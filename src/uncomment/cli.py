"""Command-line interface.

Exit codes: 0 = clean (or below fail threshold), 1 = gated findings,
2 = bad input (path, baseline, config) or environment error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .config import load_config, parse_disable_arg
from .extract import extract_file
from .languages import EXTENSIONS
from .model import Severity, ToolError
from .report import RENDERERS, to_ascii
from .rules import GATE_SIGNALS, all_rules, run_rules

SKIP_DIRS = frozenset(
    {".git", ".hg", ".svn", "node_modules", "target", "build", "dist", "out",
     "vendor", "third_party", ".venv", "venv", "__pycache__", ".idea", ".vscode"}
)


def discover_files(paths: list[Path], cfg=None, unsupported=None) -> list[Path]:
    """Supported source files under the given paths. Skip-dirs apply only to
    directories *below* a scanned root, so a project living inside a directory
    named `build` or `vendor` still scans, and skipped trees (node_modules,
    .git) are pruned without being walked. Include/exclude globs, gitignore,
    and generated-file markers filter walked trees; a file named explicitly
    always scans. Duplicates are returned once."""
    from .filtering import drop_gitignored, is_cachedir_tagged, is_generated, matches_any, selected

    files: list[Path] = []
    seen: set[Path] = set()

    def add(p: Path) -> None:
        resolved = p.resolve()
        if resolved not in seen:
            seen.add(resolved)
            files.append(p)

    for path in paths:
        if path.is_file():
            if path.suffix.lower() in EXTENSIONS:
                add(path)
        elif path.is_dir():
            walked: list[Path] = []
            for dirpath, dirnames, filenames in os.walk(path):
                # a signed CACHEDIR.TAG marks the whole tree as tool-made
                # cache; scanning a tagged dir AS the root remains intent
                if (
                    "CACHEDIR.TAG" in filenames
                    and Path(dirpath) != path
                    and is_cachedir_tagged(Path(dirpath))
                ):
                    dirnames[:] = []
                    continue

                def rel_of(name: str) -> str:
                    return (Path(dirpath) / name).relative_to(path).as_posix()

                # dirs prune on exclude only: an include like "src/**" must
                # not prune the parents of the files it selects
                dirnames[:] = sorted(
                    d for d in dirnames
                    if d not in SKIP_DIRS
                    and (cfg is None or not matches_any(rel_of(d), cfg.exclude))
                )
                for fname in sorted(filenames):
                    suffix = Path(fname).suffix.lower()
                    if suffix not in EXTENSIONS:
                        # tally what the walk passes over, so a tree of
                        # unsupported source files is a visible coverage gap
                        if unsupported is not None and suffix:
                            unsupported[suffix] += 1
                        continue
                    if cfg is not None and not selected(rel_of(fname), cfg):
                        continue
                    walked.append(Path(dirpath) / fname)
            if cfg is not None and cfg.respect_gitignore:
                walked = drop_gitignored(path, walked)
            for f in walked:
                if cfg is not None and cfg.skip_generated and is_generated(f):
                    continue
                add(f)
    return files


def _validated_paths(raw_paths: list[str]) -> list[Path]:
    paths = []
    for raw in raw_paths:
        p = Path(raw)
        if not p.exists():
            raise ToolError(f"path does not exist: {raw}")
        paths.append(p)
    return paths


def _skipped_explicit(paths: list[Path]) -> int:
    return sum(1 for p in paths if p.is_file() and p.suffix.lower() not in EXTENSIONS)


def _load_config(args) -> object:
    cfg = load_config(args.paths[0] if args.paths else ".", args.config)
    if args.disable:
        cfg.disable = list(cfg.disable) + parse_disable_arg(args.disable)
    cfg.include = list(cfg.include) + args.include
    cfg.exclude = list(cfg.exclude) + args.exclude
    return cfg


def _severity_arg(name: str) -> Severity | None:
    return None if name == "never" else Severity.parse(name)


# whether stdout could encode UTF-8 before main() reconfigured it; drives the
# automatic ASCII fallback for legacy Windows consoles and cp125x pipes
_STDOUT_WAS_UTF8 = True


def _emit_and_exit(findings, stats, args, cfg) -> int:
    out = RENDERERS[args.format](findings, stats, cfg)
    unicode_ok = cfg.unicode_output if cfg.unicode_output is not None else _STDOUT_WAS_UTF8
    if args.ascii or not unicode_ok:
        out = to_ascii(out)
    print(out)
    fail_on = _severity_arg(args.fail_on)
    if fail_on is not None and any(f.severity >= fail_on for f in findings):
        return 1
    return 0


def cmd_check(args) -> int:
    from collections import Counter

    paths = _validated_paths(args.paths)
    cfg = _load_config(args)
    unsupported: Counter = Counter()
    files = discover_files(paths, cfg, unsupported)
    skipped = _skipped_explicit(paths)
    if skipped:
        print(f"uncomment: note: {skipped} unsupported file(s) skipped", file=sys.stderr)
    notable = [(ext, n) for ext, n in unsupported.most_common(5) if n >= 5]
    if notable:
        shown = ", ".join(f"{ext} x{n}" for ext, n in notable)
        print(
            f"uncomment: note: {sum(unsupported.values())} file(s) in unsupported "
            f"languages not scanned ({shown})",
            file=sys.stderr,
        )
    findings = []
    for f in files:
        sf = extract_file(f)
        if sf is not None:
            findings.extend(run_rules(sf, cfg))
    stats = {
        "mode": "check",
        "files_scanned": len(files),
        "files_skipped": skipped,
        "files_unsupported": sum(unsupported.values()),
    }
    return _emit_and_exit(findings, stats, args, cfg)


def _read_diff(source: str) -> str:
    if source == "-":
        # read stdin as bytes: console/pipe encodings are unreliable on Windows
        return sys.stdin.buffer.read().decode("utf-8-sig", "replace")
    p = Path(source)
    if not p.is_file():
        raise ToolError(f"diff file does not exist: {source}")
    return p.read_text(encoding="utf-8-sig", errors="replace")


def cmd_gate(args) -> int:
    from .gate import gate_changes, gate_diff, gate_paths, validate_baseline

    cfg = _load_config(args)
    if args.diff and args.baseline:
        raise ToolError("--diff and --baseline are mutually exclusive")
    if args.diff:
        restrict = _validated_paths(args.paths) if args.paths else None
        result = gate_diff(_read_diff(args.diff), cfg, restrict)
        skipped = result.files_skipped
        baseline_label = f"diff:{'stdin' if args.diff == '-' else args.diff}"
    elif not args.baseline:
        raise ToolError("gate needs --baseline DIR|FILE|git:REF or --diff FILE|-")
    elif not args.paths:
        # the pathless form: git supplies the changed-file list
        if not args.baseline.startswith("git:"):
            raise ToolError("gate without paths needs a git: baseline (or --diff)")
        validate_baseline(args.baseline, Path("."))
        result = gate_changes(args.baseline[4:], cfg)
        skipped = result.files_skipped
        baseline_label = args.baseline
    else:
        paths = _validated_paths(args.paths)
        validate_baseline(args.baseline, paths[0])
        result = gate_paths(paths, args.baseline, cfg)
        skipped = _skipped_explicit(paths)
        baseline_label = args.baseline
    stats = {
        "mode": "gate",
        "baseline": baseline_label,
        "files_scanned": result.files_scanned,
        "files_skipped": skipped,
        "new_comments": result.new_comments,
        "new_comment_lines": result.new_comment_lines,
        "added_code_lines": result.added_code_lines,
    }
    return _emit_and_exit(result.findings, stats, args, cfg)


def cmd_verify(args) -> int:
    from .gate import verify_comments_only

    problems = verify_comments_only(_read_diff(args.diff))
    if problems:
        for path, detail in problems:
            print(f"{path}: NOT comment-only: {detail}")
        print(f"\n{len(problems)} file(s) with non-comment changes")
        return 1
    print("diff is comment-only")
    return 0


def cmd_rules(args) -> int:
    if args.format == "json":
        doc = [
            {"id": r.id, "severity": r.severity.name.lower(), "title": r.title,
             "doc": r.doc, "gate_only": False}
            for r in all_rules()
        ] + [
            {"id": rid, "severity": sev, "title": title, "doc": doc_text, "gate_only": True}
            for rid, sev, title, doc_text in GATE_SIGNALS
        ]
        print(json.dumps(doc, indent=2))
        return 0
    for r in all_rules():
        print(f"{r.id}  [{r.severity.name.lower():5}]  {r.title}")
        if r.doc:
            print(f"       {r.doc}")
    for rid, sev, title, doc_text in GATE_SIGNALS:
        print(f"{rid}  [{sev:5}]  {title}")
        print(f"       {doc_text}")
    return 0


def _add_common(p: argparse.ArgumentParser, paths_required: bool = True) -> None:
    p.add_argument("paths", nargs="+" if paths_required else "*",
                   help="files or directories to scan"
                   + ("" if paths_required else " (optional with --diff: restricts to these paths)"))
    p.add_argument("--format", choices=sorted(RENDERERS), default="text")
    p.add_argument("--fail-on", choices=["info", "warn", "error", "never"], default="warn",
                   help="lowest severity that causes exit code 1 (default: warn)")
    p.add_argument("--config", help="explicit config file (TOML)")
    p.add_argument("--disable", help="comma-separated rule ids/prefixes to disable (e.g. STE,UC011)")
    p.add_argument("--include", action="append", default=[], metavar="GLOB",
                   help="scan only files matching one of these patterns (repeatable; adds to config)")
    p.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                   help="skip files/directories matching this pattern (repeatable; adds to config)")
    p.add_argument("--ascii", action="store_true",
                   help="restrict output to ASCII (also settable via unicode-output = false)")


def main(argv: list[str] | None = None) -> int:
    # Windows consoles and pipes often default to legacy codepages; findings
    # quote source comments, so the output must survive any encoding. The
    # original encoding is remembered: a non-UTF-8 stdout means the CONSUMER
    # is a legacy console/pipe, so output falls back to ASCII unless the
    # config pins unicode-output explicitly.
    global _STDOUT_WAS_UTF8
    enc = getattr(sys.stdout, "encoding", None) or ""
    _STDOUT_WAS_UTF8 = "utf" in enc.lower()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        prog="uncomment",
        description="Lint and gate overly detailed comments introduced by coding agents.",
    )
    parser.add_argument("--version", action="version", version=f"uncomment {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="scan all comments in the given paths")
    _add_common(p_check)
    p_check.set_defaults(fn=cmd_check)

    p_gate = sub.add_parser("gate", help="judge only comments new relative to a baseline")
    _add_common(p_gate, paths_required=False)
    p_gate.add_argument("--baseline",
                        help="baseline dir/file, or git:REF (e.g. git:HEAD, git:main)")
    p_gate.add_argument("--diff", metavar="FILE",
                        help="gate the files a unified diff changed, using the diff itself as the "
                             "baseline ('-' reads the diff from stdin)")
    p_gate.set_defaults(fn=cmd_gate)

    p_verify = sub.add_parser(
        "verify", help="prove a unified diff touches comments only (for autonomous fixer loops)"
    )
    p_verify.add_argument("--diff", metavar="FILE", required=True,
                          help="unified diff to verify ('-' reads stdin)")
    p_verify.set_defaults(fn=cmd_verify)

    p_rules = sub.add_parser("rules", help="list rules")
    p_rules.add_argument("--format", choices=["text", "json"], default="text")
    p_rules.set_defaults(fn=cmd_rules)

    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except (ToolError, OSError) as exc:
        print(f"uncomment: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

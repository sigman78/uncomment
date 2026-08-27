"""Command-line interface.

Exit codes: 0 = clean (or below fail threshold), 1 = gated findings, 2 = usage error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .extract import extract_file
from .languages import EXTENSIONS
from .model import Severity
from .report import RENDERERS
from .rules import all_rules, run_rules

SKIP_DIRS = frozenset(
    {".git", ".hg", ".svn", "node_modules", "target", "build", "dist", "out",
     "vendor", "third_party", ".venv", "venv", "__pycache__", ".idea", ".vscode"}
)


def discover_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            if path.suffix.lower() in EXTENSIONS:
                files.append(path)
        elif path.is_dir():
            for p in sorted(path.rglob("*")):
                if p.is_file() and p.suffix.lower() in EXTENSIONS and not (set(p.parts) & SKIP_DIRS):
                    files.append(p)
    return files


def _severity_arg(name: str) -> Severity | None:
    return None if name == "never" else Severity.parse(name)


def _emit_and_exit(findings, stats, fmt: str, fail_on: Severity | None) -> int:
    print(RENDERERS[fmt](findings, stats))
    if fail_on is not None and any(f.severity >= fail_on for f in findings):
        return 1
    return 0


def cmd_check(args) -> int:
    cfg = load_config(args.paths[0] if args.paths else ".", args.config)
    if args.disable:
        cfg.disable = list(cfg.disable) + args.disable.split(",")
    findings = []
    files = discover_files([Path(p) for p in args.paths])
    for f in files:
        sf = extract_file(f)
        if sf is not None:
            findings.extend(run_rules(sf, cfg))
    stats = {"mode": "check", "files_scanned": len(files)}
    return _emit_and_exit(findings, stats, args.format, _severity_arg(args.fail_on))


def cmd_gate(args) -> int:
    from .gate import gate_paths

    cfg = load_config(args.paths[0] if args.paths else ".", args.config)
    if args.disable:
        cfg.disable = list(cfg.disable) + args.disable.split(",")
    result = gate_paths([Path(p) for p in args.paths], args.baseline, cfg)
    stats = {
        "mode": "gate",
        "baseline": args.baseline,
        "files_scanned": result.files_scanned,
        "new_comments": result.new_comments,
        "new_comment_lines": result.new_comment_lines,
        "added_code_lines": result.added_code_lines,
    }
    return _emit_and_exit(result.findings, stats, args.format, _severity_arg(args.fail_on))


def cmd_rules(args) -> int:
    for r in all_rules():
        print(f"{r.id}  [{r.severity.name.lower():5}]  {r.title}")
        if r.doc:
            print(f"       {r.doc}")
    return 0


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("paths", nargs="+", help="files or directories to scan")
    p.add_argument("--format", choices=sorted(RENDERERS), default="text")
    p.add_argument("--fail-on", choices=["info", "warn", "error", "never"], default="warn",
                   help="lowest severity that causes exit code 1 (default: warn)")
    p.add_argument("--config", help="explicit config file (TOML)")
    p.add_argument("--disable", help="comma-separated rule ids/prefixes to disable (e.g. STE,UC011)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="uncomment",
        description="Lint and gate overly detailed comments introduced by coding agents.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="scan all comments in the given paths")
    _add_common(p_check)
    p_check.set_defaults(fn=cmd_check)

    p_gate = sub.add_parser("gate", help="judge only comments new relative to a baseline")
    _add_common(p_gate)
    p_gate.add_argument("--baseline", required=True,
                        help="baseline dir/file, or git:REF (e.g. git:HEAD, git:main)")
    p_gate.set_defaults(fn=cmd_gate)

    p_rules = sub.add_parser("rules", help="list rules")
    p_rules.set_defaults(fn=cmd_rules)

    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except (OSError, ValueError) as exc:
        print(f"uncomment: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

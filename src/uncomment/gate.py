"""Gate mode: judge only comments that are NEW relative to a baseline.

The baseline is an older copy of the tree (directory, single file, or a git
ref via "git:REF"). Comments are matched by normalized content, so moved
comments are not re-flagged; added or reworded ones are.
"""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .extract import extract_file, extract_source
from .languages import spec_for_path
from .model import Comment, Finding, Severity, SourceFile
from .rules import run_rules, visible_comments

_WS_RE = re.compile(r"\s+")


def _norm(comment: Comment) -> str:
    return _WS_RE.sub(" ", comment.content).strip().lower()


@dataclass
class GateResult:
    findings: list[Finding] = field(default_factory=list)
    files_scanned: int = 0
    new_comments: int = 0
    new_comment_lines: int = 0
    added_code_lines: int = 0


def _baseline_source(baseline: str, new_path: Path, new_root: Path) -> str | None:
    """Return the baseline text for new_path, or None if it has no baseline."""
    if baseline.startswith("git:"):
        ref = baseline[4:] or "HEAD"
        try:
            top = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=new_path.parent, capture_output=True, text=True, check=True,
            ).stdout.strip()
            rel = new_path.resolve().relative_to(Path(top).resolve()).as_posix()
            out = subprocess.run(
                ["git", "show", f"{ref}:{rel}"],
                cwd=top, capture_output=True, check=True,
            )
            return out.stdout.decode("utf-8", "replace")
        except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
            return None
    base = Path(baseline)
    if base.is_file():
        candidate = base
    else:
        try:
            rel = new_path.resolve().relative_to(new_root.resolve())
        except ValueError:
            rel = Path(new_path.name)
        candidate = base / rel
    if candidate.is_file():
        return candidate.read_text(encoding="utf-8", errors="replace")
    return None


def gate_file(new_path: Path, baseline: str, new_root: Path, cfg: Config) -> tuple[list[Finding], SourceFile | None, dict]:
    sf = extract_file(new_path)
    stats = {"new_comments": 0, "new_comment_lines": 0, "added_code_lines": 0}
    if sf is None:
        return [], None, stats

    old_source = _baseline_source(baseline, new_path, new_root)
    if old_source is not None:
        spec = spec_for_path(str(new_path))
        old_sf = extract_source(str(new_path), old_source, spec)
        old_counts = Counter(_norm(c) for c in visible_comments(old_sf, cfg))
        old_code_lines = old_sf.code_line_count
    else:
        old_counts = Counter()
        old_code_lines = 0

    # directives (nolint, go:build, eslint-disable, …) are functional lines,
    # not comment noise: they neither gate nor count toward the flood metric
    new_comments: list[Comment] = []
    for c in visible_comments(sf, cfg):
        key = _norm(c)
        if old_counts[key] > 0:
            old_counts[key] -= 1
        else:
            new_comments.append(c)

    stats["new_comments"] = len(new_comments)
    stats["new_comment_lines"] = sum(c.line_count for c in new_comments)
    stats["added_code_lines"] = max(0, sf.code_line_count - old_code_lines)

    new_spans = [(c.start_line, c.end_line) for c in new_comments]

    def touches_new(f: Finding) -> bool:
        return any(not (b < f.line or a > f.end_line) for a, b in new_spans)

    findings = [f for f in run_rules(sf, cfg) if touches_new(f)]

    # comment flood: a sudden large amount of comment lines relative to added code
    if (
        stats["new_comment_lines"] >= cfg.flood_min_lines
        and stats["new_comment_lines"] > cfg.flood_ratio * max(stats["added_code_lines"], 1)
    ):
        findings.append(
            Finding(
                rule="UC100",
                severity=Severity.ERROR,
                path=str(new_path),
                line=new_comments[0].start_line,
                end_line=new_comments[-1].end_line,
                message=(
                    f"comment flood: {stats['new_comment_lines']} new comment lines vs "
                    f"{stats['added_code_lines']} new code lines"
                ),
                action=(
                    "This edit added far more comment than code. Re-read every new comment and delete those "
                    "that restate code, narrate the process, or describe the edit. Keep only WHY notes."
                ),
                excerpt="",
            )
        )
    findings.sort(key=lambda f: (f.line, f.rule))
    return findings, sf, stats


def gate_paths(paths: list[Path], baseline: str, cfg: Config, root: Path | None = None) -> GateResult:
    from .cli import discover_files  # shared discovery, avoids duplication

    result = GateResult()
    for path in paths:
        file_root = path if path.is_dir() else path.parent
        for f in discover_files([path]):
            findings, sf, stats = gate_file(f, baseline, root or file_root, cfg)
            if sf is None:
                continue
            result.files_scanned += 1
            result.findings.extend(findings)
            result.new_comments += stats["new_comments"]
            result.new_comment_lines += stats["new_comment_lines"]
            result.added_code_lines += stats["added_code_lines"]
    result.findings.sort(key=lambda f: (f.path, f.line, f.rule))
    return result

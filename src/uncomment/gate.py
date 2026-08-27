"""Gate mode: judge only comments that are NEW relative to a baseline.

The baseline is an older copy of the tree (directory, single file, or a git
ref via "git:REF"). Matching runs in stages so ordinary edits are not
re-judged:

1. exact match against the same file's baseline (normalized content),
2. exact match against leftover baseline comments from the other scanned
   files (cross-file moves),
3. when a scanned file has no baseline counterpart (renames, new files),
   exact match against the rest of the baseline tree,
4. fuzzy match (similarity >= baseline_similarity) so typo fixes and light
   rewording do not count as new.

The comment-flood signal (UC100) counts only NOISY new comment lines — new
comments that triggered at least one finding — so license headers and clean
documentation never flood."""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from .config import Config
from .extract import extract_file, extract_source
from .languages import EXTENSIONS, spec_for_path
from .model import Comment, Finding, Severity, SourceFile, ToolError
from .rules import run_rules, visible_comments

_WS_RE = re.compile(r"\s+")


def validate_baseline(baseline: str, anchor: Path) -> None:
    """Fail fast (exit 2) on an unusable baseline instead of silently judging
    every existing comment as new. A per-file miss inside a valid baseline
    still means 'new file' and stays permitted."""
    if baseline.startswith("git:"):
        ref = baseline[4:] or "HEAD"
        anchor_dir = anchor if anchor.is_dir() else anchor.parent
        try:
            subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                cwd=anchor_dir, capture_output=True, check=True,
            )
        except FileNotFoundError:
            raise ToolError("git executable not found; a git: baseline needs git on PATH") from None
        except subprocess.CalledProcessError:
            raise ToolError(
                f"baseline ref '{ref}' not found (is {anchor_dir} inside a git repository?)"
            ) from None
    elif not Path(baseline).exists():
        raise ToolError(f"baseline path does not exist: {baseline}")


def _norm(comment: Comment) -> str:
    return _WS_RE.sub(" ", comment.content).strip().lower()


def _similar(a: str, b: str, threshold: float) -> bool:
    if not a or not b:
        return False
    if min(len(a), len(b)) / max(len(a), len(b)) < 0.5:
        return False
    sm = SequenceMatcher(None, a, b)
    if sm.real_quick_ratio() < threshold or sm.quick_ratio() < threshold:
        return False
    return sm.ratio() >= threshold


@dataclass
class GateResult:
    findings: list[Finding] = field(default_factory=list)
    files_scanned: int = 0
    new_comments: int = 0
    new_comment_lines: int = 0
    added_code_lines: int = 0


@dataclass
class _FileState:
    path: Path
    sf: SourceFile
    unmatched: list[Comment]
    added_code_lines: int
    had_counterpart: bool


def _git_repo_top(anchor_dir: Path) -> Path | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=anchor_dir, capture_output=True, text=True, check=True,
        ).stdout.strip()
        return Path(out)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _baseline_source(baseline: str, new_path: Path, new_root: Path) -> tuple[str | None, object]:
    """Return (text, identity) for new_path's baseline counterpart; identity
    keys the file so the tree sweep can skip already-consumed counterparts."""
    if baseline.startswith("git:"):
        ref = baseline[4:] or "HEAD"
        top = _git_repo_top(new_path.parent)
        if top is None:
            return None, None
        try:
            rel = new_path.resolve().relative_to(top.resolve()).as_posix()
        except ValueError:
            return None, None
        try:
            out = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=top, capture_output=True, check=True)
            return out.stdout.decode("utf-8-sig", "replace"), rel
        except subprocess.CalledProcessError:
            return None, rel
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
        return candidate.read_text(encoding="utf-8-sig", errors="replace"), candidate.resolve()
    return None, candidate.resolve()


def _tree_norms(baseline: str, anchor: Path, consumed: set, cfg: Config) -> Counter:
    """Comment norms from baseline files that were not per-file counterparts —
    loaded only when a scanned file lacks a counterpart (rename/new file)."""
    pool: Counter = Counter()

    def absorb(path_label: str, text: str) -> None:
        spec = spec_for_path(path_label)
        if spec is None:
            return
        sf = extract_source(path_label, text, spec)
        pool.update(_norm(c) for c in visible_comments(sf, cfg))

    if baseline.startswith("git:"):
        ref = baseline[4:] or "HEAD"
        top = _git_repo_top(anchor if anchor.is_dir() else anchor.parent)
        if top is None:
            return pool
        try:
            listing = subprocess.run(
                ["git", "ls-tree", "-r", "--name-only", ref],
                cwd=top, capture_output=True, text=True, check=True,
            ).stdout.splitlines()
        except subprocess.CalledProcessError:
            return pool
        for rel in listing:
            if rel in consumed or Path(rel).suffix.lower() not in EXTENSIONS:
                continue
            try:
                out = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=top, capture_output=True, check=True)
            except subprocess.CalledProcessError:
                continue
            absorb(rel, out.stdout.decode("utf-8-sig", "replace"))
    else:
        base = Path(baseline)
        if base.is_dir():
            for p in sorted(base.rglob("*")):
                if not p.is_file() or p.suffix.lower() not in EXTENSIONS or p.resolve() in consumed:
                    continue
                absorb(str(p), p.read_text(encoding="utf-8-sig", errors="replace"))
    return pool


def _consume_exact(comments: list[Comment], pool: Counter) -> list[Comment]:
    leftover = []
    for c in comments:
        key = _norm(c)
        if pool[key] > 0:
            pool[key] -= 1
        else:
            leftover.append(c)
    return leftover


def _consume_fuzzy(comments: list[Comment], pool: Counter, threshold: float) -> list[Comment]:
    leftover = []
    for c in comments:
        key = _norm(c)
        match = next((old for old, n in pool.items() if n > 0 and _similar(key, old, threshold)), None)
        if match is not None:
            pool[match] -= 1
        else:
            leftover.append(c)
    return leftover


def _finalize(st: _FileState, cfg: Config) -> list[Finding]:
    new_spans = [(c.start_line, c.end_line) for c in st.unmatched]

    def touches_new(f: Finding) -> bool:
        return any(not (b < f.line or a > f.end_line) for a, b in new_spans)

    findings = [f for f in run_rules(st.sf, cfg) if touches_new(f)]

    # flood counts only noisy lines: new comments with at least one finding.
    # A license header or clean documentation never floods.
    def is_noisy(c: Comment) -> bool:
        return any(not (c.end_line < f.line or c.start_line > f.end_line) for f in findings)

    noisy_lines = sum(c.line_count for c in st.unmatched if is_noisy(c))
    if noisy_lines >= cfg.flood_min_lines and noisy_lines > cfg.flood_ratio * max(st.added_code_lines, 1):
        noisy = [c for c in st.unmatched if is_noisy(c)]
        findings.append(
            Finding(
                rule="UC100",
                severity=Severity.ERROR,
                path=str(st.path),
                line=noisy[0].start_line,
                end_line=noisy[-1].end_line,
                message=(
                    f"comment flood: {noisy_lines} noisy new comment lines vs "
                    f"{st.added_code_lines} new code lines"
                ),
                action=(
                    "This edit added far more comment noise than code. Re-read every new comment and delete "
                    "those that restate code, narrate the process, or describe the edit. Keep only WHY notes."
                ),
                excerpt="",
            )
        )
    findings.sort(key=lambda f: (f.line, f.rule))
    return findings


def _gate(files: list[Path], baseline: str, cfg: Config, root_of) -> GateResult:
    states: list[_FileState] = []
    cross_pool: Counter = Counter()
    consumed: set = set()
    result = GateResult()

    for f in files:
        sf = extract_file(f)
        if sf is None:
            continue
        old_source, identity = _baseline_source(baseline, f, root_of(f))
        if identity is not None:
            consumed.add(identity)
        old_norms: Counter = Counter()
        old_code_lines = 0
        if old_source is not None:
            spec = spec_for_path(str(f))
            old_sf = extract_source(str(f), old_source, spec)
            old_norms = Counter(_norm(c) for c in visible_comments(old_sf, cfg))
            old_code_lines = old_sf.code_line_count
        unmatched = _consume_exact(visible_comments(sf, cfg), old_norms)
        cross_pool += old_norms  # leftovers feed cross-file matching
        states.append(
            _FileState(
                path=f,
                sf=sf,
                unmatched=unmatched,
                added_code_lines=max(0, sf.code_line_count - old_code_lines),
                had_counterpart=old_source is not None,
            )
        )

    leftovers = any(st.unmatched for st in states)
    if leftovers:
        # renames and file splits: pull in the rest of the baseline tree
        if any(not st.had_counterpart for st in states):
            cross_pool += _tree_norms(baseline, files[0], consumed, cfg)
        for st in states:
            st.unmatched = _consume_exact(st.unmatched, cross_pool)
        for st in states:
            st.unmatched = _consume_fuzzy(st.unmatched, cross_pool, cfg.baseline_similarity)

    for st in states:
        result.files_scanned += 1
        result.findings.extend(_finalize(st, cfg))
        result.new_comments += len(st.unmatched)
        result.new_comment_lines += sum(c.line_count for c in st.unmatched)
        result.added_code_lines += st.added_code_lines
    result.findings.sort(key=lambda f: (f.path, f.line, f.rule))
    return result


def gate_paths(paths: list[Path], baseline: str, cfg: Config, root: Path | None = None) -> GateResult:
    from .cli import discover_files  # shared discovery, avoids duplication

    roots = {}
    files: list[Path] = []
    for path in paths:
        file_root = root or (path if path.is_dir() else path.parent)
        for f in discover_files([path]):
            if f not in roots:
                roots[f] = file_root
                files.append(f)
    return _gate(files, baseline, cfg, lambda f: roots[f])


def gate_file(new_path: Path, baseline: str, new_root: Path, cfg: Config) -> tuple[list[Finding], SourceFile | None, dict]:
    """Single-file convenience wrapper used by tests and simple hooks."""
    sf = extract_file(new_path)
    if sf is None:
        return [], None, {"new_comments": 0, "new_comment_lines": 0, "added_code_lines": 0}
    result = _gate([Path(new_path)], baseline, cfg, lambda f: new_root)
    stats = {
        "new_comments": result.new_comments,
        "new_comment_lines": result.new_comment_lines,
        "added_code_lines": result.added_code_lines,
    }
    return result.findings, sf, stats

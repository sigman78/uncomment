"""Gate mode: judge only comments that are NEW relative to a baseline.

The baseline is an older copy of the tree (directory, single file, a git ref
via "git:REF", or a unified diff whose reverse gives the old content).
Matching runs in stages so ordinary edits are not re-judged:

1. exact match against the same file's baseline (normalized content),
2. exact match against leftover baseline comments from the other scanned
   files (cross-file moves),
3. when a scanned file has no baseline counterpart (renames, new files),
   exact match against the rest of the baseline tree,
4. fuzzy match (similarity >= baseline_similarity) so typo fixes and light
   rewording do not count as new.

Baseline access goes through a provider object; the git provider keeps one
`git cat-file --batch` process per repository so gating hundreds of files
costs two subprocesses, not two per file.

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
from .model import Comment, Finding, Kind, Severity, SourceFile, ToolError
from .rules import (
    _IGNORE_FILE_RE,
    file_suppressed_rules,
    file_wide_rules,
    is_license_header,
    marker_line_count,
    run_rules,
    visible_comments,
)

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
    files_skipped: int = 0
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
    old_prose_lines: int = 0
    new_prose_lines: int = 0  # ALL visible prose lines in the new file
    old_file_wide: frozenset = frozenset()  # baseline's file-wide marker grants


_repo_top_cache: dict[Path, Path | None] = {}


def _git_repo_top(anchor_dir: Path) -> Path | None:
    """One `git rev-parse` per directory, not per file — gates over hundreds
    of files in one tree pay for a single subprocess."""
    key = anchor_dir.resolve()
    if key not in _repo_top_cache:
        try:
            out = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=anchor_dir, capture_output=True, text=True, check=True,
            ).stdout.strip()
            _repo_top_cache[key] = Path(out)
        except (subprocess.CalledProcessError, FileNotFoundError):
            _repo_top_cache[key] = None
    return _repo_top_cache[key]


class _CatFileBatch:
    """One persistent `git cat-file --batch` process per repository. Requests
    are `REF:path` lines on stdin; a dead process is a hard error, never a
    silent 'everything is new'."""

    def __init__(self, top: Path):
        self.top = top
        try:
            self._proc = subprocess.Popen(
                ["git", "cat-file", "--batch"],
                cwd=top, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            raise ToolError("git executable not found; a git: baseline needs git on PATH") from None

    def read(self, spec: str) -> bytes | None:
        proc = self._proc
        try:
            proc.stdin.write(spec.encode("utf-8") + b"\n")
            proc.stdin.flush()
            header = proc.stdout.readline()
        except OSError:
            header = b""
        if not header:
            raise ToolError(f"git cat-file exited unexpectedly while reading '{spec}'")
        parts = header.decode("utf-8", "replace").split()
        if len(parts) != 3 or not parts[2].isdigit():
            return None  # "<spec> missing" (or ambiguous/dangling)
        size = int(parts[2])
        data = proc.stdout.read(size + 1)[:size]  # payload + trailing LF
        if len(data) < size:
            raise ToolError(f"git cat-file exited unexpectedly while reading '{spec}'")
        return data if parts[1] == "blob" else None

    def close(self) -> None:
        try:
            self._proc.stdin.close()
        except OSError:
            pass
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()


class _PathBaseline:
    """Baseline is a directory tree or a single file on disk."""

    def __init__(self, baseline: str):
        self.base = Path(baseline)

    def source_for(self, new_path: Path, new_root: Path) -> tuple[str | None, object]:
        if self.base.is_file():
            candidate = self.base
        else:
            try:
                rel = new_path.resolve().relative_to(new_root.resolve())
            except ValueError:
                rel = Path(new_path.name)
            candidate = self.base / rel
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8-sig", errors="replace"), candidate.resolve()
        return None, candidate.resolve()

    def tree_files(self, anchor: Path, consumed: set, cfg: Config) -> list[tuple[str, str]]:
        from .filtering import selected

        out = []
        if self.base.is_dir():
            for p in sorted(self.base.rglob("*")):
                if not p.is_file() or p.suffix.lower() not in EXTENSIONS or p.resolve() in consumed:
                    continue
                if not selected(p.relative_to(self.base).as_posix(), cfg):
                    continue
                out.append((str(p), p.read_text(encoding="utf-8-sig", errors="replace")))
        return out

    def close(self) -> None:
        pass


class _GitBaseline:
    """Baseline is a git ref; file content comes from one cat-file batch
    process per repository top."""

    def __init__(self, ref: str):
        self.ref = ref or "HEAD"
        self._batches: dict[Path, _CatFileBatch] = {}

    def _batch(self, top: Path) -> _CatFileBatch:
        if top not in self._batches:
            self._batches[top] = _CatFileBatch(top)
        return self._batches[top]

    def source_for(self, new_path: Path, new_root: Path) -> tuple[str | None, object]:
        top = _git_repo_top(new_path.parent)
        if top is None:
            return None, None
        try:
            rel = new_path.resolve().relative_to(top.resolve()).as_posix()
        except ValueError:
            return None, None
        data = self._batch(top).read(f"{self.ref}:{rel}")
        if data is None:
            return None, rel
        return data.decode("utf-8-sig", "replace"), rel

    def tree_files(self, anchor: Path, consumed: set, cfg: Config) -> list[tuple[str, str]]:
        from .filtering import selected

        top = _git_repo_top(anchor if anchor.is_dir() else anchor.parent)
        if top is None:
            return []
        try:
            listing = subprocess.run(
                ["git", "ls-tree", "-r", "--name-only", self.ref],
                cwd=top, capture_output=True, text=True, check=True,
            ).stdout.splitlines()
        except subprocess.CalledProcessError:
            return []
        out = []
        batch = self._batch(top)
        for rel in listing:
            if rel in consumed or Path(rel).suffix.lower() not in EXTENSIONS or not selected(rel, cfg):
                continue
            data = batch.read(f"{self.ref}:{rel}")
            if data is not None:
                out.append((rel, data.decode("utf-8-sig", "replace")))
        return out

    def close(self) -> None:
        for batch in self._batches.values():
            batch.close()


class _DiffBaseline:
    """Baseline is the reverse of a unified diff: old content was rebuilt per
    file up front (None = file created by the diff). The diff defines the
    whole edit, so there is no wider tree to sweep."""

    def __init__(self, old_texts: dict[Path, str | None]):
        self._old = old_texts

    def source_for(self, new_path: Path, new_root: Path) -> tuple[str | None, object]:
        key = new_path.resolve()
        return self._old.get(key), key

    def tree_files(self, anchor: Path, consumed: set, cfg: Config) -> list[tuple[str, str]]:
        return []

    def close(self) -> None:
        pass


def _provider_for(baseline: str):
    if baseline.startswith("git:"):
        return _GitBaseline(baseline[4:])
    return _PathBaseline(baseline)


def _tree_norms(provider, anchor: Path, consumed: set, cfg: Config) -> Counter:
    """Comment norms from baseline files that were not per-file counterparts —
    loaded only when a scanned file lacks a counterpart (rename/new file)."""
    pool: Counter = Counter()
    for path_label, text in provider.tree_files(anchor, consumed, cfg):
        spec = spec_for_path(path_label)
        if spec is None:
            continue
        sf = extract_source(path_label, text, spec)
        pool.update(_norm(c) for c in visible_comments(sf, cfg))
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


def _prose_comments(comments: list[Comment]) -> list[Comment]:
    """Comments that are neither documentation nor license text — the kind an
    over-eager agent multiplies."""
    return [c for c in comments if c.kind is not Kind.DOC and not is_license_header(c)]


def _prose_lines(comments: list[Comment]) -> int:
    return sum(c.line_count - marker_line_count(c) for c in _prose_comments(comments))


def _finalize(st: _FileState, cfg: Config) -> list[Finding]:
    new_spans = [(c.start_line, c.end_line) for c in st.unmatched]

    def touches_new(f: Finding) -> bool:
        return any(not (b < f.line or a > f.end_line) for a, b in new_spans)

    findings = [f for f in run_rules(st.sf, cfg) if touches_new(f)]
    rule_findings = list(findings)  # per-comment findings only; UC100's noise
    # measure must not count the aggregate UC101 signal below

    # UC101 comment amplification: the "sees comments, writes more comments"
    # pattern. Fires on NET growth of the file's prose volume, so an in-place
    # rewrite (old comments replaced by reworded ones) is not amplification —
    # only a file whose prose actually multiplied is. Elaboration sprees are
    # still caught even when every comment evades the per-comment rules.
    # the file-level gate signals honor an explicit uncomment-ignore[RULE]
    # anywhere in the file — span-scoped markers cannot reach them
    file_sups = file_suppressed_rules(st.sf)

    net_growth = st.new_prose_lines - st.old_prose_lines
    prose_comments = _prose_comments(st.unmatched)
    if (
        "UC101" not in file_sups
        and st.had_counterpart
        and st.old_prose_lines > 0
        and prose_comments
        and net_growth >= cfg.growth_min_lines
        and net_growth >= cfg.growth_factor * st.old_prose_lines
    ):
        findings.append(
            Finding(
                rule="UC101",
                severity=Severity.WARN,
                path=str(st.path),
                line=prose_comments[0].start_line,
                end_line=prose_comments[-1].end_line,
                message=(
                    f"comment amplification: prose comments grew from {st.old_prose_lines} "
                    f"to {st.new_prose_lines} lines"
                ),
                action=(
                    "This edit multiplied the file's comments. Existing comments are not an invitation "
                    "to add more: re-read every comment you added and keep only those stating a WHY the "
                    "code cannot express. Delete elaborations, restatements, and section labels."
                ),
                excerpt="",
            )
        )

    # flood counts only noisy lines: new NON-DOC comments with at least one
    # warn/error finding. License headers and API docs never flood, and
    # info-tier hints (STE wording) can never compound into an error.
    gating_findings = [f for f in rule_findings if f.severity >= Severity.WARN]

    def is_noisy(c: Comment) -> bool:
        return c.kind is not Kind.DOC and any(
            not (c.end_line < f.line or c.start_line > f.end_line) for f in gating_findings
        )

    noisy_lines = sum(c.line_count for c in st.unmatched if is_noisy(c))
    if (
        "UC100" not in file_sups
        and noisy_lines >= cfg.flood_min_lines
        and noisy_lines > cfg.flood_ratio * max(st.added_code_lines, 1)
    ):
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
    # a NEW file-wide exception is itself worth a look: the escape hatch
    # stays open, but an edit granting one announces it to the reviewer
    if "UC102" not in file_sups:
        for rid in sorted(file_wide_rules(st.sf) - st.old_file_wide):
            marker = next(
                (c for c in st.sf.comments
                 if any(rid in m.group("rules") for m in _IGNORE_FILE_RE.finditer(c.content))),
                None,
            )
            if marker is None:
                continue
            findings.append(
                Finding(
                    rule="UC102",
                    severity=Severity.INFO,
                    path=str(st.path),
                    line=marker.start_line,
                    end_line=marker.end_line,
                    message=f"edit grants this file a file-wide exception for {rid}",
                    action=(
                        "Confirm the marker's reason justifies a whole-file exception; "
                        "prefer span markers when only specific comments need it."
                    ),
                    excerpt=marker.content.splitlines()[0] if marker.content else "",
                )
            )

    findings.sort(key=lambda f: (f.line, f.rule))
    return findings


def _gate(files: list[Path], provider, cfg: Config, root_of) -> GateResult:
    states: list[_FileState] = []
    cross_pool: Counter = Counter()
    consumed: set = set()
    result = GateResult()

    try:
        for f in files:
            sf = extract_file(f)
            if sf is None:
                continue
            old_source, identity = provider.source_for(f, root_of(f))
            if identity is not None:
                consumed.add(identity)
            old_norms: Counter = Counter()
            old_code_lines = 0
            old_prose_lines = 0
            old_file_wide: frozenset = frozenset()
            if old_source is not None:
                spec = spec_for_path(str(f))
                old_sf = extract_source(str(f), old_source, spec)
                old_visible = visible_comments(old_sf, cfg)
                old_norms = Counter(_norm(c) for c in old_visible)
                old_code_lines = old_sf.code_line_count
                old_prose_lines = _prose_lines(old_visible)
                old_file_wide = file_wide_rules(old_sf)
            visible_new = visible_comments(sf, cfg)
            unmatched = _consume_exact(visible_new, old_norms)
            cross_pool += old_norms  # leftovers feed cross-file matching
            states.append(
                _FileState(
                    path=f,
                    sf=sf,
                    unmatched=unmatched,
                    added_code_lines=max(0, sf.code_line_count - old_code_lines),
                    had_counterpart=old_source is not None,
                    old_prose_lines=old_prose_lines,
                    new_prose_lines=_prose_lines(visible_new),
                    old_file_wide=old_file_wide,
                )
            )

        leftovers = any(st.unmatched for st in states)
        if leftovers:
            # renames and file splits: pull in the rest of the baseline tree
            if any(not st.had_counterpart for st in states):
                cross_pool += _tree_norms(provider, files[0], consumed, cfg)
            for st in states:
                st.unmatched = _consume_exact(st.unmatched, cross_pool)
            for st in states:
                st.unmatched = _consume_fuzzy(st.unmatched, cross_pool, cfg.baseline_similarity)
    finally:
        provider.close()

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
        for f in discover_files([path], cfg):
            if f not in roots:
                roots[f] = file_root
                files.append(f)
    return _gate(files, _provider_for(baseline), cfg, lambda f: roots[f])


def _locate_diff_file(rel: str, root: Path) -> Path | None:
    """git prints paths relative to the repository top, whatever the cwd:
    resolve against the given root first, then against the enclosing repo."""
    candidate = root / rel
    if candidate.is_file():
        return candidate
    top = _git_repo_top(root)
    if top is not None and (top / rel).is_file():
        return top / rel
    return None


def _split_lines(text: str) -> list[str]:
    """Split on \\n only, like diff tools and the extractor do; splitlines()
    would desync on \\f or U+2028."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # the trailing-newline artifact, not a line
    return lines


def gate_diff(diff_text: str, cfg: Config, restrict: list[Path] | None = None,
              root: Path | None = None) -> GateResult:
    """Gate using a unified diff as the baseline: new content comes from the
    working tree, old content from reverse-applying the hunks. Files the diff
    deleted, binary files, and unsupported languages are skipped; a diff that
    no longer matches the tree is a hard error."""
    from .diffio import parse_diff, reverse_apply

    root = (root or Path.cwd()).resolve()
    limits = [p.resolve() for p in restrict] if restrict else None
    old_texts: dict[Path, str | None] = {}
    files: list[Path] = []
    skipped = 0

    from .filtering import is_generated, selected

    for fp in parse_diff(diff_text):
        if fp.new_path is None or fp.binary:
            continue
        if Path(fp.new_path).suffix.lower() not in EXTENSIONS or not selected(fp.new_path, cfg):
            skipped += 1
            continue
        disk = _locate_diff_file(fp.new_path, root)
        if disk is None:
            raise ToolError(
                f"file from diff not found on disk: {fp.new_path} "
                "(stale diff, or run from the directory the diff paths are relative to)"
            )
        if cfg.skip_generated and is_generated(disk):
            skipped += 1
            continue
        resolved = disk.resolve()
        if limits is not None and not any(resolved == lim or resolved.is_relative_to(lim) for lim in limits):
            continue
        try:
            # report paths the way git prints them: relative to the cwd
            disk = resolved.relative_to(Path.cwd())
        except ValueError:
            pass
        if fp.old_path is None:
            old_texts[resolved] = None  # created by the diff: no counterpart
        else:
            new_lines = _split_lines(disk.read_text(encoding="utf-8-sig", errors="replace"))
            old_lines = reverse_apply(fp, new_lines, fp.new_path)
            old_texts[resolved] = "\n".join(old_lines) + ("\n" if old_lines else "")
        files.append(disk)

    result = _gate(files, _DiffBaseline(old_texts), cfg, lambda f: root)
    result.files_skipped = skipped
    return result


def gate_changes(ref: str, cfg: Config, root: Path | None = None) -> GateResult:
    """The pathless gate: git decides the file list — tracked files changed
    relative to REF plus untracked (not ignored) ones — and the config's
    include/exclude decides the scope. One command for hooks and fixer
    agents, no name-only piping."""
    from .filtering import is_generated, selected

    cwd = (root or Path.cwd()).resolve()
    top = _git_repo_top(cwd)
    if top is None:
        raise ToolError("gate without paths needs to run inside a git repository")

    rels: list[str] = []
    for cmd in (
        ["git", "diff", "--name-only", "-z", ref or "HEAD", "--"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    ):
        try:
            out = subprocess.run(cmd, cwd=top, capture_output=True, text=True, check=True).stdout
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "").strip().splitlines()
            raise ToolError(
                f"git could not list changes vs '{ref or 'HEAD'}'"
                + (f": {detail[0]}" if detail else "")
            ) from None
        rels.extend(r for r in out.split("\0") if r.strip())

    seen: set[str] = set()
    files: list[Path] = []
    skipped = 0
    for rel in rels:
        if rel in seen:
            continue
        seen.add(rel)
        disk = top / rel
        if not disk.is_file():
            continue  # deleted in the working tree
        if Path(rel).suffix.lower() not in EXTENSIONS or not selected(rel, cfg):
            skipped += 1
            continue
        if cfg.skip_generated and is_generated(disk):
            skipped += 1
            continue
        try:
            display = disk.resolve().relative_to(Path.cwd())
        except ValueError:
            display = disk
        files.append(display)

    result = _gate(files, _GitBaseline(ref), cfg, lambda f: top)
    result.files_skipped = skipped
    return result


def _code_fingerprint(path_label: str, text: str, spec) -> list[str]:
    """Comment-stripped, whitespace-trimmed, non-blank code lines. Two files
    with equal fingerprints differ only in comments and blank space."""
    sf = extract_source(path_label, text, spec)
    return [ln.rstrip() for ln in sf.code_lines if ln.strip()]


def verify_comments_only(diff_text: str, root: Path | None = None) -> list[tuple[str, str]]:
    """Prove a unified diff touches nothing but comments. Returns violations
    as (path, detail); empty means every change is comment-only. Built for
    autonomous comment-fixer loops: a fixer that drifted into code is caught
    here, not in review. Conservative by design — deletions, binary changes,
    and unsupported languages are violations, never assumptions."""
    from .diffio import parse_diff, reverse_apply

    root = (root or Path.cwd()).resolve()
    problems: list[tuple[str, str]] = []
    for fp in parse_diff(diff_text):
        if fp.new_path is None:
            problems.append((fp.old_path or "<unknown>", "file deleted"))
            continue
        if fp.binary:
            problems.append((fp.new_path, "binary change"))
            continue
        spec = spec_for_path(fp.new_path)
        if spec is None:
            problems.append((fp.new_path, "unsupported language, cannot verify"))
            continue
        disk = _locate_diff_file(fp.new_path, root)
        if disk is None:
            raise ToolError(
                f"file from diff not found on disk: {fp.new_path} "
                "(stale diff, or run from the directory the diff paths are relative to)"
            )
        new_text = disk.read_text(encoding="utf-8-sig", errors="replace")
        old_lines = [] if fp.old_path is None else reverse_apply(fp, _split_lines(new_text), fp.new_path)
        old_text = "\n".join(old_lines) + ("\n" if old_lines else "")
        old_code = _code_fingerprint(fp.new_path, old_text, spec)
        new_code = _code_fingerprint(fp.new_path, new_text, spec)
        if old_code != new_code:
            i = next(
                (k for k, (a, b) in enumerate(zip(old_code, new_code)) if a != b),
                min(len(old_code), len(new_code)),
            )
            near = new_code[i] if i < len(new_code) else old_code[i]
            problems.append((fp.new_path, f"code changed near: {near.strip()!r}"))
    return problems


def gate_file(new_path: Path, baseline: str, new_root: Path, cfg: Config) -> tuple[list[Finding], SourceFile | None, dict]:
    """Single-file convenience wrapper used by tests and simple hooks."""
    sf = extract_file(new_path)
    if sf is None:
        return [], None, {"new_comments": 0, "new_comment_lines": 0, "added_code_lines": 0}
    result = _gate([Path(new_path)], _provider_for(baseline), cfg, lambda f: new_root)
    stats = {
        "new_comments": result.new_comments,
        "new_comment_lines": result.new_comment_lines,
        "added_code_lines": result.added_code_lines,
    }
    return result.findings, sf, stats

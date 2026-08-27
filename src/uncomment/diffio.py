"""Unified-diff input: parse a diff and rebuild per-file baselines.

Gate mode can take the edit itself (`--diff`) instead of a baseline tree:
new content comes from the working tree and old content is rebuilt by
reverse-applying the hunks. A diff that does not match the on-disk file is a
hard error (exit 2) — a stale diff must never silently mis-judge comments.

Accepted syntax: git diffs (`diff --git` sections with renames, new/deleted
files, binary markers) and plain `---`/`+++` unified diffs such as
`difflib.unified_diff` output. Payload comparison ignores \r so LF/CRLF
mismatches between the diff and the working tree do not false-fail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import ToolError

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_GIT_HEADER_RE = re.compile(r"^diff --git (\S+) (\S+)$")

# path prefixes git may emit: a/ b/ by default, c/ i/ w/ o/ with
# diff.mnemonicPrefix, nothing with --no-prefix
_GIT_PREFIXES = ("a/", "b/", "c/", "i/", "w/", "o/")
_PLAIN_PREFIXES = ("a/", "b/")

_ESCAPES = {"n": b"\n", "t": b"\t", '"': b'"', "\\": b"\\"}


def _c_unquote(name: str) -> str:
    """git C-quotes paths with special characters; non-ASCII bytes appear as
    \\ooo octal escapes of the UTF-8 encoding."""
    body = name[1:-1]
    out = bytearray()
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in _ESCAPES:
                out += _ESCAPES[nxt]
                i += 2
                continue
            if nxt.isdigit():
                out.append(int(body[i + 1:i + 4], 8))
                i += 4
                continue
        out += ch.encode("utf-8")
        i += 1
    return out.decode("utf-8", "replace")


@dataclass
class Hunk:
    old_start: int                # 1-based; 0 when the old side is empty
    new_start: int                # 1-based; 0 when the new side is empty
    old_lines: list[str] = field(default_factory=list)   # context + '-'
    new_lines: list[str] = field(default_factory=list)   # context + '+'


@dataclass
class FilePatch:
    old_path: str | None = None   # None = file created (/dev/null)
    new_path: str | None = None   # None = file deleted
    hunks: list[Hunk] = field(default_factory=list)
    binary: bool = False


def _clean_name(name: str, git_section: bool) -> str | None:
    """Strip diff prefixes (a/ b/, or any git mnemonic prefix inside a
    git-style section) and `--- path\\t2024-01-01` timestamps."""
    name = name.split("\t")[0].strip()
    if name.startswith('"') and name.endswith('"') and len(name) >= 2:
        name = _c_unquote(name)
    if name in ("/dev/null", ""):
        return None
    for prefix in _GIT_PREFIXES if git_section else _PLAIN_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def parse_diff(text: str) -> list[FilePatch]:
    patches: list[FilePatch] = []
    cur: FilePatch | None = None
    git_section = False
    saw_minus = False
    hunk: Hunk | None = None
    want_old = want_new = 0

    # split on \n only (diff tools never split on \f or U+2028) and drop a
    # CRLF diff file's carriage returns at the edge
    for raw in text.split("\n"):
        raw = raw.rstrip("\r")
        if hunk is not None and (want_old > 0 or want_new > 0):
            if raw.startswith("\\"):  # "\ No newline at end of file"
                continue
            tag, payload = raw[:1], raw[1:]
            if tag == " " or raw == "":  # some pipelines strip the space off blank context lines
                hunk.old_lines.append(payload)
                hunk.new_lines.append(payload)
                want_old -= 1
                want_new -= 1
            elif tag == "-":
                hunk.old_lines.append(payload)
                want_old -= 1
            elif tag == "+":
                hunk.new_lines.append(payload)
                want_new -= 1
            else:
                raise ToolError(f"malformed diff: unexpected line inside hunk: {raw!r}")
            continue
        hunk = None

        if raw.startswith("diff --git "):
            # path pairs with spaces are ambiguous on this line; the
            # ---/+++/rename lines that follow are authoritative anyway
            m = _GIT_HEADER_RE.match(raw)
            old_name = _clean_name(m.group(1), git_section=True) if m else None
            new_name = _clean_name(m.group(2), git_section=True) if m else None
            cur = FilePatch(old_path=old_name, new_path=new_name)
            patches.append(cur)
            git_section = True
            saw_minus = False
            continue
        if raw.startswith("--- "):
            # in a git diff this refines the current section; in a plain diff
            # it opens a new one
            if cur is None or cur.hunks or saw_minus:
                cur = FilePatch()
                patches.append(cur)
                git_section = False
            cur.old_path = _clean_name(raw[4:], git_section)
            saw_minus = True
            continue
        if raw.startswith("+++ ") and cur is not None:
            cur.new_path = _clean_name(raw[4:], git_section)
            continue
        m = _HUNK_RE.match(raw)
        if m:
            if cur is None:
                raise ToolError(f"malformed diff: hunk header before any file header: {raw!r}")
            old_start, old_count = int(m.group(1)), int(m.group(2) or "1")
            new_start, new_count = int(m.group(3)), int(m.group(4) or "1")
            hunk = Hunk(old_start=old_start, new_start=new_start)
            cur.hunks.append(hunk)
            want_old, want_new = old_count, new_count
            continue
        if cur is not None:
            if raw.startswith("Binary files ") or raw == "GIT binary patch":
                cur.binary = True
            elif raw.startswith("rename from "):
                cur.old_path = raw[len("rename from "):].strip()
            elif raw.startswith("rename to "):
                cur.new_path = raw[len("rename to "):].strip()
        # everything else (index/mode lines, commit headers) is ignored

    if not patches and text.strip():
        raise ToolError("input does not look like a unified diff (no file headers found)")
    return patches


def _eq(a: str, b: str) -> bool:
    return a.rstrip("\r") == b.rstrip("\r")


def reverse_apply(patch: FilePatch, new_lines: list[str], label: str) -> list[str]:
    """Old file lines, reconstructed from the new file plus the patch. Every
    new-side hunk line is verified against the file so a stale diff fails
    loudly instead of judging against a fictional baseline."""
    old: list[str] = []
    pos = 0  # 0-based cursor into new_lines
    for h in patch.hunks:
        # a hunk with an empty new side anchors on the line BEFORE the removal
        idx = h.new_start - 1 if h.new_lines else h.new_start
        if idx < pos or idx > len(new_lines):
            raise ToolError(f"diff does not match {label}: hunk at new-file line {h.new_start} is out of range")
        old.extend(new_lines[pos:idx])
        actual = new_lines[idx: idx + len(h.new_lines)]
        if len(actual) != len(h.new_lines) or not all(_eq(a, b) for a, b in zip(actual, h.new_lines)):
            raise ToolError(
                f"diff does not match {label} at line {idx + 1}: the file changed after the diff was taken"
            )
        old.extend(h.old_lines)
        pos = idx + len(h.new_lines)
    old.extend(new_lines[pos:])
    return old

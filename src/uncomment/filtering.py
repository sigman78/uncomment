"""Input filtering: include/exclude globs, gitignore, generated files.

Filters apply wherever files are picked up implicitly — directory walks,
diff-mode selection, and the gate's baseline tree sweep. A file named
explicitly on the command line always scans: naming it is intent.
"""

from __future__ import annotations

import subprocess
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from .config import Config


def matches_any(rel_posix: str, patterns: list[str]) -> bool:
    """Gitignore-flavored matching. A pattern without '/' matches any single
    path component ('_deps' prunes a _deps directory at any depth); a pattern
    with '/' matches the whole path relative to the scan root ('src/**',
    '**/gen/*.py')."""
    parts = PurePosixPath(rel_posix).parts
    for pattern in patterns:
        pat = pattern.strip("/")
        if "/" not in pat:
            if any(fnmatchcase(part, pat) for part in parts):
                return True
        elif PurePosixPath(rel_posix).full_match(pat):
            return True
    return False


def selected(rel_posix: str, cfg: Config) -> bool:
    """True when include (if any) matches and no exclude matches."""
    if cfg.include and not matches_any(rel_posix, cfg.include):
        return False
    return not matches_any(rel_posix, cfg.exclude)


# strong generated-code signals only: a stray human "do not edit this list"
# in prose must not silently skip a whole file, so the classic marker is
# matched case-sensitively
_GENERATED_UPPER = "DO NOT EDIT"
_GENERATED_ANY_CASE = ("@generated", "automatically generated", "auto-generated file")


def is_generated(path: Path) -> bool:
    """Generated-file heuristic: a marker within the first 2KB."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(2048).decode("utf-8", "replace")
    except OSError:
        return False
    if _GENERATED_UPPER in head:
        return True
    lower = head.lower()
    return any(marker in lower for marker in _GENERATED_ANY_CASE)


# Cache Directory Tagging Specification (bford.info/cachedir): tools like
# cargo, uv, pip, and pytest drop a signed CACHEDIR.TAG into the caches they
# create. The signature check keeps an ordinary file that happens to be named
# CACHEDIR.TAG from hiding a whole tree.
_CACHEDIR_SIG = b"Signature: 8a477f597d28d172789f06886806bc55"


def is_cachedir_tagged(directory: Path) -> bool:
    try:
        with open(directory / "CACHEDIR.TAG", "rb") as fh:
            return fh.read(len(_CACHEDIR_SIG)) == _CACHEDIR_SIG
    except OSError:
        return False


def _inside_git_repo(root: Path) -> bool:
    resolved = root.resolve()
    return any((d / ".git").exists() for d in [resolved, *resolved.parents])


def drop_gitignored(root: Path, files: list[Path]) -> list[Path]:
    """Remove files git ignores, via one `git check-ignore` batch per scanned
    root. Outside a repository, or without git, this is a no-op — filtering
    fails open, never silently emptying a scan."""
    if not files or not _inside_git_repo(root):
        return files
    rels = []
    for f in files:
        try:
            rels.append(f.resolve().relative_to(root.resolve()).as_posix())
        except ValueError:
            rels.append(str(f))
    try:
        out = subprocess.run(
            ["git", "check-ignore", "--stdin", "-z"],
            cwd=root, input="\0".join(rels) + "\0", capture_output=True, text=True,
        )
    except (FileNotFoundError, OSError):
        return files
    if out.returncode not in (0, 1):  # 128: not a repository / hard error
        return files
    ignored = set(out.stdout.split("\0"))
    return [f for f, rel in zip(files, rels) if rel not in ignored]

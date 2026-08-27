"""Linter/compiler/tooling control comments.

These are functional, not prose: suppressions, build constraints, coverage
markers, pragmas. They are never judged by any rule, never suggested for
removal, and do not count toward gate statistics. Extra project-specific
patterns can be added via the `directive-patterns` config key.
"""

from __future__ import annotations

import re

from .model import Kind

_COMMON = [
    r"^#\s*(region|endregion)\b",                # IDE folding markers
    r"^(LCOV|GCOV|GCOVR)_EXCL_\w+",              # coverage exclusions
    r"^coverage:(ignore|off|on)(-line|-start|-end|-file)?\b",   # dart-style, no free prose
    r"^NOSONAR\b",
    r"(?i)^falls?[ -]?thr(ough|u)\.?$",          # compiler fallthrough hint
]

_C_FAMILY = [
    # clang-tidy: bare, or with a (category); "NOLINT: <prose>" is not a real
    # form and stays judged so narration cannot hide behind it
    r"^NOLINT(NEXTLINE|BEGIN|END)?(?!\s*:)\b",
    r"^clang-format\s+(on|off)\b",
    r"^cppcheck-suppress\b",
    r"^IWYU pragma:",
    r"^coverity\[",
    r"^PRQA\b",
]

_JS_FAMILY = [
    r"^@ts-(ignore|expect-error|nocheck|check)\b",
    r"^eslint\b",                                # /* eslint rule: "off" */, eslint-env
    r"^eslint-",                                 # eslint-disable(-next-line|-line), eslint-enable
    r"^prettier-ignore\b",
    r"^(biome|rome)-ignore\b",
    r"^deno-lint-ignore\b",
    r"^@?vite-ignore\b",
    r"^webpack[A-Z]\w*:",                        # /* webpackChunkName: "..." */
    r"^[@#]__PURE__$",
    r"^#\s*source(MappingURL|URL)=",
    r"^(istanbul|c8|v8)\s+ignore\b",
    r"^@(jest|vitest)-environment\b",
    r"^@jsx\b",
    r"^@flow\b",
    r"^\$Flow\w*",
    r"^@(license|preserve)\b",                   # minifier preserve pragmas
    r"^@type\s",                                 # /** @type {Foo} */ casts
    r"^@satisfies\s",
]

# only meaningful as block comments; guarded separately so prose line comments
# starting with "global ..." are not exempted
_JS_BLOCK_ONLY = [
    r"^globals?\s+[A-Za-z_$][\w$.]*([\s,:].*)?$",   # /* global foo */
    r"^exported\s+[A-Za-z_$][\w$]*\s*$",            # /* exported foo */
]

_GO = [
    r"^go:[a-z]",                                # go:build, go:generate, go:embed, go:linkname, …
    r"^\+build\b",                               # legacy build constraint
    r"^nolint\b",                                # golangci-lint
    r"^lint:(ignore|file-ignore)\b",             # staticcheck
    r"^#cgo\b",
    r"^export\s+\w+$",                           # cgo //export
]

_RUST = [
    r"^rustfmt::skip\b",
    r"^@\s",                                     # compiletest: //@ check-pass
]

# patterns see content AFTER the single leading '#' is stripped, so a shebang
# arrives as "!/usr/bin/env python" and "# noqa" as "noqa"
_PYTHON = [
    r"^!\s*/",                                   # shebang
    r"^-\*-.*-\*-\s*$",                          # emacs file variables (incl. coding)
    r"^(en)?coding[:=]\s*[-\w.]+\s*$",           # PEP 263 encoding declaration
    r"^vim?:\s?",                                # vim/vi modeline
    r"^noqa\b",                                  # flake8/ruff suppression
    r"^type:\s",                                 # PEP 484 type comments incl. type: ignore
    r"^mypy:\s",
    r"^pylint:\s*(disable|enable|skip-file)",
    r"^ruff:\s*(noqa|isort)",
    r"^flake8:\s*noqa",
    r"^fmt:\s*(off|on|skip)\b",                  # black
    r"^isort:\s*(skip|skip_file|off|on|split|dont[- ]add[- ]imports)",
    r"^yapf:\s*(disable|enable)",
    r"^pragma:\s*\S",                            # coverage.py: pragma: no cover
    r"^nosec\b",                                 # bandit
    r"^noinspection\s",                          # PyCharm
    r"^cython:\s",
    r"^(end)?region\b(\s+[\w-]+)?$",             # editor folding, marker already stripped
]

_BY_LANG: dict[str, list[str]] = {
    "c": _C_FAMILY,
    "cpp": _C_FAMILY,
    "javascript": _JS_FAMILY,
    "typescript": _JS_FAMILY,
    "tsx": _JS_FAMILY,
    "go": _GO,
    "rust": _RUST,
    "python": _PYTHON,
}

_COMPILED: dict[str, list[re.Pattern]] = {}
_COMPILED_BLOCK: dict[str, list[re.Pattern]] = {}


def _patterns(lang: str) -> list[re.Pattern]:
    if lang not in _COMPILED:
        _COMPILED[lang] = [re.compile(p) for p in _COMMON + _BY_LANG.get(lang, [])]
    return _COMPILED[lang]


def _block_patterns(lang: str) -> list[re.Pattern]:
    if lang not in _COMPILED_BLOCK:
        extra = _JS_BLOCK_ONLY if lang in ("javascript", "typescript", "tsx") else []
        _COMPILED_BLOCK[lang] = [re.compile(p) for p in extra]
    return _COMPILED_BLOCK[lang]


def is_directive_text(first_line: str, lang: str, kind: Kind | None = None) -> bool:
    """True if a comment's first content line is a tooling directive."""
    line = first_line.strip()
    if not line:
        return False
    if any(rx.search(line) for rx in _patterns(lang)):
        return True
    if kind is not Kind.LINE and any(rx.search(line) for rx in _block_patterns(lang)):
        return True
    return False


_CGO_IMPORT_RE = re.compile(r"^import\s+\"C\"")


def is_cgo_preamble(lang: str, attached_code: str) -> bool:
    """A Go comment directly above `import "C"` is the cgo preamble: it is C
    code by design and must never be treated as commented-out code."""
    return lang == "go" and bool(_CGO_IMPORT_RE.match(attached_code.strip()))

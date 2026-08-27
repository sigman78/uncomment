"""Core data types shared by extraction, rules, and reporting."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class ToolError(Exception):
    """User-facing failure: bad input path, baseline, config, or environment.
    The CLI reports these as `uncomment: error: ...` with exit code 2."""


class Kind(enum.Enum):
    LINE = "line"
    BLOCK = "block"
    DOC = "doc"


class Attachment(enum.Enum):
    FILE_HEADER = "file_header"   # before the first code in the file
    PRECEDING = "preceding"       # own-line comment directly above code
    TRAILING = "trailing"         # on the same line, after code
    FLOATING = "floating"         # own-line comment followed by a blank line / EOF


class Severity(enum.IntEnum):
    INFO = 0
    WARN = 1
    ERROR = 2

    @classmethod
    def parse(cls, name: str) -> "Severity":
        return cls[name.upper()]


@dataclass
class Comment:
    """One logical comment: a block comment, a doc comment, or a run of
    adjacent single-line comments merged into one unit."""

    path: str
    lang: str
    kind: Kind
    attachment: Attachment
    text: str                 # raw text including comment markers
    content: str              # marker-stripped text, one string, \n-joined
    start_line: int           # 1-based, inclusive
    end_line: int             # 1-based, inclusive
    col: int                  # 0-based column of the first marker
    attached_code: str = ""   # code on the same line (trailing) or first line below (preceding)
    in_function: bool = False
    function_name: str = ""
    is_directive: bool = False  # linter/compiler control comment; never judged

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1

    @property
    def word_count(self) -> int:
        return len(self.content.split())


@dataclass
class FunctionInfo:
    """A function/method span, used for per-function density rules."""

    path: str
    name: str
    start_line: int
    end_line: int
    body_line_count: int


@dataclass
class SourceFile:
    path: str
    lang: str
    lines: list[str]
    comments: list[Comment] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    code_line_count: int = 0      # lines with code on them (comment-only lines excluded)
    comment_line_count: int = 0   # lines occupied by comments


@dataclass
class Finding:
    rule: str
    severity: Severity
    path: str
    line: int                 # 1-based anchor line
    end_line: int
    message: str              # what is wrong
    action: str               # what the agent/author should do about it
    excerpt: str = ""         # short quote of the offending text

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "severity": self.severity.name.lower(),
            "path": self.path,
            "line": self.line,
            "end_line": self.end_line,
            "message": self.message,
            "action": self.action,
            "excerpt": self.excerpt,
        }

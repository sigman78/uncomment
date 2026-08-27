"""Core rules: agent comment noise — narration, restating code, banners,
commented-out code, density, redundant docs, doc-migration hints."""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..config import Config
from ..model import Attachment, Comment, Finding, Kind, Severity, SourceFile
from ..textutil import first_line, overlap_ratio
from . import is_license_header, rule


def _finding(rule_id: str, severity: Severity, c: Comment, message: str, action: str) -> Finding:
    return Finding(
        rule=rule_id,
        severity=severity,
        path=c.path,
        line=c.start_line,
        end_line=c.end_line,
        message=message,
        action=action,
        excerpt=first_line(c.content),
    )


_WHY_RE = re.compile(
    r"\b(because|why|workaround|otherwise|avoid|caveat|warning|careful|invariant|must not|do not|don't|note:|nb:|safety|so that)\b|https?://",
    re.IGNORECASE,
)
_TODO_RE = re.compile(r"\b(todo|fixme|hack|xxx)\b", re.IGNORECASE)


@rule(
    "UC001",
    "restates-code",
    Severity.WARN,
    "Comment says the same thing as the adjacent code.",
)
def restates_code(sf: SourceFile, cfg: Config) -> Iterable[Finding]:
    for c in sf.comments:
        if c.kind is Kind.DOC or c.attachment not in (Attachment.PRECEDING, Attachment.TRAILING):
            continue
        if c.line_count > 2 or c.word_count < 2 or not c.attached_code:
            continue
        if _WHY_RE.search(c.content) or _TODO_RE.search(c.content):
            continue
        ratio = overlap_ratio(c.content, c.attached_code)
        if ratio >= cfg.restate_overlap:
            yield _finding(
                "UC001",
                Severity.WARN,
                c,
                f"comment repeats the adjacent code ({ratio:.0%} of its words appear in the code)",
                "Delete this comment. The code already says this.",
            )


_NARRATION_START_RE = re.compile(
    r"^(now,? we |now that we |first,|first we |then |next,? we |finally,? we |finally, |lastly[,: ]"
    r"|we |let'?s |here,? we |i |start by |begin by |the following |below,? we |step \d)",
    re.IGNORECASE,
)
_STEP_NUMBER_RE = re.compile(r"^\d+[.)]\s+\w")


@rule(
    "UC002",
    "narration",
    Severity.WARN,
    "Comment narrates the coding process (step-by-step storytelling) instead of describing intent.",
)
def narration(sf: SourceFile, cfg: Config) -> Iterable[Finding]:
    for c in sf.comments:
        # doc comments conventionally start with the symbol name ("Now returns
        # the current time…"), which collides with narration openers — skip them
        if c.kind is Kind.DOC or is_license_header(c):
            continue
        head = c.content.splitlines()[0] if c.content else ""
        if _NARRATION_START_RE.match(head) or (c.in_function and _STEP_NUMBER_RE.match(head)):
            yield _finding(
                "UC002",
                Severity.WARN,
                c,
                "comment narrates the process ('now/first/we/step N…') instead of stating intent",
                "Delete it, or rewrite as a short statement of WHY the code does this. Do not tell a story.",
            )


# past-tense openers narrate an edit; present tense ("Adds a newline…") is a
# normal behavior description, so it stays out. The lookahead spares runtime
# descriptions ("Removed from the queue when done") and adjective uses
# ("Fixed size buffer").
_CHANGE_START_RE = re.compile(
    r"^(?:added|updated|changed|modified|fixed|removed|renamed|refactored|replaced|moved|switched"
    r"|migrated|improved|enhanced|optimized|rewrote)\b"
    r"(?!\s+(?:from|by|in|on|at|out|off|up|when|while|after|before|during|once|if|unless"
    r"|point|size|width|length|number|amount|rate|capacity|cost)\b)"
    r"|^(?:new|change|edit|fix):",
    re.IGNORECASE,
)
_CHANGE_INNER_RE = re.compile(
    r"\b(as requested|as per (the )?(instructions?|request)|per (the )?(user|reviewer|feedback)"
    r"|this (change|edit|update|commit|patch)|the (old|previous|original) (implementation|version|code|logic)"
    r"|no longer (needed|used|necessary)|instead of the (old|previous)|was (removed|changed|renamed|moved) (in|to|from))\b",
    re.IGNORECASE,
)


@rule(
    "UC003",
    "change-narration",
    Severity.ERROR,
    "Comment describes the edit that was made, not the code that exists. Version control holds history.",
)
def change_narration(sf: SourceFile, cfg: Config) -> Iterable[Finding]:
    for c in sf.comments:
        if is_license_header(c):
            continue
        head = c.content.splitlines()[0] if c.content else ""
        if _CHANGE_START_RE.match(head) or _CHANGE_INNER_RE.search(c.content):
            yield _finding(
                "UC003",
                Severity.ERROR,
                c,
                "comment describes the edit, not the code ('added/changed/as requested…')",
                "Delete this comment. Edit history belongs in the commit message, not in the source.",
            )


_BANNER_CHARS_RE = re.compile(r"[-=*~_#/]{8,}")


@rule(
    "UC004",
    "banner",
    Severity.WARN,
    "Decorative divider / section banner comment.",
)
def banner(sf: SourceFile, cfg: Config) -> Iterable[Finding]:
    for c in sf.comments:
        if is_license_header(c):
            continue
        for line in c.content.splitlines():
            if _BANNER_CHARS_RE.search(line) and len(line.split()) <= 5:
                yield _finding(
                    "UC004",
                    Severity.WARN,
                    c,
                    "decorative banner/divider comment",
                    "Delete the banner. If the file needs sections, split it into smaller files or functions.",
                )
                break


_CODEISH_RES = [
    re.compile(r"[;{}]\s*$"),
    re.compile(r"^\s*[{}]\s*$"),
    re.compile(r"^\s*(if|for|while|switch|return|import|export|let|const|var|fn|func|def|pub|static|struct|class|case|else|try|catch)\b.*[;{()=:]"),
    re.compile(r"^\s*#\s*(include|define|if|ifdef|ifndef|endif|pragma)\b"),
    re.compile(r"^\s*[\w.\[\]:>*&-]+\s*\([^)]*\)\s*;?\s*$"),
    re.compile(r"^\s*[\w.\[\]]+\s*[-+*/|&^:]?=\s*[^=]"),
    re.compile(r"=>|->\s*\w|\)\s*{"),
    # bare one-operand statements: 'return result', 'break', 'continue'
    re.compile(r"^\s*return\s+[\w.\[\]()\"']+\s*;?\s*$"),
    re.compile(r"^\s*(break|continue)\s*;?\s*$"),
]


def _looks_like_code(line: str) -> bool:
    if not line.strip():
        return False
    return any(rx.search(line) for rx in _CODEISH_RES)


@rule(
    "UC005",
    "commented-out-code",
    Severity.WARN,
    "Comment contains disabled code.",
)
def commented_out_code(sf: SourceFile, cfg: Config) -> Iterable[Finding]:
    for c in sf.comments:
        if c.kind is Kind.DOC:
            continue
        lines = [ln for ln in c.content.splitlines() if ln.strip()]
        if not lines:
            continue
        codeish = sum(1 for ln in lines if _looks_like_code(ln))
        if (len(lines) >= 2 and codeish / len(lines) >= cfg.code_line_fraction and codeish >= 2) or (
            len(lines) == 1 and _looks_like_code(lines[0]) and not _TODO_RE.search(lines[0])
        ):
            yield _finding(
                "UC005",
                Severity.WARN,
                c,
                f"commented-out code ({codeish} of {len(lines)} lines look like code)",
                "Delete it. Version control preserves removed code; dead code in comments rots.",
            )


@rule(
    "UC006",
    "function-comment-density",
    Severity.WARN,
    "Function body is saturated with comments.",
)
def function_density(sf: SourceFile, cfg: Config) -> Iterable[Finding]:
    for fn in sf.functions:
        interior = [
            c
            for c in sf.comments
            if c.in_function and fn.start_line < c.start_line <= fn.end_line
        ]
        # attribute each comment to its innermost function only
        interior = [
            c
            for c in interior
            if not any(
                other is not fn and other.start_line >= fn.start_line and other.end_line <= fn.end_line
                and other.start_line < c.start_line <= other.end_line
                for other in sf.functions
            )
        ]
        comment_lines = sum(c.line_count for c in interior)
        if (
            comment_lines >= cfg.min_interior_comment_lines
            and fn.body_line_count > 0
            and comment_lines / fn.body_line_count > cfg.max_function_comment_ratio
        ):
            yield Finding(
                rule="UC006",
                severity=Severity.WARN,
                path=sf.path,
                line=fn.start_line,
                end_line=fn.end_line,
                message=(
                    f"function '{fn.name}' has {comment_lines} comment lines in a "
                    f"{fn.body_line_count}-line body ({comment_lines / fn.body_line_count:.0%})"
                ),
                action=(
                    "Strip the play-by-play comments from this function. Keep at most a short WHY note "
                    "per non-obvious block; if the logic needs this much explanation, simplify or split it."
                ),
                excerpt=fn.name,
            )


_DOC_TAG_RE = re.compile(r"(@param|@returns?|@throws|@arg|Args:|Returns:|Raises:|# Arguments|# Errors|# Panics|# Safety)", re.IGNORECASE)


@rule(
    "UC007",
    "redundant-doc",
    Severity.WARN,
    "Doc comment adds nothing beyond the symbol name.",
)
def redundant_doc(sf: SourceFile, cfg: Config) -> Iterable[Finding]:
    for c in sf.comments:
        if c.kind is not Kind.DOC or c.attachment is not Attachment.PRECEDING or not c.attached_code:
            continue
        if c.line_count > 3 or _DOC_TAG_RE.search(c.content):
            continue
        ratio = overlap_ratio(c.content, c.attached_code)
        if ratio >= cfg.redundant_doc_overlap and c.word_count >= 2:
            yield _finding(
                "UC007",
                Severity.WARN,
                c,
                f"doc comment restates the symbol name ({ratio:.0%} word overlap)",
                "Delete it, or make it say something the signature cannot: units, invariants, error behavior, ownership.",
            )


_SECTION_RE = re.compile(
    r"^#+\s|\b(example|usage|architecture|overview|background|design|rationale|how it works|implementation notes?|history|tutorial)\b\s*:?",
    re.IGNORECASE | re.MULTILINE,
)


@rule(
    "UC008",
    "doc-migration",
    Severity.INFO,
    "Comment is real documentation living in the wrong place; suggest moving it to docs.",
)
def doc_migration(sf: SourceFile, cfg: Config) -> Iterable[Finding]:
    for c in sf.comments:
        if is_license_header(c):
            continue
        if c.in_function and c.line_count >= 6:
            yield _finding(
                "UC008",
                Severity.INFO,
                c,
                f"{c.line_count}-line essay inside function '{c.function_name}'",
                "Move this to the function's doc comment or to project docs; keep at most one WHY line here.",
            )
            continue
        if c.line_count < cfg.doc_migration_lines:
            continue
        if c.attachment is Attachment.FILE_HEADER and c.kind is Kind.DOC:
            # module/package docs (Go doc.go, Rust //!) are a legitimate home
            # for long documentation — that IS the docs
            continue
        if c.attachment is Attachment.FILE_HEADER:
            yield _finding(
                "UC008",
                Severity.INFO,
                c,
                f"{c.line_count}-line file header essay",
                "Move guide-level content to README/docs or the module doc; keep a one-paragraph summary here.",
            )
        elif c.kind is Kind.DOC:
            if _SECTION_RE.search(c.content) or c.line_count >= 2 * cfg.doc_migration_lines:
                yield _finding(
                    "UC008",
                    Severity.INFO,
                    c,
                    f"{c.line_count}-line doc comment with guide-level sections",
                    "Keep the API summary and parameter docs here; move tutorial/architecture prose to project docs.",
                )
        else:
            yield _finding(
                "UC008",
                Severity.INFO,
                c,
                f"{c.line_count}-line comment block",
                "If this documents the API, make it a doc comment; if it is guide-level prose, move it to project docs.",
            )


@rule(
    "UC009",
    "trailing-comment-length",
    Severity.WARN,
    "Inline (trailing) comment too long to sit on the code line.",
)
def trailing_length(sf: SourceFile, cfg: Config) -> Iterable[Finding]:
    for c in sf.comments:
        if c.attachment is not Attachment.TRAILING:
            continue
        if len(c.text) > cfg.max_trailing_chars or c.word_count > 10:
            yield _finding(
                "UC009",
                Severity.WARN,
                c,
                f"trailing comment is {len(c.text)} chars / {c.word_count} words",
                "Delete it if it repeats the code; otherwise move it to its own line above, shortened.",
            )


_BOILERPLATE_RE = re.compile(
    r"^(imports?|includes?|variables?|globals?|constants?|fields?|members?|types?|"
    r"(private|public|protected|static)\s+(methods?|members?|fields?|functions?)|"
    r"helpers?|helper functions?|utility functions?|utils?|main( function| entry point)?|"
    r"constructors?|destructors?|getters?( and setters?)?|setters?|accessors?|"
    r"initialization|init|cleanup|setup|teardown|declarations?|definitions?|implementation|"
    r"entry point|event handlers?|callbacks?|properties|state|misc(ellaneous)?|other|"
    r"end of .{0,40}|done)[.:]?$",
    re.IGNORECASE,
)


@rule(
    "UC010",
    "boilerplate-label",
    Severity.WARN,
    "Label comment that names the obvious ('// imports', '// helper functions', '// end of loop').",
)
def boilerplate_label(sf: SourceFile, cfg: Config) -> Iterable[Finding]:
    for c in sf.comments:
        if c.kind is Kind.DOC or c.line_count > 1:
            continue
        if _BOILERPLATE_RE.match(c.content.strip()):
            yield _finding(
                "UC010",
                Severity.WARN,
                c,
                "label comment states the obvious",
                "Delete it. Readers can see what imports/helpers/loops are; structure should come from code, not labels.",
            )


_TODO_REF_RE = re.compile(r"\(\s*\w+\s*\)|#\d+|\b[A-Z][A-Z0-9]+-\d+\b|https?://")

# emoji, pictographs, dingbats, decorative symbols — not general typography
# (arrows, accented letters, CJK prose stay allowed unless ascii_comments)
_EMOJI_RANGES = [
    (0x2600, 0x27BF),    # misc symbols + dingbats
    (0x2B00, 0x2BFF),    # misc symbols and arrows
    (0xFE0F, 0xFE0F),    # variation selector 16
    (0x200D, 0x200D),    # zero-width joiner (emoji sequences)
    (0x1F000, 0x1FAFF),  # emoticons, pictographs, transport, supplemental
    (0x1FB00, 0x1FBFF),  # symbols for legacy computing
]
_EMOJI_RE = re.compile("[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in _EMOJI_RANGES) + "]")
_NON_ASCII_RE = re.compile(r"[^\x00-\x7f]")


@rule(
    "UC011",
    "unowned-todo",
    Severity.INFO,
    "TODO/FIXME without an owner or ticket reference.",
)
def unowned_todo(sf: SourceFile, cfg: Config) -> Iterable[Finding]:
    for c in sf.comments:
        m = _TODO_RE.search(c.content)
        if m and not _TODO_REF_RE.search(c.content):
            yield _finding(
                "UC011",
                Severity.INFO,
                c,
                f"{m.group(0).upper()} has no owner or ticket",
                "Add an owner or issue reference (TODO(name), #123), file a ticket, or remove it.",
            )


@rule(
    "UC012",
    "emoji-comment",
    Severity.WARN,
    "Emoji/decorative symbols in comments; any non-ASCII when ascii-comments is set.",
)
def emoji_comment(sf: SourceFile, cfg: Config) -> Iterable[Finding]:
    rx = _NON_ASCII_RE if cfg.ascii_comments else _EMOJI_RE
    what = "non-ASCII characters" if cfg.ascii_comments else "emoji/decorative symbols"
    for c in sf.comments:
        if is_license_header(c):
            continue
        found = rx.findall(c.content)
        if found:
            unique = "".join(dict.fromkeys(ch for ch in found if ch.isprintable()))[:8]
            shown = unique or " ".join(f"U+{ord(ch):04X}" for ch in dict.fromkeys(found))[:40]
            yield _finding(
                "UC012",
                Severity.WARN,
                c,
                f"comment contains {what}: {shown}",
                "Remove the decoration. Comments read best as plain text; symbols add no information.",
            )

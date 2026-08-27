"""Core rules: agent comment noise — narration, restating code, banners,
commented-out code, density, redundant docs, doc-migration hints."""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..config import Config
from ..languages import is_interface_file
from ..model import Attachment, Comment, Finding, Kind, Severity, SourceFile
from ..textutil import first_line, overlap_ratio
from . import is_license_header, rule, wording_text


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
        if c.line_count > 4 or c.word_count < 2 or not c.attached_code:
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


# narration "let's" always precedes a lowercase verb ("let's iterate"); a
# capitalized word after it is a product name ("Let's Encrypt"), not a story
_NARRATION_START_RE = re.compile(
    r"^(now,? we |now that we |first,|first we |then |next,? we |finally,? we |finally, |lastly[,: ]"
    r"|we |let'?s (?=(?-i:[a-z]))|here,? we |i |start by |begin by |the following |below,? we |step \d)",
    re.IGNORECASE,
)
_STEP_NUMBER_RE = re.compile(r"^\d+[.)]\s+\w")
# for lines after the first, only unambiguous narration counts — a wrapped
# sentence may legitimately continue onto a line starting with "we"
_NARRATION_CONT_RE = re.compile(r"^(now,? we |first,? we |then we |next,? we |finally,? we |step \d)", re.IGNORECASE)


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
        text = wording_text(c.content, cfg)
        # a WHY comment that happens to open with "We cannot… because…" is the
        # kind of comment this tool asks for — leave it alone
        if _WHY_RE.search(text):
            continue
        head, *rest = text.splitlines() or [""]
        if (
            _NARRATION_START_RE.match(head)
            or (c.in_function and _STEP_NUMBER_RE.match(head))
            or any(_NARRATION_CONT_RE.match(line) or (c.in_function and _STEP_NUMBER_RE.match(line)) for line in rest)
        ):
            yield _finding(
                "UC002",
                Severity.WARN,
                c,
                "comment narrates the process ('now/first/we/step N…') instead of stating intent",
                "Delete it, or rewrite as a short statement of WHY the code does this. Do not tell a story.",
            )


# uncomment-ignore[UC003]: this comment must quote the phrases the rule detects
# UC003 works in two evidence tiers:
#  - explicit edit context ("as requested", "the previous version") -> ERROR
#  - a past-tense opener alone -> WARN; present tense ("Adds a newline…") is a
#    normal behavior description and stays out. The lookahead spares runtime
#    descriptions ("Removed from the queue", "Moved to the free list") and
#    adjective uses ("Fixed-point", "Fixed size buffer").
_CHANGE_START_RE = re.compile(
    r"^(?:added|updated|changed|modified|fixed|removed|renamed|refactored|replaced|moved"
    r"|migrated|improved|enhanced|optimized|rewrote|corrected|simplified|reworked|adjusted"
    r"|introduced|dropped|cleaned(?:\s+up)?)\b"
    r"(?![\s-]+(?:from|by|in|on|at|out|off|up|when|while|after|before|during|once|if|unless"
    r"|point|size|width|length|number|amount|rate|capacity|cost|header|timestamp|to\s+(?:the|a|an))\b)"
    # transition verbs are edit narration regardless of preposition
    r"|^(?:switched|reverted|ported)\b"
    r"|^(?:now|this now)\s+(?:uses|calls|returns|relies|handles|supports|avoids|reads|writes|skips)\b"
    r"|^(?:new|change|edit|fix):",
    re.IGNORECASE,
)
_CHANGE_INNER_RE = re.compile(
    r"\b(as requested|as discussed|as per (the )?(instructions?|request)"
    r"|per (the )?(user|reviewer|review|feedback)|in response to (the )?(review|feedback|request)"
    r"|this (change|edit|update|commit|patch)|the (old|previous|original) (implementation|version|code|logic)"
    # "no longer needed/necessary" is ownership/lifetime prose ("free the map
    # when it's no longer needed") — only behavioral change forms count
    r"|no longer (uses|calls|requires|relies)"
    r"|instead of the (old|previous)|was (removed|changed|renamed|moved) (in|to|from))\b",
    re.IGNORECASE,
)


@rule(
    "UC003",
    "change-narration",
    Severity.ERROR,
    "Comment describes the edit that was made, not the code that exists. "
    "Explicit edit context is an error; a past-tense opener alone is a warning.",
)
def change_narration(sf: SourceFile, cfg: Config) -> Iterable[Finding]:
    for c in sf.comments:
        if is_license_header(c):
            continue
        text = wording_text(c.content, cfg)
        head = text.splitlines()[0] if text else ""
        if _CHANGE_INNER_RE.search(text):
            yield _finding(
                "UC003",
                Severity.ERROR,
                c,
                "comment describes the edit, not the code ('as requested', 'the previous version'…)",
                "Delete this comment. Edit history belongs in the commit message, not in the source.",
            )
        # doc comments open with the symbol name by convention ("Now returns
        # the current time…" for a func named Now) — opener tier skips them
        elif c.kind is not Kind.DOC and _CHANGE_START_RE.match(head):
            yield _finding(
                "UC003",
                Severity.WARN,
                c,
                "comment starts like edit narration ('changed/simplified/now uses…')",
                "If this describes the edit, delete it; history belongs in the commit message. "
                "If it describes current behavior, reword in present tense ('Uses X because…').",
            )


_BANNER_CHARS_RE = re.compile(r"[-=*~_#/]{8,}")
_BOX_BORDER_RE = re.compile(r"^[+|][-+=| ]{6,}[+|]$")


def _is_diagram(content: str) -> bool:
    """ASCII tables and box diagrams share characters with banners but carry
    real information — keep them."""
    for line in content.splitlines():
        stripped = line.strip()
        if _BOX_BORDER_RE.match(stripped) or stripped.count("|") >= 2:
            return True
    return False


@rule(
    "UC004",
    "banner",
    Severity.WARN,
    "Decorative divider / section banner comment (ASCII tables and diagrams are kept).",
)
def banner(sf: SourceFile, cfg: Config) -> Iterable[Finding]:
    for c in sf.comments:
        if is_license_header(c) or _is_diagram(c.content):
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
    re.compile(r"^\s*(if|elif|for|while|switch|return|import|export|let|const|var|fn|func|def|pub|static|struct|class|case|else|try|catch|except|finally|with|raise|yield|assert)\b.*[;{()=:]"),
    re.compile(r"^\s*#\s*(include|define|if|ifdef|ifndef|endif|pragma)\b"),
    re.compile(r"^\s*[\w.\[\]:>*&-]+\s*\(.*\)\s*;?\s*$"),  # calls, incl. chained
    re.compile(r"^\s*[\w.\[\]]+\s*[-+*/|&^:]?=\s*[^=]"),
    # attached arrows are member access (p->next); a SPACED arrow is mapping
    # prose ("HID events -> ui_key_t") and must not read as code on its own
    re.compile(r"\w->\w|\)\s*{"),
    # bare one-operand statements: 'return result', 'break', 'continue'
    re.compile(r"^\s*return\s+[\w.\[\]()\"']+\s*;?\s*$"),
    re.compile(r"^\s*(break|continue|pass)\s*;?\s*$"),
    # whole-line import statements and decorators (Python); anchored so prose
    # like 'import the settings from the file' stays prose
    re.compile(r"^\s*(import\s+[\w.]+(\s+as\s+\w+)?|from\s+[\w.]+\s+import\s+[\w.*,() ]+)\s*$"),
    re.compile(r"^\s*@\w[\w.]*(\(.*\))?\s*$"),
]


# "lo = first index that might match;" is a prose invariant sketch, not code:
# an assignment whose right side is three or more plain words
_PROSE_ASSIGN_RE = re.compile(r"^\s*\w+\s*=\s*[A-Za-z]+(\s+[A-Za-z]+){2,}\s*[.;]?\s*$")


def _looks_like_code(line: str) -> bool:
    if not line.strip():
        return False
    if _PROSE_ASSIGN_RE.match(line):
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
        # a one-line formula that mirrors the adjacent code ("// x = r * cos(t)"
        # above "return r * cos(t);") is a restatement — UC001's finding, not
        # dead code
        single_restates = (
            len(lines) == 1
            and c.attached_code
            and overlap_ratio(c.content, c.attached_code) >= cfg.restate_overlap
        )
        if (len(lines) >= 2 and codeish / len(lines) >= cfg.code_line_fraction and codeish >= 2) or (
            len(lines) == 1
            and _looks_like_code(lines[0])
            and not _TODO_RE.search(lines[0])
            and not single_restates
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
    if not sf.functions:
        return
    # attribute each interior comment to its innermost enclosing function once
    comment_lines_of: dict[int, int] = {}
    spans = [(fn.start_line, fn.end_line, fn.end_line - fn.start_line) for fn in sf.functions]
    for c in sf.comments:
        if not c.in_function:
            continue
        best = None
        best_size = None
        for idx, (start, end, size) in enumerate(spans):
            if start < c.start_line <= end and (best_size is None or size < best_size):
                best, best_size = idx, size
        if best is not None:
            comment_lines_of[best] = comment_lines_of.get(best, 0) + c.line_count

    for idx, fn in enumerate(sf.functions):
        comment_lines = comment_lines_of.get(idx, 0)
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
            )


# structured API-doc markers: JSDoc/Doxygen tags (@ or backslash form) and
# rustdoc's conventional sections. A doc with these is documentation doing its
# job, not guide prose that wandered into the code.
_DOC_TAG_RE = re.compile(
    r"[@\\](t?param|returns?|retval|throws?|arg|brief|details|note|warning|see|sa|since"
    r"|ingroup|defgroup|addtogroup|copydoc|deprecated|exception|pre|post|file|invariant)\b"
    r"|Args:|Returns:|Raises:|# Arguments|# Errors|# Panics|# Safety|# Examples",
    re.IGNORECASE,
)


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
            # interface files (.h, .d.ts) exist to carry API docs — never
            # suggest moving documentation out of them
            if is_interface_file(sf.path):
                continue
            # a structured doc (Doxygen/JSDoc tags, rustdoc sections) is
            # documentation in its right place unless it grows into a book
            if _DOC_TAG_RE.search(c.content) and c.line_count < 2 * cfg.doc_migration_lines:
                continue
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
        over = []
        if len(c.text) > cfg.max_trailing_chars:
            over.append(f"{len(c.text)} chars (limit {cfg.max_trailing_chars})")
        if c.word_count > cfg.max_trailing_words:
            over.append(f"{c.word_count} words (limit {cfg.max_trailing_words})")
        if over:
            yield _finding(
                "UC009",
                Severity.WARN,
                c,
                "trailing comment is too long: " + ", ".join(over),
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

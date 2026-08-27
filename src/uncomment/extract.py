"""Tree-sitter based comment extraction.

Produces a SourceFile with logical comments (adjacent line comments merged),
each classified by kind (line/block/doc) and attachment (file header,
preceding code, trailing code, or floating).
"""

from __future__ import annotations

import re
from pathlib import Path

from tree_sitter_language_pack import get_parser

from .directives import is_cgo_preamble, is_directive_text
from .languages import COMMENT_NODE_TYPES, LangSpec, spec_for_path
from .model import Attachment, Comment, FunctionInfo, Kind, SourceFile

_NAME_NODE_TYPES = frozenset(
    {"identifier", "field_identifier", "type_identifier", "property_identifier", "destructor_name", "operator_name"}
)

# a header comment directly above one of these lines documents the file, not the line
_IMPORT_LINE_RE = re.compile(
    r"^\s*(#\s*(include|pragma|ifndef|define)\b|import\b|package\b|using\b|use\b|extern crate\b|mod\b|module\b|['\"]use strict)"
)


def _function_name(node) -> str:
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return name_node.text.decode("utf-8", "replace")
    declarator = node.child_by_field_name("declarator")
    if declarator is not None:
        stack = [declarator]
        while stack:
            n = stack.pop(0)
            if n.type in _NAME_NODE_TYPES:
                return n.text.decode("utf-8", "replace")
            stack = list(n.children) + stack
    return "<anonymous>"


def strip_markers(raw: str) -> str:
    """Remove comment markers, keeping the human text."""
    out: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        for prefix in ("/*!", "/**", "/*", "//!", "///", "//"):
            if s.startswith(prefix):
                s = s[len(prefix):]
                break
        else:
            if s.startswith("*") and not s.startswith("*/"):
                s = s[1:]
        if s.endswith("*/"):
            s = s[:-2]
        out.append(s.strip())
    # drop leading/trailing empty lines produced by /* and */ on their own lines
    while out and not out[0]:
        out.pop(0)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


class _RawComment:
    __slots__ = ("text", "start_row", "start_col", "end_row", "end_col", "func_name", "in_function")

    def __init__(self, node, func_name: str, in_function: bool):
        self.text = node.text.decode("utf-8", "replace").rstrip("\r\n")
        self.start_row = node.start_point[0]
        self.start_col = node.start_point[1]
        self.end_row = node.end_point[0]
        self.end_col = node.end_point[1]
        # some grammars (rust doc comments) include the trailing newline
        if self.end_col == 0 and self.end_row > self.start_row:
            self.end_row -= 1
            self.end_col = 1 << 30
        self.func_name = func_name
        self.in_function = in_function


def extract_source(path: str, source: str, spec: LangSpec) -> SourceFile:
    parser = get_parser(spec.grammar)
    data = source.encode("utf-8")
    tree = parser.parse(data)
    lines = source.splitlines()

    raw_comments: list[_RawComment] = []
    functions: list[FunctionInfo] = []
    # first named non-comment node starting at each row (outermost wins)
    row_first_node: dict[int, str] = {}

    stack: list[tuple[object, str, bool]] = [(tree.root_node, "", False)]
    while stack:
        node, func_name, in_func = stack.pop()
        if node.type in COMMENT_NODE_TYPES:
            raw_comments.append(_RawComment(node, func_name, in_func))
            continue
        if node.is_named and node.type != "translation_unit":
            row_first_node.setdefault(node.start_point[0], node.type)
        child_func, child_in = func_name, in_func
        if node.type in spec.function_nodes:
            name = _function_name(node)
            body = node.child_by_field_name("body")
            if body is not None:
                functions.append(
                    FunctionInfo(
                        path=path,
                        name=name,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        body_line_count=body.end_point[0] - body.start_point[0] + 1,
                    )
                )
            child_func, child_in = name, True
        # push children in reverse so we visit them in source order
        for child in reversed(node.children):
            stack.append((child, child_func, child_in))

    raw_comments.sort(key=lambda c: (c.start_row, c.start_col))

    # rows occupied by comments, and per-row comment span masks
    comment_rows: set[int] = set()
    masks: dict[int, list[tuple[int, int]]] = {}
    for rc in raw_comments:
        for row in range(rc.start_row, rc.end_row + 1):
            comment_rows.add(row)
            line_len = len(lines[row]) if row < len(lines) else 0
            a = rc.start_col if row == rc.start_row else 0
            b = rc.end_col if row == rc.end_row else line_len
            masks.setdefault(row, []).append((a, b))

    code_rows: set[int] = set()
    for row, line in enumerate(lines):
        chars = list(line)
        for a, b in masks.get(row, ()):
            for i in range(a, min(b, len(chars))):
                chars[i] = " "
        if "".join(chars).strip():
            code_rows.add(row)

    first_code_row = min(code_rows) if code_rows else None

    def code_before(rc: _RawComment) -> str:
        line = lines[rc.start_row] if rc.start_row < len(lines) else ""
        return line[: rc.start_col].strip()

    def code_after(rc: _RawComment) -> str:
        line = lines[rc.end_row] if rc.end_row < len(lines) else ""
        return line[rc.end_col:].strip()

    # ---- group adjacent line comments into logical comments ----
    groups: list[list[_RawComment]] = []
    for rc in raw_comments:
        is_line = rc.text.startswith("//")
        trailing = bool(code_before(rc))
        if (
            groups
            and is_line
            and not trailing
            and groups[-1][-1].text.startswith("//")
            and not code_before(groups[-1][-1])
            and rc.start_row == groups[-1][-1].end_row + 1
            and rc.start_col == groups[-1][-1].start_col
            and _doc_class(rc.text, spec) == _doc_class(groups[-1][-1].text, spec)
            # a directive line never merges with prose, so the prose part
            # stays judged and the directive stays protected
            and _directive_line(rc.text, spec) == _directive_line(groups[-1][-1].text, spec)
        ):
            groups[-1].append(rc)
        else:
            groups.append([rc])

    comments: list[Comment] = []
    for group in groups:
        first, last = group[0], group[-1]
        raw_text = "\n".join(g.text for g in group)
        trailing_code = code_before(first)
        after_code = code_after(last)

        next_row_code = (last.end_row + 1) in code_rows
        next_line = lines[last.end_row + 1].strip() if last.end_row + 1 < len(lines) else ""
        before_first_code = first_code_row is None or first.start_row < first_code_row

        if trailing_code:
            attachment = Attachment.TRAILING
            attached = trailing_code
        elif after_code:
            attachment = Attachment.PRECEDING
            attached = after_code
        elif raw_text.startswith(("//!", "/*!")):
            # inner/module doc: documents the file, not the next item
            attachment = Attachment.FILE_HEADER
            attached = ""
        elif before_first_code and (not next_row_code or _IMPORT_LINE_RE.match(next_line)):
            attachment = Attachment.FILE_HEADER
            attached = ""
        elif next_row_code:
            attachment = Attachment.PRECEDING
            attached = next_line
        else:
            attachment = Attachment.FLOATING
            attached = ""

        kind = _classify_kind(raw_text, spec)
        if (
            kind is not Kind.DOC
            and attachment in (Attachment.PRECEDING, Attachment.FILE_HEADER)
            and not first.in_function
            and spec.doc_by_convention_nodes
            and row_first_node.get(last.end_row + 1) in spec.doc_by_convention_nodes
        ):
            # e.g. Go: a comment directly above a declaration or the package
            # clause is a doc comment, even without special markers
            kind = Kind.DOC

        content = strip_markers(raw_text)
        content_head = content.splitlines()[0] if content else ""
        comments.append(
            Comment(
                path=path,
                lang=spec.name,
                kind=kind,
                attachment=attachment,
                text=raw_text,
                content=content,
                start_line=first.start_row + 1,
                end_line=last.end_row + 1,
                col=first.start_col,
                attached_code=attached,
                in_function=first.in_function,
                function_name=first.func_name,
                is_directive=(
                    is_directive_text(content_head, spec.name, kind)
                    or is_cgo_preamble(spec.name, attached)
                ),
            )
        )

    return SourceFile(
        path=path,
        lang=spec.name,
        lines=lines,
        comments=comments,
        functions=functions,
        code_line_count=len(code_rows),
        comment_line_count=len(comment_rows),
    )


def _directive_line(text: str, spec: LangSpec) -> bool:
    return is_directive_text(strip_markers(text.splitlines()[0]), spec.name, Kind.LINE)


def _doc_class(text: str, spec: LangSpec) -> str:
    """Grouping class of a line comment: '//!' and '///' must not merge."""
    for prefix in spec.doc_line_prefixes:
        if text.startswith(prefix):
            return prefix
    return ""


def _classify_kind(text: str, spec: LangSpec) -> Kind:
    if spec.doc_block_prefixes and text.startswith(spec.doc_block_prefixes):
        # bare "/**/" or "/***/" separators are not docs
        if not text.startswith("/**/"):
            return Kind.DOC
    if spec.doc_line_prefixes and text.startswith(spec.doc_line_prefixes):
        return Kind.DOC
    if text.startswith("/*"):
        return Kind.BLOCK
    return Kind.LINE


def extract_file(path: str | Path) -> SourceFile | None:
    """Extract comments from a file; returns None for unsupported extensions."""
    p = Path(path)
    spec = spec_for_path(str(p))
    if spec is None:
        return None
    source = p.read_text(encoding="utf-8", errors="replace")
    return extract_source(str(p), source, spec)

"""Unit tests for comment extraction: kinds, attachments, grouping, functions."""

from __future__ import annotations

from unwaffle.extract import extract_source, strip_markers
from unwaffle.languages import C, GO, JS, RUST, TS
from unwaffle.model import Attachment, Kind


def _one(sf, index=0):
    return sf.comments[index]


def test_trailing_and_preceding_c():
    src = "int x = 1; // trailing note\n// above the next line\nint y = 2;\n"
    sf = extract_source("t.c", src, C)
    assert len(sf.comments) == 2
    trailing, preceding = sf.comments
    assert trailing.attachment is Attachment.TRAILING
    assert trailing.attached_code == "int x = 1;"
    assert preceding.attachment is Attachment.PRECEDING
    assert preceding.attached_code == "int y = 2;"


def test_adjacent_line_comments_group():
    src = "int a;\n// one\n// two\n// three\nint b;\n"
    sf = extract_source("t.c", src, C)
    assert len(sf.comments) == 1
    c = _one(sf)
    assert (c.start_line, c.end_line) == (2, 4)
    assert c.content == "one\ntwo\nthree"
    assert c.attachment is Attachment.PRECEDING


def test_blank_line_breaks_group_and_makes_floating():
    src = "int a;\n// alone\n\n// attached\nint b;\n"
    sf = extract_source("t.c", src, C)
    assert len(sf.comments) == 2
    assert sf.comments[0].attachment is Attachment.FLOATING
    assert sf.comments[1].attachment is Attachment.PRECEDING


def test_file_header_detection():
    src = "// my tool\n// does things\n\n#include <stdio.h>\nint main(void) { return 0; }\n"
    sf = extract_source("t.c", src, C)
    assert sf.comments[0].attachment is Attachment.FILE_HEADER


def test_header_directly_above_include_is_file_header():
    src = "// my tool\n#include <stdio.h>\n"
    sf = extract_source("t.c", src, C)
    assert sf.comments[0].attachment is Attachment.FILE_HEADER


def test_doc_kinds_rust():
    src = "//! module doc\n\n/// item doc\npub fn f() {}\n\n// plain\npub fn g() {}\n"
    sf = extract_source("t.rs", src, RUST)
    kinds = [(c.kind, c.attachment) for c in sf.comments]
    assert kinds[0] == (Kind.DOC, Attachment.FILE_HEADER)
    assert kinds[1] == (Kind.DOC, Attachment.PRECEDING)
    assert kinds[2] == (Kind.LINE, Attachment.PRECEDING)


def test_rust_doc_group_not_merged_across_kinds():
    src = "//! inner\n/// outer\npub fn f() {}\n"
    sf = extract_source("t.rs", src, RUST)
    assert len(sf.comments) == 2


def test_jsdoc_kind():
    src = "/** jsdoc */\nfunction f() {}\n/* plain block */\nfunction g() {}\n"
    sf = extract_source("t.js", src, JS)
    assert sf.comments[0].kind is Kind.DOC
    assert sf.comments[1].kind is Kind.BLOCK


def test_go_convention_doc():
    src = "package p\n\n// Exported does things.\nfunc Exported() {}\n\nfunc inner() {\n\t// interior note\n\t_ = 1\n}\n"
    sf = extract_source("t.go", src, GO)
    assert sf.comments[0].kind is Kind.DOC
    interior = sf.comments[1]
    assert interior.kind is Kind.LINE
    assert interior.in_function
    assert interior.function_name == "inner"


def test_functions_and_bodies():
    src = "function outer() {\n  // inside\n  return 1;\n}\n"
    sf = extract_source("t.ts", src, TS)
    assert [f.name for f in sf.functions] == ["outer"]
    assert sf.comments[0].in_function
    assert sf.comments[0].function_name == "outer"


def test_code_and_comment_line_counts():
    src = "int a; // note\n// full line\nint b;\n"
    sf = extract_source("t.c", src, C)
    assert sf.code_line_count == 2
    assert sf.comment_line_count == 2


def test_crlf_source():
    src = "int a; // trailing note here\r\n// above\r\nint b;\r\n"
    sf = extract_source("t.c", src, C)
    assert len(sf.comments) == 2
    assert sf.comments[0].content == "trailing note here"
    assert "\r" not in sf.comments[0].text
    assert sf.comments[1].attached_code == "int b;"


def test_comment_only_file():
    sf = extract_source("t.c", "// just a note\n// nothing else\n", C)
    assert len(sf.comments) == 1
    assert sf.comments[0].attachment is Attachment.FILE_HEADER
    assert sf.code_line_count == 0


def test_empty_file():
    sf = extract_source("t.c", "", C)
    assert sf.comments == []
    assert sf.functions == []


def test_strip_markers():
    assert strip_markers("// hello") == "hello"
    assert strip_markers("/// doc") == "doc"
    assert strip_markers("/* one\n * two\n */") == "one\ntwo"
    assert strip_markers("/** doc */") == "doc"
    assert strip_markers("//! inner") == "inner"

"""Encoding edges: tree-sitter columns are byte offsets and rows split on \\n
only — BOM, non-ASCII code, and exotic line separators must not shift
classification."""

from __future__ import annotations

from unwaffle.config import Config
from unwaffle.extract import extract_file, extract_source
from unwaffle.languages import C, JS
from unwaffle.model import Attachment
from unwaffle.rules import run_rules


def test_bom_file_keeps_license_exemption(tmp_path):
    src = chr(0xFEFF) + "/* Copyright (c) 2026 Example. MIT license. */\nint x;\n"
    p = tmp_path / "a.c"
    p.write_text(src, encoding="utf-8")  # writes the BOM byte sequence
    sf = extract_file(p)
    c = sf.comments[0]
    assert c.attachment is not Attachment.TRAILING
    assert run_rules(sf, Config()) == []


def test_non_ascii_code_before_trailing_comment():
    src = 'const nombre = "José García"; // owner display name shown in the header\n'
    sf = extract_source("t.js", src, JS)
    c = sf.comments[0]
    assert c.attachment is Attachment.TRAILING
    assert c.attached_code == 'const nombre = "José García";'


def test_form_feed_does_not_desync_rows():
    src = "int a;\n\x0cint b; // note about the flag width here\n"
    sf = extract_source("t.c", src, C)
    c = sf.comments[0]
    assert c.attachment is Attachment.TRAILING
    assert c.start_line == 2
    # the old row desync produced a false UC001 here
    assert not any(f.rule == "UC001" for f in run_rules(sf, Config()))


def test_unicode_line_separator_in_string_literal():
    src = 'const s = "a b";\n// explains the odd separator kept for parity with upstream data\nconst t = 1;\n'
    sf = extract_source("t.js", src, JS)
    assert sf.comments[0].start_line == 2
    assert sf.comments[0].attachment is Attachment.PRECEDING
    assert sf.comments[0].attached_code == "const t = 1;"

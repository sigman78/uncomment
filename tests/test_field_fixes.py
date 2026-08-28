"""Regressions from the first real-world deployment (esperdeck field report):
arrow-notation prose, lifetime docs, flood escalation, UC009 limits,
doc-tag sentence segmentation, legacy-console output."""

from __future__ import annotations

import io
import sys
from pathlib import Path

from uncomment.cli import main
from uncomment.config import Config
from uncomment.extract import extract_source
from uncomment.gate import gate_file
from uncomment.languages import C, JS, spec_for_path
from uncomment.rules import run_rules
from uncomment.textutil import sentences


def _fired(path: str, src: str, spec, cfg: Config | None = None):
    return {f.rule for f in run_rules(extract_source(path, src, spec), cfg or Config())}


# UC005: spaced arrows are mapping prose, attached arrows are code

def test_arrow_mapping_prose_is_not_dead_code():
    py = spec_for_path("x.py")
    cases = [
        ("t.c", '#include "keymap.h" /* HIDKEY events -> ui_key_t */\n', C),
        ("t.py", 'seen = {}  # (src_comp, dst_comp) -> first "file:line" for the report\n', py),
        ("t.py", "# Allowed edges: component -> components it may include headers from.\n"
                 "# ssh -> libssh2_esp (vendored fork)\n"
                 "EDGES = {}\n", py),
    ]
    for path, src, spec in cases:
        assert "UC005" not in _fired(path, src, spec), src


def test_attached_member_arrow_is_still_code():
    src = "void f(node *t, node *q) {\n// tail->next\nuse(t);\n}\n"
    assert "UC005" in _fired("t.c", src, C)


# UC003: lifetime prose vs behavioral change narration

def test_no_longer_needed_lifetime_doc_is_clean():
    src = ("/* It is a responsibility of the user to free the parsed report map,\n"
           "   when it's no longer needed */\nvoid *parse(void);\n")
    assert "UC003" not in _fired("t.c", src, C)


def test_no_longer_uses_is_still_edit_narration():
    src = "// this helper no longer uses the shared buffer\nint x;\n"
    assert "UC003" in _fired("t.c", src, C)


# UC100: info hints and doc comments never escalate into a flood

def _gate(tmp_path, old: str, new: str):
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    (old_dir / "a.h").write_text(old, encoding="utf-8")
    (new_dir / "a.h").write_text(new, encoding="utf-8")
    findings, _, _ = gate_file(new_dir / "a.h", str(old_dir), new_dir, Config())
    return findings


def test_doc_block_with_info_hints_does_not_flood(tmp_path):
    old = "int existing(void);\n"
    # 14 doc lines wordy enough to draw STE hints, but zero warn/error findings
    doc = "/**\n * Demonstrates the keymap facility.\n" + "".join(
        f" * @param p{i} value which is used by the mapping layer number {i}\n" for i in range(12)
    ) + " */\n"
    new = old + doc + "int keymap(void);\n"
    findings = _gate(tmp_path, old, new)
    assert any(f.rule.startswith("STE") for f in findings)  # hints present
    assert not any(f.rule == "UC100" for f in findings)


def test_warn_noisy_lines_still_flood(tmp_path):
    old = "int existing(void);\n"
    noise = "".join(f"// then we run filler step number {i} of the plan\n" for i in range(14))
    findings = _gate(tmp_path, old, noise + old)
    assert any(f.rule == "UC100" for f in findings)


# UC009: the message names the limit that tripped

def test_trailing_message_names_word_limit():
    src = "int x = 1; // a note that has quite a lot of small words in it here\n"
    findings = [f for f in run_rules(extract_source("t.c", src, C), Config()) if f.rule == "UC009"]
    assert findings and "limit 10" in findings[0].message and "words" in findings[0].message


def test_max_trailing_words_is_configurable():
    src = "int x = 1; // a note that has quite a lot of small words in it here\n"
    assert "UC009" not in _fired("t.c", src, C, Config(max_trailing_words=20))


# STE01: doc tags and joined clauses segment properly

def test_doc_tag_lines_are_separate_sentences():
    text = ("Maps a HID usage to the internal key code\n"
            "@param usage HID usage id from the report descriptor\n"
            "@param modifiers active modifier bitmask taken from byte 0\n"
            "@return internal key code or KEY_NONE when the usage has no mapping")
    assert len(sentences(text)) == 4


def test_semicolon_and_dash_clauses_split():
    assert len(sentences("first clause; second clause")) == 2
    assert len(sentences("ssh -> libssh2_esp vendored fork")) == 2
    assert len(sentences("one thing — another thing")) == 2


def test_doxygen_block_produces_no_ste01():
    src = ("/**\n"
           " * Maps a HID usage to the internal key code\n"
           " * @param usage      HID usage id from the report descriptor\n"
           " * @param modifiers  active modifier bitmask taken from byte 0\n"
           " * @return internal key code, or KEY_NONE when the usage has no mapping\n"
           " */\n"
           "int keymap_lookup(int usage, int modifiers);\n")
    assert "STE01" not in _fired("t.h", src, C)


# unicode-output auto-fallback on legacy consoles

def _run_with_stdout_encoding(tmp_path, monkeypatch, encoding: str) -> bytes:
    noisy = tmp_path / "a.js"
    noisy.write_text("// Updated the constant as requested\nconst a = 1;\n", encoding="utf-8")
    buf = io.BytesIO()
    fake = io.TextIOWrapper(buf, encoding=encoding)
    monkeypatch.setattr(sys, "stdout", fake)
    main(["check", str(noisy), "--fail-on", "never"])
    fake.flush()
    return buf.getvalue()

def test_legacy_console_gets_ascii(tmp_path, monkeypatch):
    out = _run_with_stdout_encoding(tmp_path, monkeypatch, "cp1252")
    # the UC003 message quotes typography; on cp1252 it must arrive transliterated
    assert b"..." in out and "…".encode("utf-8") not in out


def test_utf8_console_keeps_unicode(tmp_path, monkeypatch):
    out = _run_with_stdout_encoding(tmp_path, monkeypatch, "utf-8")
    assert "…".encode("utf-8") in out

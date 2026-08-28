"""uncomment-ignore-file[RULE]: file-wide exceptions for rule-shaped house
patterns (spec transcriptions), plus the UC102 self-grant notice."""

from __future__ import annotations

import json

from uncomment.cli import main
from uncomment.config import Config
from uncomment.extract import extract_source
from uncomment.gate import gate_file
from uncomment.languages import JAVA
from uncomment.rules import run_rules

SPEC_STEPS = (
    "class TreeBuilder {\n"
    "    int run(int t) {\n"
    "        // step 4. if none before, skip to 8\n"
    "        int a = t;\n"
    "        // step 5. one earlier than entry\n"
    "        int b = a;\n"
    "        // then we replace entry with the new entry\n"
    "        return b;\n"
    "    }\n"
    "}\n"
)


def _rules_fired(src: str):
    return {f.rule for f in run_rules(extract_source("t.java", src, JAVA), Config())}


def test_file_marker_suppresses_rule_file_wide():
    marked = "// uncomment-ignore-file[UC002]: transcribes the WHATWG tree-builder steps\n" + SPEC_STEPS
    assert "UC002" in _rules_fired(SPEC_STEPS)
    assert "UC002" not in _rules_fired(marked)


def test_file_marker_takes_multiple_rules():
    src = ("// uncomment-ignore-file[UC002,UC005]: fixture transcription\n"
           "// then we run the fixture step\n"
           "// int dead = code();\n"
           "int x;\n")
    fired = _rules_fired(src)
    assert "UC002" not in fired and "UC005" not in fired


def test_other_rules_stay_armed():
    marked = ("// uncomment-ignore-file[UC002]: spec transcription\n"
              + SPEC_STEPS.replace("        return b;", "        int c = b;\n        // int dead = old(t);\n        return c;"))
    assert "UC005" in _rules_fired(marked)


def test_file_form_is_not_a_bare_span_marker():
    # a misparse as bare marker would silence the comment directly below
    src = ("// uncomment-ignore-file[UC009]: long trailing allowed here\n"
           "// Changed the loop to use sum() as requested\n"
           "int x;\n")
    assert "UC003" in _rules_fired(src)


def test_span_marker_does_not_grant_file_wide():
    src = ("class C {\n"
           "    // first we check the fixture uncomment-ignore[UC002]: reviewed\n"
           "    int a;\n"
           "    // then we replace entry with the new entry\n"
           "    int b;\n"
           "}\n")
    assert "UC002" in _rules_fired(src)  # the second comment is uncovered


def _gate(tmp_path, old_text, new_text):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir(exist_ok=True)
    new.mkdir(exist_ok=True)
    (old / "a.java").write_text(old_text, encoding="utf-8")
    (new / "a.java").write_text(new_text, encoding="utf-8")
    findings, _, _ = gate_file(new / "a.java", str(old), new, Config())
    return findings


def test_file_marker_reaches_gate_signals(tmp_path):
    flood = "".join(f"// then we run filler step number {i} of the plan\n" for i in range(14))
    old = "int existing;\n"
    marked = "// uncomment-ignore-file[UC100,UC002]: generated protocol fixture\n" + flood + old
    assert any(f.rule == "UC100" for f in _gate(tmp_path, old, flood + old))
    assert not any(f.rule == "UC100" for f in _gate(tmp_path, old, marked))


def test_new_grant_raises_uc102_notice(tmp_path):
    old = SPEC_STEPS
    marked = "// uncomment-ignore-file[UC002]: transcribes the WHATWG steps\n" + SPEC_STEPS
    notices = [f for f in _gate(tmp_path, old, marked) if f.rule == "UC102"]
    assert len(notices) == 1
    assert "UC002" in notices[0].message
    assert "WHATWG" in notices[0].excerpt


def test_preexisting_grant_is_silent(tmp_path):
    marked = "// uncomment-ignore-file[UC002]: transcribes the WHATWG steps\n" + SPEC_STEPS
    assert not any(f.rule == "UC102" for f in _gate(tmp_path, marked, marked))


def test_rules_listing_includes_uc102(capsys):
    main(["rules", "--format", "json"])
    doc = json.loads(capsys.readouterr().out)
    assert any(r["id"] == "UC102" and r["gate_only"] for r in doc)

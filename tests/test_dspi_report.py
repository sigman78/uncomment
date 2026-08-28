"""Round 5: false-positive classes from the dspi-web-console field report
(notes/FIELD-REPORT-2026-08-27-dspi-web-console.md)."""

from __future__ import annotations

from unwaffle.cli import main
from unwaffle.config import Config
from unwaffle.extract import extract_source
from unwaffle.languages import spec_for_path
from unwaffle.rules import run_rules

TS = spec_for_path("x.ts")


def _fired(src: str):
    return {f.rule for f in run_rules(extract_source("t.ts", src, TS), Config())}


# UC003: runtime data called "the old code" is not edit history

def test_runtime_old_code_is_clean():
    src = ("// Drop any previous result synchronously, BEFORE the device round-trip:\n"
           "// a stale DONE/TIMEOUT would complete the new learn with the old code.\n"
           "export const x = 1;\n")
    assert "UC003" not in _fired(src)


def test_edit_verb_with_old_code_still_errors():
    src = "// this replaces the old code that walked the tree twice\nexport const x = 1;\n"
    assert "UC003" in _fired(src)


def test_old_implementation_still_errors():
    src = "// the old implementation walked the tree twice\nexport const x = 1;\n"
    assert "UC003" in _fired(src)


# UC003: participial-adjective "Fixed <noun>" openers

def test_fixed_adjective_openers_are_clean():
    for text in (
        "Fixed input x output grid; iterate the live side.",
        "Fixed order traversal keeps replay deterministic.",
        "Fixed window of eight samples per estimate.",
    ):
        assert "UC003" not in _fired(f"// {text}\nexport const x = 1;\n"), text


def test_fixed_bugfix_narration_still_warns():
    for text in ("Fixed the race in session teardown", "Fixed handling of empty payloads"):
        assert "UC003" in _fired(f"// {text}\nexport const x = 1;\n"), text


# UC005: byte-layout and math glosses are prose

def test_wire_glosses_are_not_dead_code():
    for text in (
        "PARAM_CHANGED, source=HOST(1), size=0",
        "qp = round(1.5*512) = 768, little-endian at bytes 16-17.",
        "{current pipeline Hz, selected I2S input Hz}",
        "LR(N) = BW(N/2) squared: every half-order pole doubled.",
    ):
        assert "UC005" not in _fired(f"// {text}\nexport const x = 1;\n"), text


def test_enum_encoding_gloss_block_is_not_dead_code():
    src = ("// Wire encoding of the mode field:\n"
           "// 0 = unified (single volume for both channels)\n"
           "// 1 = split (independent per-channel volume)\n"
           "export const MODES = 2;\n")
    assert "UC005" not in _fired(src)


def test_assignment_to_call_statement_still_fires():
    src = "export function f() {\n  // x = compute()\n  return 1;\n}\n"
    assert "UC005" in _fired(src)


# walk-skip visibility

def test_unsupported_language_walk_note(tmp_path, capsys):
    for i in range(6):
        (tmp_path / f"c{i}.svelte").write_text("<script>let a = 1;</script>\n", encoding="utf-8")
    (tmp_path / "a.ts").write_text("export const a = 1;\n", encoding="utf-8")
    import json

    code = main(["check", str(tmp_path), "--fail-on", "never", "--format", "json"])
    captured = capsys.readouterr()
    assert code == 0
    assert ".svelte x6" in captured.err
    assert json.loads(captured.out)["stats"]["files_unsupported"] == 6


# Round 2 residuals: the cleared/remaining contrast pairs, all now prose

def test_wire_enum_gloss_variants_are_prose():
    for text in (
        "state=TIMEOUT(3)",
        "state=LOCKED(3), rate=48000 LE, clockMode=1 (slave)",
        "state=DONE(2), protocol=NEC(1), code=0x12345678 LE",
    ):
        assert "UC005" not in _fired(f"// {text}\nexport const x = 1;\n"), text


def test_sentence_wrapped_gloss_block_is_prose():
    src = ('// I2S slave-clock pins (fw V21+; decoded from clockPinModeP1, "0 = absent"\n'
           "// wire convention). 0 = unified (legacy: master+slave share one BCK/LRCLK\n"
           "// pair), 1 = split (master drives bckPin, slave listens on bckPinSlave;\n"
           "// LRCLK = BCK+1 in both).\n"
           "export const clockPinMode = 0;\n")
    assert "UC005" not in _fired(src)


def test_nested_call_assignment_still_fires():
    src = "export function f() {\n  // x = wrap(inner(x))\n  return 1;\n}\n"
    assert "UC005" in _fired(src)


def test_statement_boundary_wrapped_dead_code_still_fires():
    src = ("export function f() {\n"
           "  // const a = load(path);\n"
           "  // return a.merge(env);\n"
           "  return 1;\n}\n")
    assert "UC005" in _fired(src)

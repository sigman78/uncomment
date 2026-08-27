"""P2 detection quality: operator verbalization, WHY-guards, diagram and
formula recognition, chained-call dead code."""

from __future__ import annotations

from uncomment.config import Config
from uncomment.extract import extract_source
from uncomment.languages import C, GO, JS
from uncomment.rules import run_rules
from uncomment.textutil import code_words, overlap_ratio


def _fired(path, src, spec, cfg=None):
    return {f.rule for f in run_rules(extract_source(path, src, spec), cfg or Config())}


# ---- UC001: operator verbalization ----

def test_increment_comment_restates_increment_operator():
    assert "UC001" in _fired("t.c", "void f(void){\n// increment the counter\ncounter++;\n}\n", C)


def test_set_comment_restates_assignment():
    assert "UC001" in _fired("t.c", "void f(void){\n// set value to five\nvalue = 5;\n}\n", C)


def test_three_line_restatement_now_fires():
    src = (
        "void f(void){\n"
        "// add the value\n"
        "// to the total\n"
        "// and keep the total\n"
        "total += value;\n}\n"
    )
    assert "UC001" in _fired("t.c", src, C)


def test_operator_words_present():
    words = code_words("counter++;")
    assert "increment" in words
    assert overlap_ratio("increment the counter", "counter++;") == 1.0


# ---- UC002: WHY-guard and continuation lines ----

def test_why_comment_starting_with_we_is_spared():
    src = "void f(void){\n// We cannot use memcpy here because the regions overlap.\nmemmove(a, b, n);\n}\n"
    assert "UC002" not in _fired("t.c", src, C)


def test_narration_on_continuation_line_is_caught():
    src = (
        "void f(void){\n"
        "// The buffer arrives untrimmed from the reader.\n"
        "// Now we validate the input and normalize it.\n"
        "check(buf);\n}\n"
    )
    assert "UC002" in _fired("t.c", src, C)


def test_lets_encrypt_product_name_is_not_narration():
    src = "// Let's Encrypt rate-limits renewals to five per week.\nrenew();\n"
    assert "UC002" not in _fired("t.js", src, JS)


def test_lowercase_lets_verb_is_still_narration():
    src = "function f() {\n  // let's encrypt the payload before sending\n  return seal(p);\n}\n"
    assert "UC002" in _fired("t.js", src, JS)


def test_capital_lets_with_lowercase_verb_is_still_narration():
    src = "function f() {\n  // Let's walk the tree and collect the ids\n  return walk(t);\n}\n"
    assert "UC002" in _fired("t.js", src, JS)


# ---- UC004: diagrams are not banners ----

def test_box_diagram_is_not_a_banner():
    src = (
        "// +----------+----------+-----------+\n"
        "// | version  | flags    | payload   |\n"
        "// +----------+----------+-----------+\n"
        "int parse(void);\n"
    )
    assert "UC004" not in _fired("t.c", src, C)


def test_plain_banner_still_fires():
    assert "UC004" in _fired("t.c", "// ==========================================\nint x;\n", C)


# ---- UC005: formulas, invariant sketches, chained calls ----

def test_prose_invariant_sketch_is_not_dead_code():
    src = (
        "void f(void){\n"
        "// lo = first index that might match;\n"
        "// hi = first index that is definitely past;\n"
        "// the answer lives in the half-open range.\n"
        "search(lo, hi);\n}\n"
    )
    assert "UC005" not in _fired("t.c", src, C)


def test_formula_restatement_reports_uc001_not_uc005():
    src = "double f(double r, double theta){\n// x = r * cos(theta)\nreturn r * cos(theta);\n}\n"
    fired = _fired("t.c", src, C)
    assert "UC001" in fired
    assert "UC005" not in fired


def test_chained_call_dead_code_is_caught():
    src = "function f() {\n  // cfg.load(path).merge(env).apply()\n  return 1;\n}\n"
    assert "UC005" in _fired("t.js", src, JS)

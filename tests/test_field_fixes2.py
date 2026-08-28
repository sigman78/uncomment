"""Round 2 of real-world fixes (esperdeck full-tree sweep, Addendum 2):
effective-severity labels, net-growth amplification, legend-class UC005."""

from __future__ import annotations

from uncomment.config import Config
from uncomment.extract import extract_source
from uncomment.gate import gate_file
from uncomment.languages import C, spec_for_path
from uncomment.report import render_agent
from uncomment.rules import run_rules

PY = spec_for_path("x.py")


def _fired(path: str, src: str, spec, cfg: Config | None = None):
    return {f.rule for f in run_rules(extract_source(path, src, spec), cfg or Config())}


# ---- agent labels mirror effective severity ----

def test_promoted_rule_is_marked_must_fix():
    cfg = Config(severity={"STE01": "warn"})
    src = ("// this sentence keeps going with many small words so that it runs "
           "well past the twenty word simplified technical english limit today\n"
           "const a = 1;\n")
    findings = run_rules(extract_source("t.js", src, spec_for_path("x.js")), cfg)
    out = render_agent(findings, {"files_scanned": 1}, cfg)
    assert "`STE01` [MUST FIX]" in out


def test_demoted_rule_is_marked_consider():
    cfg = Config(severity={"UC004": "info"})
    src = "// ==========================================\nconst a = 1;\n"
    findings = run_rules(extract_source("t.js", src, spec_for_path("x.js")), cfg)
    out = render_agent(findings, {"files_scanned": 1}, cfg)
    assert "`UC004` [consider]" in out


# ---- UC101 measures net growth, not rewrite volume ----

def _gate(tmp_path, old_text, new_text):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "a.py").write_text(old_text, encoding="utf-8")
    (new / "a.py").write_text(new_text, encoding="utf-8")
    findings, _, _ = gate_file(new / "a.py", str(old), new, Config())
    return findings


def test_inplace_rewrite_is_not_amplification(tmp_path):
    # nine prose lines reworded beyond fuzzy similarity, one sentence split:
    # net growth of one line must not read as amplification
    old_lines = [f"# The handler number {i} owns its retry budget across restarts.\nH{i} = {i}\n" for i in range(9)]
    new_lines = [
        f"# Handler number {i} keeps one retry budget. The budget survives restarts.\nH{i} = {i}\n"
        for i in range(9)
    ]
    new_lines[0] = ("# Handler number 0 keeps one retry budget.\n"
                    "# The budget survives every restart cycle.\nH0 = 0\n")
    findings = _gate(tmp_path, "".join(old_lines), "".join(new_lines))
    assert not any(f.rule == "UC101" for f in findings)


def test_true_doubling_still_amplifies(tmp_path):
    old = "# The parser keeps one token of lookahead here.\nA = 1\n"
    extra = "".join(f"# Elaboration line number {i} restates the design choice again.\n" for i in range(7))
    findings = _gate(tmp_path, old, extra + old)
    assert any(f.rule == "UC101" for f in findings)


# ---- UC005: legends are prose, dead code still is not ----

LEGENDS = [
    ("t.c", "/* LI=0 VN=3 Mode=3 client */\nstatic unsigned char b = 0x1B;\n", C),
    ("t.c", "/* duty = avg_cycles/chunk * chunks/s / core_hz; tenths of a percent */\n\nint duty;\n", C),
    ("t.c", "/* r=0xF8 -> bits[15:11]=11111; g=0, b=0 -> 0xF800 */\n\nint rgb;\n", C),
    ("t.py", '_glyphs = {}  # WxH: (normal BDF, bold BDF)\n', PY),
    ("t.py", "_last = None  # None = never written (a bug)\n", PY),
    ("t.py", "# Cyrillic (basic Russian + extensions)\nRANGE = (0x0400, 0x04FF)\n", PY),
]


def test_legend_comments_are_not_dead_code():
    for path, src, spec in LEGENDS:
        assert "UC005" not in _fired(path, src, spec), src


def test_single_line_dead_code_still_fires():
    cases = [
        ("t.py", "def f():\n    y = 2\n    # x = compute()\n    return y\n", PY),
        ("t.c", "void f(void) {\n// q->next = p;\nuse(p);\n}\n", C),
        ("t.c", "void f(void) {\n// free(buf);\nuse(buf);\n}\n", C),
    ]
    for path, src, spec in cases:
        assert "UC005" in _fired(path, src, spec), src

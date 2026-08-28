"""Round 3 of real-world fixes (esperdeck Addendums 3-5): file-level
suppression for gate signals, marker lines never counted, Unicode banners,
alignment padding."""

from __future__ import annotations

from unwaffle.config import Config
from unwaffle.extract import extract_source
from unwaffle.gate import gate_file
from unwaffle.languages import C
from unwaffle.rules import run_rules


def _fired(src: str, cfg: Config | None = None):
    return {f.rule for f in run_rules(extract_source("t.c", src, C), cfg or Config())}


def _gate(tmp_path, old_text, new_text):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir(exist_ok=True)
    new.mkdir(exist_ok=True)
    (old / "a.c").write_text(old_text, encoding="utf-8")
    (new / "a.c").write_text(new_text, encoding="utf-8")
    findings, _, _ = gate_file(new / "a.c", str(old), new, Config())
    return findings


OLD = "int existing;\n"
SPREE = OLD + "".join(f"// elaboration line number {i} restates the design choice\n" for i in range(8)) + "int more;\n"
FLOOD = "".join(f"// then we run filler step number {i} of the plan\n" for i in range(14)) + OLD


# file-level suppression reaches the gate signals

def test_marker_suppresses_uc101_file_wide(tmp_path):
    marked = "// unwaffle-ignore[UC101]: reviewed, sweep rewrite\n" + SPREE
    old = "// The parser keeps one token of lookahead here.\n" + OLD
    assert any(f.rule == "UC101" for f in _gate(tmp_path, old, old + SPREE))
    assert not any(f.rule == "UC101" for f in _gate(tmp_path, old, old + marked))


def test_marker_suppresses_uc100_file_wide(tmp_path):
    marked = "// unwaffle-ignore[UC100]: generated test fixture\n" + FLOOD
    assert any(f.rule == "UC100" for f in _gate(tmp_path, OLD, FLOOD))
    assert not any(f.rule == "UC100" for f in _gate(tmp_path, OLD, marked))


def test_bare_marker_elsewhere_does_not_clear_gate_signals(tmp_path):
    # file-wide clearing demands an explicit rule list; a bare marker only
    # covers its own span, and here that span is an unrelated tail line
    marked = FLOOD + "// unwaffle-ignore: reviewed elsewhere\nint tail;\n"
    assert any(f.rule == "UC100" for f in _gate(tmp_path, OLD, marked))


def test_marker_line_never_counts_as_prose(tmp_path):
    # 9 prose lines, then the same comment gains only a marker line: net
    # growth must stay zero, not one
    old = "".join(f"// handler number {i} owns its retry budget here\n" for i in range(9)) + OLD
    new = old.replace(
        "// handler number 8 owns its retry budget here\n",
        "// handler number 8 owns its retry budget here\n// unwaffle-ignore[UC009]: aligned\n",
    )
    assert not any(f.rule == "UC101" for f in _gate(tmp_path, old, new))


# UC004: Unicode box-drawing banners, diagrams stay exempt

def test_unicode_banners_flag():
    for line in ("/* ── Section ────── */", "/* ══ init ══════ */", "/* ━━━━━━━━━━ */"):
        assert "UC004" in _fired(f"{line}\nint x;\n"), line


def test_unicode_box_diagram_is_not_a_banner():
    src = ("/* ┌──────────┬───────────┐\n"
           " * │ hdr      │ payload   │\n"
           " * └──────────┴───────────┘\n"
           " */\n"
           "int parse_frame(void);\n")
    assert "UC004" not in _fired(src)


def test_slash_heavy_prose_is_not_a_banner():
    src = "// see https://x.dev/a/, https://x.dev/b/ and https://x.dev/c/\nint x;\n"
    assert "UC004" not in _fired(src)


# UC009: alignment padding is not length

def test_alignment_padding_does_not_trip_uc009():
    pad = " " * 44
    src = f"int a; /* landing view{pad}*/\n"
    assert len(src) > 60
    assert "UC009" not in _fired(src)


def test_collapsed_overlong_trailing_still_fires():
    src = "int a; /* this text is genuinely long enough to blow past the sixty char limit */\n"
    assert "UC009" in _fired(src)

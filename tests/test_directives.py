"""Linter/compiler control comments must never be judged or gated."""

from __future__ import annotations

from uncomment.config import Config
from uncomment.extract import extract_source
from uncomment.languages import C, GO, JS, RUST, TS
from uncomment.rules import run_rules


def _rules_fired(path, src, spec, cfg=None):
    sf = extract_source(path, src, spec)
    return {f.rule for f in run_rules(sf, cfg or Config())}, sf


def test_eslint_and_ts_directives_exempt():
    src = (
        "// eslint-disable-next-line no-eval\n"
        "eval(code);\n"
        "// @ts-expect-error legacy shim has no types and this cast is deliberate\n"
        "const x = shim();\n"
        "/* eslint no-console: \"off\" */\n"
        "/* istanbul ignore next */\n"
        "// prettier-ignore\n"
        "const m = [1, 2, 3];\n"
    )
    fired, sf = _rules_fired("t.ts", src, TS)
    assert all(c.is_directive for c in sf.comments), [c.content for c in sf.comments]
    assert fired == set()


def test_go_directives_exempt():
    src = (
        "//go:build linux\n"
        "// +build linux\n\n"
        "package p\n\n"
        "//go:generate stringer -type=Kind\n"
        "func F() {\n"
        "\tx := 1 //nolint:gomnd this magic number is fine here and the line is quite long\n"
        "\t_ = x\n"
        "}\n"
    )
    fired, sf = _rules_fired("t.go", src, GO)
    assert all(c.is_directive for c in sf.comments)
    assert fired == set()


def test_cgo_preamble_not_commented_out_code():
    src = (
        "package p\n\n"
        "// #include <stdlib.h>\n"
        "// #include <stdio.h>\n"
        "// static int helper(int a) { return a * 2; }\n"
        'import "C"\n'
    )
    fired, sf = _rules_fired("t.go", src, GO)
    assert sf.comments[0].is_directive
    assert "UC005" not in fired
    assert fired == set()


def test_c_nolint_and_clang_format_exempt():
    src = (
        "int x = 1234; // NOLINT(readability-magic-numbers) calibration constant from the datasheet\n"
        "// clang-format off\n"
        "int m[2][2] = { {1, 0},\n"
        "                {0, 1} };\n"
        "// clang-format on\n"
    )
    fired, sf = _rules_fired("t.c", src, C)
    assert all(c.is_directive for c in sf.comments)
    assert fired == set()  # the long trailing NOLINT must not trip UC009


def test_rust_compiletest_directive_exempt():
    fired, sf = _rules_fired("t.rs", "//@ check-pass\nfn main() {}\n", RUST)
    assert sf.comments[0].is_directive
    assert fired == set()


def test_directive_does_not_group_with_prose():
    src = (
        "// Changed to eval as requested\n"
        "// eslint-disable-next-line no-eval\n"
        "eval(code);\n"
    )
    sf = extract_source("t.js", src, JS)
    assert len(sf.comments) == 2
    assert not sf.comments[0].is_directive
    assert sf.comments[1].is_directive
    findings = run_rules(sf, Config())
    assert {(f.rule, f.line) for f in findings} == {("UC003", 1)}


def test_prose_starting_with_global_is_not_a_directive():
    src = "// global mutex protects the cache during rehashing\nlet m = 0;\n"
    sf = extract_source("t.js", src, JS)
    assert not sf.comments[0].is_directive


def test_config_extra_directive_patterns():
    src = "// MY-LINT: suppress warning 42 because the vendor header is broken\nint x;\n"
    cfg = Config(directive_patterns=[r"^MY-LINT:"])
    fired, _ = _rules_fired("t.c", src, C, cfg)
    assert fired == set()


def test_directives_do_not_count_in_gate(tmp_path):
    from uncomment.gate import gate_file

    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    (old_dir / "a.go").write_text("package p\n\nfunc F() {}\n", encoding="utf-8")
    new = (
        "//go:build linux\n\n"
        "package p\n\n"
        "//go:generate stringer -type=Kind\n"
        "func F() {}\n"
    )
    (new_dir / "a.go").write_text(new, encoding="utf-8")
    findings, _, stats = gate_file(new_dir / "a.go", str(old_dir), new_dir, Config())
    assert findings == []
    assert stats["new_comments"] == 0
    assert stats["new_comment_lines"] == 0

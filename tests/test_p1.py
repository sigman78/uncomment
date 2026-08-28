"""P1 gate semantics: fuzzy tree-wide baseline matching, noise-density flood,
per-line directive exemption, unwaffle-ignore suppressions, UC003 tiers."""

from __future__ import annotations

from pathlib import Path

from unwaffle.config import Config
from unwaffle.extract import extract_source
from unwaffle.gate import gate_file, gate_paths
from unwaffle.languages import C, JS
from unwaffle.model import Severity
from unwaffle.rules import run_rules


def _tree(tmp_path, name: str, files: dict[str, str]) -> Path:
    root = tmp_path / name
    root.mkdir()
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def _rules_fired(path, src, spec, cfg=None):
    sf = extract_source(path, src, spec)
    return run_rules(sf, cfg or Config())


# fuzzy / tree-wide baseline matching

def test_typo_fix_is_not_a_new_comment(tmp_path):
    old = _tree(tmp_path, "old", {"a.js": "// Keeps latency low on slow disks becuase of caching.\nconst a = 1;\n"})
    new = _tree(tmp_path, "new", {"a.js": "// Keeps latency low on slow disks because of caching.\nconst a = 1;\n"})
    _, _, stats = gate_file(new / "a.js", str(old), new, Config())
    assert stats["new_comments"] == 0


def test_cross_file_move_is_not_new(tmp_path):
    comment = "// Debounce keeps request volume manageable on slow links.\n"
    old = _tree(tmp_path, "old", {"a.js": comment + "const a = 1;\n", "b.js": "const b = 2;\n"})
    new = _tree(tmp_path, "new", {"a.js": "const a = 1;\n", "b.js": comment + "const b = 2;\n"})
    result = gate_paths([new], str(old), Config())
    assert result.new_comments == 0
    assert result.findings == []


def test_renamed_file_comments_are_not_new(tmp_path):
    body = (
        "// The retry budget is shared between endpoints on purpose:\n"
        "// exhausting it on one endpoint must slow the others too,\n"
        "// so a flapping backend cannot starve the healthy ones.\n"
        "export function retry() {}\n"
    )
    old = _tree(tmp_path, "old", {"impl.js": body})
    new = _tree(tmp_path, "new", {"impl_v2.js": body})
    result = gate_paths([new], str(old), Config())
    assert result.new_comments == 0
    assert not any(f.rule == "UC100" for f in result.findings)


# noise-density flood

def test_license_header_new_file_does_not_flood(tmp_path):
    license_lines = "\n".join(f"// license line {i}: permission text of the MIT license" for i in range(14))
    new = _tree(tmp_path, "new", {"api.js": "// Copyright (c) 2026 Example\n" + license_lines + "\nconst a = 1;\n"})
    old = _tree(tmp_path, "old", {})
    findings, _, stats = gate_file(new / "api.js", str(old), new, Config())
    assert stats["new_comment_lines"] >= 14
    assert not any(f.rule == "UC100" for f in findings)


def test_narration_flood_still_fires(tmp_path):
    noise = "".join(f"// then we run filler step number {i} of the plan\n" for i in range(14))
    new = _tree(tmp_path, "new", {"a.js": noise + "export function f() {\n  return 1;\n}\n"})
    old = _tree(tmp_path, "old", {"a.js": "export function f() {\n  return 1;\n}\n"})
    findings, _, _ = gate_file(new / "a.js", str(old), new, Config())
    assert any(f.rule == "UC100" for f in findings)


# per-line directive exemption

def test_prose_block_behind_eslint_disable_is_judged():
    src = (
        "/* eslint-disable no-magic-numbers\n"
        " * Changed the retry logic as requested by the reviewer.\n"
        " * Now we walk through each step of the process.\n"
        " */\n"
        "const x = 1;\n"
    )
    fired = {f.rule for f in _rules_fired("t.js", src, JS)}
    assert "UC003" in fired


def test_single_line_eslint_block_still_exempt():
    src = '/* eslint no-console: "off" */\nconst x = 1;\n'
    sf = extract_source("t.js", src, JS)
    assert sf.comments[0].is_directive


def test_nolint_colon_prose_is_judged():
    src = "// NOLINT: Switched to the cached path as requested by the reviewer.\nint x;\n"
    fired = {f.rule for f in _rules_fired("t.c", src, C)}
    assert "UC003" in fired


def test_nolint_paren_with_rationale_still_exempt():
    src = "int x = 1234; // NOLINT(readability-magic-numbers) calibration constant\n"
    sf = extract_source("t.c", src, C)
    assert sf.comments[0].is_directive


# unwaffle-ignore suppressions

def test_inline_suppression_of_named_rule():
    src = "// Changed the retry logic as requested unwaffle-ignore[UC003]: policy exception\nint x;\n"
    fired = {f.rule for f in _rules_fired("t.c", src, C)}
    assert "UC003" not in fired


def test_standalone_marker_covers_next_comment():
    src = (
        "void f(void) {\n"
        "    // unwaffle-ignore[UC005]: kept as a worked example\n"
        "    // int old = compute();\n"
        "    // use(old);\n"
        "}\n"
    )
    fired = {f.rule for f in _rules_fired("t.c", src, C)}
    assert "UC005" not in fired


def test_suppression_is_rule_scoped():
    src = (
        "// unwaffle-ignore[UC005]\n"
        "// Changed the retry logic as requested\n"
        "int x;\n"
    )
    fired = {f.rule for f in _rules_fired("t.c", src, C)}
    assert "UC003" in fired  # only UC005 was suppressed


def test_marker_comment_is_not_judged_or_counted(tmp_path):
    old = _tree(tmp_path, "old", {"a.c": "int x;\n"})
    new = _tree(tmp_path, "new", {"a.c": "// unwaffle-ignore[UC001]: reviewed\nint x;\n"})
    findings, _, stats = gate_file(new / "a.c", str(old), new, Config())
    assert findings == []
    assert stats["new_comments"] == 0


# UC003 evidence tiers

def _uc003(src: str):
    return [f for f in _rules_fired("t.c", src, C) if f.rule == "UC003"]


def test_uc003_explicit_context_is_error():
    found = _uc003("// Simplified the retry logic as requested by the reviewer\nint x;\n")
    assert found and found[0].severity == Severity.ERROR


def test_uc003_opener_alone_is_warn():
    found = _uc003("// Simplified the retry logic to reduce allocations\nint x;\n")
    assert found and found[0].severity == Severity.WARN


def test_uc003_now_uses_is_caught():
    found = _uc003("// Now uses memcpy instead of memmove\nint x;\n")
    assert found and found[0].severity == Severity.WARN


def test_uc003_fixed_point_not_flagged():
    assert not _uc003("// Fixed-point arithmetic: angles are stored as 16.16 values.\nint x;\n")


def test_uc003_runtime_description_not_flagged():
    assert not _uc003("// Moved to the free list when the refcount reaches zero.\nint x;\n")
    assert not _uc003("// Fixed header size of 12 bytes precedes the payload.\nint x;\n")


def test_uc003_switched_from_is_caught():
    found = _uc003("// Switched from strcpy to memcpy for the bounds fix\nint x;\n")
    assert found

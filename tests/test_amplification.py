"""UC101 comment amplification: an agent that sees existing comments and
answers with more comments is caught on volume, even when each individual
comment evades the per-comment rules."""

from __future__ import annotations

from pathlib import Path

from uncomment.config import Config
from uncomment.gate import gate_file

OLD = (
    "// The parser keeps one token of lookahead.\n"
    "// Backtracking is deliberately unsupported.\n"
    "export function parse(src) {\n"
    "  return src.trim();\n"
    "}\n"
)

# six clean-worded elaboration comments: none trips a per-comment rule
NEW = (
    "// The parser keeps one token of lookahead.\n"
    "// Backtracking is deliberately unsupported.\n"
    "// The lookahead token lives in a single field.\n"
    "// Whitespace at both ends carries no meaning for the grammar.\n"
    "// The grammar treats interior whitespace as significant.\n"
    "// Trimming happens once per call, never lazily.\n"
    "// Callers rely on the trimmed shape of the value.\n"
    "// The trimmed value keeps its original casing.\n"
    "export function parse(src) {\n"
    "  return src.trim();\n"
    "}\n"
)


def _dirs(tmp_path, old_text, new_text):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "a.js").write_text(old_text, encoding="utf-8")
    (new / "a.js").write_text(new_text, encoding="utf-8")
    return old, new


def test_elaboration_spree_fires_uc101(tmp_path):
    old, new = _dirs(tmp_path, OLD, NEW)
    findings, _, stats = gate_file(new / "a.js", str(old), new, Config())
    # the six added lines merge with the two existing ones into one grown
    # logical comment — which is the point: the block was amplified
    assert stats["new_comment_lines"] == 8
    uc101 = [f for f in findings if f.rule == "UC101"]
    assert uc101, [f.rule for f in findings]
    assert "8 new prose comment lines in a file that had 2" in uc101[0].message
    # volume alone must not also count as flood noise
    assert not any(f.rule == "UC100" for f in findings)


def test_few_new_comments_do_not_amplify(tmp_path):
    new_text = OLD.replace(
        "export function",
        "// Trimming happens once per call, never lazily.\nexport function",
    )
    old, new = _dirs(tmp_path, OLD, new_text)
    findings, _, _ = gate_file(new / "a.js", str(old), new, Config())
    assert not any(f.rule == "UC101" for f in findings)


def test_uncommented_file_gets_no_amplification(tmp_path):
    old_text = "export function parse(src) {\n  return src.trim();\n}\n"
    old, new = _dirs(tmp_path, old_text, NEW)
    findings, _, _ = gate_file(new / "a.js", str(old), new, Config())
    # old file had no prose comments: this is flood territory, not contagion
    assert not any(f.rule == "UC101" for f in findings)


def test_new_docs_do_not_amplify(tmp_path):
    doc = "/**\n * Parses one directive line.\n * @param src raw input\n * @returns trimmed value\n */\n"
    new_text = OLD.replace("export function", doc + "export function")
    old, new = _dirs(tmp_path, OLD, new_text)
    findings, _, _ = gate_file(new / "a.js", str(old), new, Config())
    assert not any(f.rule == "UC101" for f in findings)

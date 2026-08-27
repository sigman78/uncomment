"""CLI behavior: exit codes, output formats, rule filtering."""

from __future__ import annotations

import json
from pathlib import Path

from uncomment.cli import main

CORPUS = Path(__file__).parent / "corpus"
NOISY_C = str(CORPUS / "c" / "agent_noise.c")
CLEAN_C = str(CORPUS / "c" / "clean.c")


def test_check_clean_exits_zero(capsys):
    assert main(["check", CLEAN_C]) == 0


def test_check_noisy_exits_one(capsys):
    assert main(["check", NOISY_C]) == 1


def test_fail_on_never(capsys):
    assert main(["check", NOISY_C, "--fail-on", "never"]) == 0


def test_fail_on_error_ignores_warnings(capsys):
    # clean file has no errors; noisy file has a UC003 error
    assert main(["check", CLEAN_C, "--fail-on", "error"]) == 0
    assert main(["check", NOISY_C, "--fail-on", "error"]) == 1


def test_json_format_schema(capsys):
    main(["check", NOISY_C, "--fail-on", "never", "--format", "json"])
    doc = json.loads(capsys.readouterr().out)
    assert doc["tool"] == "uncomment"
    assert doc["schema_version"] == 1
    assert doc["summary"]["error"] >= 1
    assert all({"rule", "severity", "path", "line", "message", "action"} <= set(f) for f in doc["findings"])


def test_agent_format_mentions_must_fix(capsys):
    main(["check", NOISY_C, "--fail-on", "never", "--format", "agent"])
    out = capsys.readouterr().out
    assert "MUST FIX" in out
    assert "Comment review feedback" in out


def test_agent_format_clean(capsys):
    main(["check", CLEAN_C, "--fail-on", "never", "--format", "agent"])
    assert "No action needed" in capsys.readouterr().out


def test_disable_rules(capsys):
    main(["check", NOISY_C, "--fail-on", "never", "--format", "json", "--disable", "STE,UC011"])
    doc = json.loads(capsys.readouterr().out)
    rules = {f["rule"] for f in doc["findings"]}
    assert not any(r.startswith("STE") for r in rules)
    assert "UC011" not in rules


def test_gate_cli(tmp_path, capsys):
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    (old_dir / "a.js").write_text("const a = 1;\n", encoding="utf-8")
    (new_dir / "a.js").write_text("// Updated the constant as requested\nconst a = 2;\n", encoding="utf-8")
    code = main(["gate", str(new_dir), "--baseline", str(old_dir), "--format", "json"])
    doc = json.loads(capsys.readouterr().out)
    assert code == 1
    assert doc["stats"]["mode"] == "gate"
    assert any(f["rule"] == "UC003" for f in doc["findings"])


def test_rules_listing(capsys):
    assert main(["rules"]) == 0
    out = capsys.readouterr().out
    assert "UC001" in out and "STE03" in out

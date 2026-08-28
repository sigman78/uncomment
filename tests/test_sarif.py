"""SARIF 2.1.0 output for code-scanning integrations."""

from __future__ import annotations

import json
from pathlib import Path

from unwaffle.cli import main

CORPUS = Path(__file__).parent / "corpus"
NOISY_C = str(CORPUS / "c" / "agent_noise.c")


def _run_sarif(capsys, args: list[str]) -> dict:
    main(args + ["--fail-on", "never", "--format", "sarif"])
    return json.loads(capsys.readouterr().out)


def test_sarif_structure_and_levels(capsys):
    doc = _run_sarif(capsys, ["check", NOISY_C])
    assert doc["version"] == "2.1.0"
    run = doc["runs"][0]
    driver = run["tool"]["driver"]
    assert driver["name"] == "unwaffle"
    assert driver["version"]
    rule_ids = [r["id"] for r in driver["rules"]]
    assert rule_ids == sorted(set(rule_ids))
    results = run["results"]
    assert results
    for res in results:
        assert rule_ids[res["ruleIndex"]] == res["ruleId"]
        assert res["level"] in ("error", "warning", "note")
        loc = res["locations"][0]["physicalLocation"]
        assert "\\" not in loc["artifactLocation"]["uri"]
        assert loc["region"]["startLine"] >= 1
        assert res["message"]["text"]
    # the noisy corpus contains a UC003 edit-narration error
    assert any(r["ruleId"] == "UC003" and r["level"] == "error" for r in results)


def test_sarif_relative_uri(capsys, monkeypatch):
    monkeypatch.chdir(CORPUS.parent)
    doc = _run_sarif(capsys, ["check", "corpus/c/agent_noise.c"])
    uris = {
        r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        for r in doc["runs"][0]["results"]
    }
    assert uris == {"corpus/c/agent_noise.c"}


def test_sarif_rule_metadata(capsys):
    doc = _run_sarif(capsys, ["check", NOISY_C])
    rules = {r["id"]: r for r in doc["runs"][0]["tool"]["driver"]["rules"]}
    assert rules["UC003"]["defaultConfiguration"]["level"] == "error"
    assert rules["UC003"]["shortDescription"]["text"]


def test_sarif_gate_only_rules(tmp_path, capsys):
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    (old_dir / "a.js").write_text("export function f() {\n  return 1;\n}\n", encoding="utf-8")
    noise = "".join(f"// then we run filler step number {i} of the plan\n" for i in range(14))
    (new_dir / "a.js").write_text(noise + "export function f() {\n  return 1;\n}\n", encoding="utf-8")
    doc = _run_sarif(capsys, ["gate", str(new_dir), "--baseline", str(old_dir)])
    run = doc["runs"][0]
    assert any(r["ruleId"] == "UC100" and r["level"] == "error" for r in run["results"])
    rules = {r["id"]: r for r in run["tool"]["driver"]["rules"]}
    assert "flood" in rules["UC100"]["shortDescription"]["text"]


def test_sarif_no_findings(tmp_path, capsys):
    clean = tmp_path / "clean.js"
    clean.write_text("export const a = 1;\n", encoding="utf-8")
    doc = _run_sarif(capsys, ["check", str(clean)])
    run = doc["runs"][0]
    assert run["results"] == []
    assert run["tool"]["driver"]["rules"] == []

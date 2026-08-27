"""Corpus harness: every rule change must keep these assertions green.

- agent_noise.* files carry a sidecar .expected.json:
    findings: EXACT set of (rule, line) at warn/error severity — any missing
              finding is a recall regression, any extra one is new noise.
    hints:    (rule, line) pairs that MUST be present at info severity;
              additional info findings are allowed.
- clean.* files must produce zero findings of any severity (false-positive guard).
- Every rule in the registry must be exercised by at least one corpus file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from uncomment.config import Config
from uncomment.extract import extract_file
from uncomment.languages import EXTENSIONS
from uncomment.model import Severity
from uncomment.rules import all_rules, run_rules

CORPUS = Path(__file__).parent / "corpus"

SOURCES = sorted(p for p in CORPUS.rglob("*") if p.suffix.lower() in EXTENSIONS)
NOISY = [p for p in SOURCES if p.name.startswith("agent_noise")]
CLEAN = [p for p in SOURCES if p.name.startswith("clean")]


def _findings_for(path: Path):
    sf = extract_file(path)
    assert sf is not None, f"unsupported corpus file {path}"
    return run_rules(sf, Config())


@pytest.mark.parametrize("path", NOISY, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_noisy_file_matches_expectations(path: Path):
    expected = json.loads(path.with_name(path.name + ".expected.json").read_text())
    findings = _findings_for(path)

    actual_gating = {(f.rule, f.line) for f in findings if f.severity >= Severity.WARN}
    expected_gating = {(rule, line) for rule, line in expected["findings"]}
    missing = expected_gating - actual_gating
    extra = actual_gating - expected_gating
    assert not missing, f"recall regression, findings disappeared: {sorted(missing)}"
    assert not extra, f"new noise, unexpected findings: {sorted(extra)}"

    actual_hints = {(f.rule, f.line) for f in findings if f.severity == Severity.INFO}
    expected_hints = {(rule, line) for rule, line in expected.get("hints", [])}
    missing_hints = expected_hints - actual_hints
    assert not missing_hints, f"expected hints disappeared: {sorted(missing_hints)}"


@pytest.mark.parametrize("path", CLEAN, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_clean_file_has_no_findings(path: Path):
    findings = _findings_for(path)
    details = [(f.rule, f.line, f.message) for f in findings]
    assert not findings, f"false positives on clean code: {details}"


def test_every_language_has_corpus():
    languages = {p.parent.name for p in NOISY}
    assert languages == {"c", "cpp", "js", "ts", "rust", "go"}
    assert {p.parent.name for p in CLEAN} == languages


def test_every_rule_is_exercised():
    exercised: set[str] = set()
    for path in NOISY:
        expected = json.loads(path.with_name(path.name + ".expected.json").read_text())
        exercised |= {rule for rule, _ in expected["findings"]}
        exercised |= {rule for rule, _ in expected.get("hints", [])}
    registered = {r.id for r in all_rules()}
    uncovered = registered - exercised
    assert not uncovered, f"rules with no corpus coverage: {sorted(uncovered)}"

"""Agent-format terseness: grouped actions, conditional policy, house rules."""

from __future__ import annotations

import pytest

from uncomment.cli import main
from uncomment.config import Config, load_config
from uncomment.extract import extract_source
from uncomment.languages import JS
from uncomment.model import ToolError
from uncomment.report import render_agent
from uncomment.rules import run_rules


def _agent(src: str, cfg: Config | None = None) -> str:
    cfg = cfg or Config()
    findings = run_rules(extract_source("t.js", src, JS), cfg)
    return render_agent(findings, {"files_scanned": 1}, cfg)


NARRATION_ONLY = "".join(
    f"// then we run filler step number {i} of the plan\nconst v{i} = {i};\n" for i in range(8)
)


def test_repeated_rule_prints_action_once():
    out = _agent(NARRATION_ONLY)
    assert out.count("Do not tell a story") == 1  # the UC002 action, 8 sites
    assert out.count("**L") == 8
    assert "×8" in out


def test_policy_lists_only_fired_families():
    out = _agent(NARRATION_ONLY)  # fires UC002 alone
    assert "Do not narrate your process" in out
    # the UC005 and UC003 points must be absent
    assert "commented-out code" not in out
    assert "Never describe the edit" not in out
    # both guardrails hold in every report
    assert "never strip real docs" in out
    assert "delete only the comment" in out


def test_output_stays_bounded_as_findings_repeat():
    small = _agent("".join(f"// then we run filler step number {i} of the plan\nconst a{i} = 1;\n" for i in range(2)))
    big = _agent(NARRATION_ONLY)
    # 4x the findings must cost far less than 4x the bytes: only the
    # one-line site entries may grow
    assert len(big) - len(small) < 6 * 80


def test_house_policy_lines_are_injected():
    cfg = Config(agent_policy=["Long design prose goes to docs/architecture.md."])
    out = _agent(NARRATION_ONLY, cfg)
    assert "docs/architecture.md" in out
    # injected after the built-ins, still numbered
    assert out.index("never strip real docs") < out.index("docs/architecture.md")


def test_house_policy_from_toml(tmp_path, capsys):
    (tmp_path / "a.js").write_text("// then we check the input\nconst a = 1;\n", encoding="utf-8")
    (tmp_path / "uncomment.toml").write_text(
        'agent-policy = ["House rule: comments are English-only."]\n', encoding="utf-8"
    )
    main(["check", str(tmp_path / "a.js"), "--fail-on", "never", "--format", "agent"])
    assert "English-only" in capsys.readouterr().out


def test_empty_policy_line_is_a_config_error(tmp_path):
    (tmp_path / "uncomment.toml").write_text('agent-policy = [" "]\n', encoding="utf-8")
    with pytest.raises(ToolError, match="agent-policy: empty line"):
        load_config(tmp_path)

"""approved-terms: project vocabulary the wording rules must not judge."""

from __future__ import annotations

import pytest

from uncomment.cli import main
from uncomment.config import Config
from uncomment.extract import extract_source
from uncomment.languages import JS
from uncomment.model import ToolError
from uncomment.rules import run_rules, wording_text


def _fired(src: str, cfg: Config | None = None) -> set[str]:
    return {f.rule for f in run_rules(extract_source("t.js", src, JS), cfg or Config())}


def test_wording_text_masks_terms():
    cfg = Config(approved_terms=["Let's Encrypt", "leverage"])
    assert wording_text("Let's Encrypt limits leverage here", cfg) == " limits  here"
    assert wording_text("no terms here", cfg) == "no terms here"


def test_uc002_opener_term_is_spared():
    src = "// Then Labs ships the SDK for the kiosk.\nexport const sdk = 1;\n"
    assert "UC002" in _fired(src)
    assert "UC002" not in _fired(src, Config(approved_terms=["Then Labs"]))


def test_uc003_opener_term_is_spared():
    src = "// Fixed Income books settle on the next day.\nexport const t = 1;\n"
    assert "UC003" in _fired(src)
    assert "UC003" not in _fired(src, Config(approved_terms=["Fixed Income"]))


def test_uppercase_term_matches_exact_case_only():
    # the lowercase phrase is real narration and must stay flagged even when
    # the capitalized product name is approved
    src = "function f() {\n  // fixed income handling for the desk\n  return 1;\n}\n"
    assert "UC003" in _fired(src, Config(approved_terms=["Fixed Income"]))


def test_lowercase_term_matches_any_case():
    cfg = Config(approved_terms=["leverage"])
    for word in ("leverage", "Leverage"):
        src = f"// {word} the cache for repeated lookups.\nexport const c = 1;\n"
        assert "STE03" in _fired(src)
        assert "STE03" not in _fired(src, cfg)


def test_masking_does_not_hide_other_wording_problems():
    src = "// Fixed Income books are stored nightly by the batch job.\nexport const b = 1;\n"
    assert "STE02" in _fired(src, Config(approved_terms=["Fixed Income"]))


def test_overlap_rules_still_see_term_words():
    # approving a term must not weaken restatement detection
    src = "function f() {\n  // Fixed Income rate\n  fixed_income_rate = load();\n}\n"
    assert "UC001" in _fired(src, Config(approved_terms=["Fixed Income"]))


def test_partial_word_never_matches():
    cfg = Config(approved_terms=["leverage"])
    assert wording_text("leverages cleverage", cfg) == "leverages cleverage"


def test_empty_term_is_a_config_error(tmp_path):
    from uncomment.config import load_config

    cfg_file = tmp_path / "uncomment.toml"
    cfg_file.write_text('approved-terms = ["ok", " "]\n', encoding="utf-8")
    with pytest.raises(ToolError, match="empty term"):
        load_config(tmp_path)


def test_toml_config_end_to_end(tmp_path, capsys):
    (tmp_path / "a.js").write_text(
        "// Fixed Income books settle on the next day.\nexport const t = 1;\n", encoding="utf-8"
    )
    assert main(["check", str(tmp_path / "a.js")]) == 1
    capsys.readouterr()
    (tmp_path / "uncomment.toml").write_text('approved-terms = ["Fixed Income"]\n', encoding="utf-8")
    assert main(["check", str(tmp_path / "a.js")]) == 0

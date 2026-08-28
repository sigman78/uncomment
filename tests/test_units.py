"""Unit tests for the sensitivity knobs: stemming, identifier splitting,
overlap scoring, and config discovery order."""

from __future__ import annotations

from unwaffle.config import load_config
from unwaffle.textutil import overlap_ratio, sentences, split_identifier, stem


# stemming: both sides of a comparison must agree

def test_stem_verb_and_identifier_agree():
    assert stem("frobnicates") == stem("frobnicate")
    assert stem("copies") == stem("copy")
    assert stem("uses") == stem("use")
    assert stem("running") == stem("runs")


def test_split_identifier():
    assert split_identifier("getUserName") == ["get", "user", "name"]
    assert split_identifier("user_name") == ["user", "name"]
    assert split_identifier("HTTPServer") == ["http", "server"]
    assert split_identifier("v2_parser") == ["v", "parser"]


def test_overlap_ignores_stopwords():
    assert overlap_ratio("return the result", "return result;") == 1.0
    assert overlap_ratio("a wholly unrelated remark", "return result;") == 0.0


def test_sentences_split():
    assert sentences("One. Two! Three?") == ["One.", "Two!", "Three?"]
    assert sentences("") == []


# config discovery order

def _write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_unwaffle_toml_beats_pyproject(tmp_path):
    _write(tmp_path / "unwaffle.toml", 'disable = ["STE"]\n')
    _write(tmp_path / "pyproject.toml", '[tool.unwaffle]\ndisable = ["UC011"]\n')
    assert load_config(tmp_path).disable == ["STE"]


def test_nearest_directory_wins(tmp_path):
    _write(tmp_path / "unwaffle.toml", 'disable = ["STE"]\n')
    inner = tmp_path / "pkg" / "sub"
    _write(inner / "unwaffle.toml", 'disable = ["UC011"]\n')
    assert load_config(inner).disable == ["UC011"]
    assert load_config(tmp_path / "pkg").disable == ["STE"]


def test_explicit_config_beats_discovery(tmp_path):
    _write(tmp_path / "unwaffle.toml", 'disable = ["STE"]\n')
    explicit = tmp_path / "special.toml"
    _write(explicit, 'disable = ["UC004"]\n')
    assert load_config(tmp_path, explicit=str(explicit)).disable == ["UC004"]


def test_pyproject_without_table_falls_through(tmp_path):
    _write(tmp_path / "pkg" / "pyproject.toml", '[project]\nname = "x"\n')
    _write(tmp_path / "unwaffle.toml", 'disable = ["STE"]\n')
    assert load_config(tmp_path / "pkg").disable == ["STE"]

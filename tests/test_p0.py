"""P0 reliability fixes: failure modes must be loud, output must survive any
console, and Unicode/emoji policy is configurable on both sides."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from uncomment.cli import discover_files, main
from uncomment.config import Config, load_config, parse_disable_arg
from uncomment.extract import extract_source
from uncomment.languages import C, JS
from uncomment.model import ToolError
from uncomment.report import to_ascii
from uncomment.rules import run_rules

NOISY = "// utilize the buffer in order to facilitate reads\nint x;\n"


# ---- path validation ----

def test_nonexistent_path_exits_2(capsys):
    assert main(["check", "does_not_exist.c"]) == 2
    assert "does not exist" in capsys.readouterr().err


def test_unsupported_explicit_file_is_reported(tmp_path, capsys):
    p = tmp_path / "script.py"
    p.write_text("# python\n", encoding="utf-8")
    assert main(["check", str(p)]) == 0
    captured = capsys.readouterr()
    assert "unsupported" in captured.err
    assert '"files_skipped"' not in captured.out  # text format


def test_duplicate_paths_scan_once(tmp_path, capsys):
    f = tmp_path / "a.c"
    f.write_text("int x;\n", encoding="utf-8")
    assert main(["check", str(tmp_path), str(f), "--format", "json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["stats"]["files_scanned"] == 1


def test_skip_dirs_apply_only_below_scan_root(tmp_path):
    project = tmp_path / "build" / "myproj"      # checkout lives under "build"
    (project / "node_modules").mkdir(parents=True)
    (project / "a.c").write_text("int x;\n", encoding="utf-8")
    (project / "node_modules" / "b.c").write_text("int y;\n", encoding="utf-8")
    found = [p.name for p in discover_files([project])]
    assert found == ["a.c"]


# ---- baseline validation ----

def test_bad_git_ref_exits_2(tmp_path, capsys):
    f = tmp_path / "a.c"
    f.write_text(NOISY, encoding="utf-8")
    assert main(["gate", str(f), "--baseline", "git:no-such-ref"]) == 2
    assert "baseline ref" in capsys.readouterr().err


def test_missing_baseline_dir_exits_2(tmp_path, capsys):
    f = tmp_path / "a.c"
    f.write_text(NOISY, encoding="utf-8")
    assert main(["gate", str(f), "--baseline", str(tmp_path / "absent")]) == 2
    assert "baseline path" in capsys.readouterr().err


# ---- config validation ----

def _cfg_file(tmp_path, text: str) -> str:
    p = tmp_path / "cfg.toml"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_unknown_config_key_is_an_error(tmp_path):
    with pytest.raises(ToolError, match="unknown key"):
        load_config(explicit=_cfg_file(tmp_path, 'restate-overlp = 0.1\n'))


def test_wrong_config_type_is_an_error(tmp_path):
    with pytest.raises(ToolError, match="expected float"):
        load_config(explicit=_cfg_file(tmp_path, 'restate-overlap = "0.6"\n'))


def test_invalid_severity_value_is_an_error(tmp_path):
    with pytest.raises(ToolError, match="info/warn/error"):
        load_config(explicit=_cfg_file(tmp_path, '[severity]\nUC003 = "warning"\n'))


def test_invalid_directive_regex_is_an_error(tmp_path):
    with pytest.raises(ToolError, match="invalid regex"):
        load_config(explicit=_cfg_file(tmp_path, 'directive-patterns = ["["]\n'))


def test_invalid_toml_names_the_file(tmp_path):
    with pytest.raises(ToolError, match="invalid TOML"):
        load_config(explicit=_cfg_file(tmp_path, "[broken\n"))


def test_config_errors_exit_2_via_cli(tmp_path, capsys):
    f = tmp_path / "a.c"
    f.write_text("int x;\n", encoding="utf-8")
    bad = _cfg_file(tmp_path, "restate-overlp = 0.1\n")
    assert main(["check", str(f), "--config", bad]) == 2
    assert "unknown key" in capsys.readouterr().err


def test_tool_uncomment_table_works_in_uncomment_toml(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "uncomment.toml").write_text(
        '[tool.uncomment]\ndisable = ["STE"]\n', encoding="utf-8"
    )
    cfg = load_config(proj)
    assert cfg.disable == ["STE"]
    # bare keys keep working too
    (proj / "uncomment.toml").write_text('disable = ["UC011"]\n', encoding="utf-8")
    assert load_config(proj).disable == ["UC011"]


def test_disable_arg_rejects_empty_and_bogus_entries():
    with pytest.raises(ToolError):
        parse_disable_arg("UC001,")
    with pytest.raises(ToolError):
        parse_disable_arg("BOGUS")
    assert parse_disable_arg("STE,UC011") == ["STE", "UC011"]


# ---- version / output encoding ----

def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "uncomment 0.2.0" in capsys.readouterr().out


def test_ascii_output_flag(tmp_path, capsys):
    f = tmp_path / "a.c"
    f.write_text(NOISY, encoding="utf-8")
    main(["check", str(f), "--fail-on", "never", "--ascii"])
    out = capsys.readouterr().out
    assert "->" in out          # STE03's arrow, transliterated
    assert "→" not in out
    assert out.isascii()


def test_to_ascii_transliteration():
    assert to_ascii("'utilize' → use…") == "'utilize' -> use..."


# ---- UC012 emoji / ascii-comments ----

def test_emoji_comment_flagged():
    src = "// \U0001f680 fast path for small arrays ⚡\nconst x = 1;\n"
    sf = extract_source("t.js", src, JS)
    rules = {f.rule for f in run_rules(sf, Config())}
    assert "UC012" in rules


def test_accented_prose_allowed_by_default_flagged_in_strict():
    src = "// café latency is measured in µs\nint x;\n"
    sf = extract_source("t.c", src, C)
    assert "UC012" not in {f.rule for f in run_rules(sf, Config())}
    assert "UC012" in {f.rule for f in run_rules(sf, Config(ascii_comments=True))}


def test_unicode_output_config(tmp_path, capsys):
    f = tmp_path / "a.c"
    f.write_text(NOISY, encoding="utf-8")
    cfg = _cfg_file(tmp_path, "unicode-output = false\n")
    main(["check", str(f), "--fail-on", "never", "--config", cfg])
    assert capsys.readouterr().out.isascii()

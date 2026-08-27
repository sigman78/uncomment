"""Diff input: the unified diff itself is the baseline (`gate --diff`)."""

from __future__ import annotations

import difflib
import io
import json
import sys
from pathlib import Path

import pytest

from uncomment.cli import main
from uncomment.config import Config
from uncomment.diffio import parse_diff, reverse_apply
from uncomment.gate import gate_diff
from uncomment.model import ToolError

OLD = """\
// Debounce keeps the request count low.
export function debounce(fn, delay = 250) {
  let timer = null;
  return () => fn();
}
"""

NEW = """\
// Debounce keeps the request count low.
export function debounce(fn, delay = 250) {
  // Changed the timer handling as requested
  let timer = null;
  // Then we return the wrapped callback
  return () => fn();
}
"""

GIT_DIFF = """\
diff --git a/x.js b/y.js
similarity index 90%
rename from x.js
rename to y.js
index 1111111..2222222 100644
--- a/x.js
+++ b/y.js
@@ -1,2 +1,2 @@
-const a = 1;
+const a = 2;
 const b = 3;
diff --git a/gone.js b/gone.js
deleted file mode 100644
index 3333333..0000000
--- a/gone.js
+++ /dev/null
@@ -1 +0,0 @@
-const gone = 1;
diff --git a/img.png b/img.png
index 4444444..5555555 100644
Binary files a/img.png and b/img.png differ
"""


def _udiff(old: str, new: str, name: str, n: int = 3) -> str:
    lines = difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=f"a/{name}", tofile=f"b/{name}", lineterm="", n=n,
    )
    return "\n".join(lines) + "\n"


def test_parse_git_diff_sections():
    patches = parse_diff(GIT_DIFF)
    assert len(patches) == 3
    renamed, deleted, binary = patches
    assert (renamed.old_path, renamed.new_path) == ("x.js", "y.js")
    assert renamed.hunks[0].old_lines == ["const a = 1;", "const b = 3;"]
    assert renamed.hunks[0].new_lines == ["const a = 2;", "const b = 3;"]
    assert deleted.new_path is None
    assert binary.binary


def test_parse_mnemonic_prefixes_and_quoted_paths():
    diff = (
        "diff --git i/a.js w/a.js\n"       # diff.mnemonicPrefix = true
        "index 1111111..2222222 100644\n"
        "--- i/a.js\n"
        "+++ w/a.js\n"
        "@@ -1 +1 @@\n"
        "-const a = 1;\n"
        "+const a = 2;\n"
        'diff --git "a/sp ace.js" "b/sp ace.js"\n'
        '--- "a/sp ace.js"\n'
        '+++ "b/sp ace.js"\n'
        "@@ -1 +1 @@\n"
        "-const b = 1;\n"
        "+const b = 2;\n"
    )
    plain, quoted = parse_diff(diff)
    assert (plain.old_path, plain.new_path) == ("a.js", "a.js")
    assert (quoted.old_path, quoted.new_path) == ("sp ace.js", "sp ace.js")


def test_garbage_input_is_an_error():
    with pytest.raises(ToolError):
        parse_diff("this is not a diff\njust some text\n")


def test_empty_diff_is_empty():
    assert parse_diff("") == []


@pytest.mark.parametrize("context", [3, 0])
def test_reverse_apply_roundtrip(context):
    patch = parse_diff(_udiff(OLD, NEW, "a.js", n=context))[0]
    old_lines = reverse_apply(patch, NEW.splitlines(), "a.js")
    assert old_lines == OLD.splitlines()


def test_reverse_apply_stale_diff_fails():
    patch = parse_diff(_udiff(OLD, NEW, "a.js"))[0]
    tampered = NEW.replace("timer = null", "timer = undefined").splitlines()
    with pytest.raises(ToolError, match="does not match"):
        reverse_apply(patch, tampered, "a.js")


def test_gate_diff_judges_only_added_comments(tmp_path):
    (tmp_path / "a.js").write_text(NEW, encoding="utf-8")
    result = gate_diff(_udiff(OLD, NEW, "a.js"), Config(), root=tmp_path)
    rules = {f.rule for f in result.findings}
    assert "UC003" in rules and "UC002" in rules
    assert all(f.line != 1 for f in result.findings)  # pre-existing comment untouched
    assert result.new_comments == 2


def test_gate_diff_moved_comment_is_not_new(tmp_path):
    old = "// Keeps latency low on slow disks.\nconst a = 1;\n"
    new = "const a = 1;\n// Keeps latency low on slow disks.\nconst b = 2;\n"
    (tmp_path / "a.js").write_text(new, encoding="utf-8")
    result = gate_diff(_udiff(old, new, "a.js"), Config(), root=tmp_path)
    assert result.new_comments == 0
    assert result.findings == []


def test_gate_diff_new_file_all_comments_new(tmp_path):
    (tmp_path / "fresh.js").write_text(NEW, encoding="utf-8")
    diff = "--- /dev/null\n+++ b/fresh.js\n@@ -0,0 +1,7 @@\n" + "".join(
        f"+{line}\n" for line in NEW.splitlines()
    )
    result = gate_diff(diff, Config(), root=tmp_path)
    assert result.new_comments == 3
    assert any(f.rule == "UC003" for f in result.findings)


def test_gate_diff_skips_deleted_and_unsupported(tmp_path):
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    diff = (
        _udiff("x\n", "hello\n", "notes.txt")
        + "--- a/gone.js\n+++ /dev/null\n@@ -1 +0,0 @@\n-const gone = 1;\n"
    )
    result = gate_diff(diff, Config(), root=tmp_path)
    assert result.files_scanned == 0
    assert result.files_skipped == 1  # notes.txt: unsupported language


def test_gate_diff_restrict_paths(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (tmp_path / "a.js").write_text(NEW, encoding="utf-8")
    (sub / "b.js").write_text(NEW, encoding="utf-8")
    diff = _udiff(OLD, NEW, "a.js") + _udiff(OLD, NEW, "sub/b.js")
    result = gate_diff(diff, Config(), restrict=[sub], root=tmp_path)
    assert result.files_scanned == 1
    assert all("b.js" in str(f.path) for f in result.findings)


def test_gate_diff_missing_file_is_loud(tmp_path):
    with pytest.raises(ToolError, match="not found on disk"):
        gate_diff(_udiff(OLD, NEW, "absent.js"), Config(), root=tmp_path)


def test_cli_diff_file(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.js").write_text(NEW, encoding="utf-8")
    (tmp_path / "edit.diff").write_text(_udiff(OLD, NEW, "a.js"), encoding="utf-8")
    code = main(["gate", "--diff", "edit.diff", "--format", "json"])
    doc = json.loads(capsys.readouterr().out)
    assert code == 1
    assert doc["stats"]["baseline"] == "diff:edit.diff"
    assert any(f["rule"] == "UC003" for f in doc["findings"])


def test_cli_diff_stdin(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.js").write_text(NEW, encoding="utf-8")

    class _Stdin:
        buffer = io.BytesIO(_udiff(OLD, NEW, "a.js").encode("utf-8"))

    monkeypatch.setattr(sys, "stdin", _Stdin())
    code = main(["gate", "--diff", "-", "--format", "json"])
    doc = json.loads(capsys.readouterr().out)
    assert code == 1
    assert doc["stats"]["baseline"] == "diff:stdin"


def test_cli_diff_empty_stdin_passes(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)

    class _Stdin:
        buffer = io.BytesIO(b"")

    monkeypatch.setattr(sys, "stdin", _Stdin())
    assert main(["gate", "--diff", "-"]) == 0


def test_cli_diff_stale_diff_exits_two(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.js").write_text(NEW.replace("timer = null", "timer = undefined"), encoding="utf-8")
    (tmp_path / "edit.diff").write_text(_udiff(OLD, NEW, "a.js"), encoding="utf-8")
    assert main(["gate", "--diff", "edit.diff"]) == 2
    assert "does not match" in capsys.readouterr().err


def test_cli_diff_and_baseline_conflict(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["gate", "--diff", "-", "--baseline", "git:HEAD"]) == 2
    assert main(["gate", str(tmp_path)]) == 2  # neither --diff nor --baseline
    err = capsys.readouterr().err
    assert "mutually exclusive" in err
    assert "needs --baseline" in err


def test_cli_diff_missing_diff_file(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["gate", "--diff", "absent.diff"]) == 2
    assert "diff file does not exist" in capsys.readouterr().err


def test_gate_diff_resolves_from_repo_top(tmp_path, monkeypatch):
    """git prints repo-top-relative paths; gating from a subdirectory must
    still find the files."""
    import shutil
    import subprocess

    if shutil.which("git") is None:
        pytest.skip("git not available")
    repo = tmp_path / "repo"
    sub = repo / "sub"
    sub.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    (repo / "a.js").write_text(NEW, encoding="utf-8")
    result = gate_diff(_udiff(OLD, NEW, "a.js"), Config(), root=sub)
    assert result.files_scanned == 1
    assert result.new_comments == 2

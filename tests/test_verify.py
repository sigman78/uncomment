"""`uncomment verify --diff`: prove a diff touches comments only — the
safety bound for autonomous comment-fixer loops."""

from __future__ import annotations

import difflib
import io
import sys
from pathlib import Path

from uncomment.cli import main
from uncomment.gate import verify_comments_only


def _udiff(old: str, new: str, name: str) -> str:
    lines = difflib.unified_diff(
        old.splitlines(), new.splitlines(), fromfile=f"a/{name}", tofile=f"b/{name}", lineterm=""
    )
    return "\n".join(lines) + "\n"


def _write(tmp_path: Path, name: str, text: str) -> None:
    (tmp_path / name).write_text(text, encoding="utf-8")


CODE = "export function f(x) {\n  return x + 1;\n}\n"


def test_comment_reword_and_delete_pass(tmp_path):
    old = "// the old wording of the note\n" + CODE + "// a comment that gets deleted\nconst a = 1;\n"
    new = "// reworded: retries twice because the registry drops one\n" + CODE + "const a = 1;\n"
    _write(tmp_path, "a.js", new)
    assert verify_comments_only(_udiff(old, new, "a.js"), root=tmp_path) == []


def test_trailing_comment_edit_passes(tmp_path):
    old = "const t = 250; // tuned by hand\n"
    new = "const t = 250; // tuned against the staging registry\n"
    _write(tmp_path, "a.js", new)
    assert verify_comments_only(_udiff(old, new, "a.js"), root=tmp_path) == []


def test_python_docstring_edit_passes(tmp_path):
    old = 'def f():\n    """Old doc."""\n    return 1\n'
    new = 'def f():\n    """Returns one; the registry counts from one."""\n    return 1\n'
    _write(tmp_path, "a.py", new)
    assert verify_comments_only(_udiff(old, new, "a.py"), root=tmp_path) == []


def test_code_change_is_caught(tmp_path):
    old = "// note\n" + CODE
    new = "// note\n" + CODE.replace("x + 1", "x + 2")
    _write(tmp_path, "a.js", new)
    problems = verify_comments_only(_udiff(old, new, "a.js"), root=tmp_path)
    assert problems and "x + 2" in problems[0][1]


def test_mixed_change_is_caught(tmp_path):
    old = "// old note\n" + CODE
    new = "// new wording of the note\n" + CODE.replace("f(x)", "f(x, y)")
    _write(tmp_path, "a.js", new)
    assert verify_comments_only(_udiff(old, new, "a.js"), root=tmp_path)


def test_indentation_change_is_code(tmp_path):
    # indentation is semantic in python: not a comment-only change
    old = "if a:\n    b()\n    c()\n"
    new = "if a:\n    b()\nc()\n"
    _write(tmp_path, "a.py", new)
    assert verify_comments_only(_udiff(old, new, "a.py"), root=tmp_path)


def test_unsupported_and_deleted_are_conservative(tmp_path):
    _write(tmp_path, "s.svelte", "<script>let a = 2;</script>\n")
    diff = _udiff("<script>let a = 1;</script>\n", "<script>let a = 2;</script>\n", "s.svelte")
    diff += "--- a/gone.js\n+++ /dev/null\n@@ -1 +0,0 @@\n-const gone = 1;\n"
    problems = verify_comments_only(diff, root=tmp_path)
    details = {p: d for p, d in problems}
    assert "unsupported" in details["s.svelte"]
    assert details["gone.js"] == "file deleted"


def test_pathless_verify_runs_git_itself(tmp_path, capsys, monkeypatch):
    import shutil
    import subprocess

    import pytest

    if shutil.which("git") is None:
        pytest.skip("git not available")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    (repo / "a.js").write_text("// old note\nconst a = 1;\n", encoding="utf-8")
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "a.js"],
        cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "base"],
        cwd=repo, check=True, capture_output=True,
    )
    monkeypatch.chdir(repo)

    (repo / "a.js").write_text("// reworded note about retries\nconst a = 1;\n", encoding="utf-8")
    assert main(["verify"]) == 0
    capsys.readouterr()

    (repo / "a.js").write_text("// reworded note about retries\nconst a = 2;\n", encoding="utf-8")
    assert main(["verify"]) == 1
    assert "NOT comment-only" in capsys.readouterr().out


def test_pathless_verify_rejects_non_git_baseline(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "base").mkdir()
    assert main(["verify", "--baseline", str(tmp_path / "base")]) == 2
    assert "git: baseline" in capsys.readouterr().err


def test_cli_verify_stdin(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    old = "// old\nconst a = 1;\n"
    new = "// new wording here\nconst a = 1;\n"
    _write(tmp_path, "a.js", new)

    class _Stdin:
        buffer = io.BytesIO(_udiff(old, new, "a.js").encode("utf-8"))

    monkeypatch.setattr(sys, "stdin", _Stdin())
    assert main(["verify", "--diff", "-"]) == 0
    assert "comment-only" in capsys.readouterr().out

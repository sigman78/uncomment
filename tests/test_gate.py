"""Gate mode: only comments new relative to the baseline are judged."""

from __future__ import annotations

from pathlib import Path

from unwaffle.config import Config
from unwaffle.gate import gate_file, gate_paths

OLD = """\
// Debounce keeps the request count low.
export function debounce(fn, delay = 250) {
  let timer = null;
  return () => fn();
}
"""

# same file after an agent edit: one old comment kept, noisy ones added
NEW = """\
// Debounce keeps the request count low.
export function debounce(fn, delay = 250) {
  // Changed the timer handling as requested
  let timer = null;
  // Then we return the wrapped callback
  return () => fn();
}
"""


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_only_new_comments_are_flagged(tmp_path):
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    _write(old_dir, "a.js", OLD)
    new_file = _write(new_dir, "a.js", NEW)

    findings, sf, stats = gate_file(new_file, str(old_dir), new_dir, Config())
    rules = {f.rule for f in findings}
    assert "UC003" in rules  # the edit-narration line
    assert "UC002" in rules  # the process-narration line
    # the pre-existing comment on line 1 must not produce findings
    assert all(f.line != 1 for f in findings)
    assert stats["new_comments"] == 2


def test_unchanged_file_is_silent(tmp_path):
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    _write(old_dir, "a.js", NEW)  # baseline already contains the noise
    new_file = _write(new_dir, "a.js", NEW)

    findings, _, stats = gate_file(new_file, str(old_dir), new_dir, Config())
    assert findings == []
    assert stats["new_comments"] == 0


def test_moved_comment_is_not_new(tmp_path):
    old = "// Keeps latency low on slow disks.\nconst a = 1;\n"
    new = "const a = 1;\n// Keeps latency low on slow disks.\nconst b = 2;\n"
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    _write(old_dir, "a.js", old)
    new_file = _write(new_dir, "a.js", new)

    _, _, stats = gate_file(new_file, str(old_dir), new_dir, Config())
    assert stats["new_comments"] == 0


def test_comment_flood(tmp_path):
    old = "export function f() {\n  return 1;\n}\n"
    noise = "".join(f"// then we run filler step number {i} of the plan\n" for i in range(14))
    new = noise + old
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    _write(old_dir, "a.js", old)
    new_file = _write(new_dir, "a.js", new)

    findings, _, stats = gate_file(new_file, str(old_dir), new_dir, Config())
    assert stats["new_comment_lines"] == 14
    assert stats["added_code_lines"] == 0
    assert any(f.rule == "UC100" for f in findings)


def test_missing_baseline_treats_all_as_new(tmp_path):
    new_dir = tmp_path / "new"
    new_dir.mkdir()
    new_file = _write(new_dir, "a.js", NEW)

    findings, _, stats = gate_file(new_file, str(tmp_path / "absent"), new_dir, Config())
    assert stats["new_comments"] == 3
    assert any(f.rule == "UC003" for f in findings)


def _git_repo(tmp_path: Path) -> Path:
    """A fresh git repo, or skip the test when git is unavailable."""
    import shutil

    import pytest

    if shutil.which("git") is None:
        pytest.skip("git not available")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    return repo


def _git(repo: Path, *args: str) -> None:
    import os
    import subprocess

    subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
             "GIT_COMMITTER_EMAIL": "t@t", "PATH": os.environ["PATH"]},
    )


def test_git_baseline(tmp_path):
    repo = _git_repo(tmp_path)
    f = repo / "a.js"
    f.write_text(OLD, encoding="utf-8")
    _git(repo, "add", "a.js")
    _git(repo, "commit", "-q", "-m", "base")
    f.write_text(NEW, encoding="utf-8")

    findings, _, stats = gate_file(f, "git:HEAD", repo, Config())
    assert stats["new_comments"] == 2
    assert {x.rule for x in findings} >= {"UC002", "UC003"}


def test_git_baseline_multi_file_rename(tmp_path):
    """Several files against one git baseline (exercises the cat-file batch)
    plus a rename, which pulls in the ls-tree sweep."""
    repo = _git_repo(tmp_path)
    (repo / "a.js").write_text(OLD, encoding="utf-8")
    (repo / "b.js").write_text(
        "// Retry twice: the registry drops the first request under load.\nexport const N = 2;\n",
        encoding="utf-8",
    )
    _git(repo, "add", "a.js", "b.js")
    _git(repo, "commit", "-q", "-m", "base")

    (repo / "a.js").write_text(NEW, encoding="utf-8")
    (repo / "b.js").rename(repo / "c.js")  # rename: c.js has no HEAD counterpart

    result = gate_paths([repo], "git:HEAD", Config())
    assert result.files_scanned == 2
    # the renamed file's comment matched through the tree sweep; only the
    # two noisy comments added to a.js are new
    assert result.new_comments == 2
    assert {f.rule for f in result.findings} >= {"UC002", "UC003"}
    assert all(str(f.path).endswith("a.js") for f in result.findings)


def test_pathless_gate_uses_git_change_list(tmp_path, monkeypatch, capsys):
    import json

    from unwaffle.cli import main

    repo = _git_repo(tmp_path)
    (repo / "touched.js").write_text(OLD, encoding="utf-8")
    (repo / "untouched.js").write_text("// A settled note that never changes.\nconst u = 1;\n", encoding="utf-8")
    (repo / "excluded.js").write_text(OLD, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")

    (repo / "touched.js").write_text(NEW, encoding="utf-8")          # differs from base
    (repo / "excluded.js").write_text(NEW, encoding="utf-8")         # differs, but excluded
    (repo / "fresh.js").write_text(NEW, encoding="utf-8")            # untracked
    (repo / "notes.txt").write_text("changed\n", encoding="utf-8")   # unsupported

    monkeypatch.chdir(repo)
    code = main(["gate", "--baseline", "git:HEAD", "--exclude", "excluded.js",
                 "--format", "json", "--fail-on", "never"])
    doc = json.loads(capsys.readouterr().out)
    assert code == 0
    # only the changed+selected files were gated: untouched.js not scanned
    assert doc["stats"]["files_scanned"] == 2
    assert doc["stats"]["files_skipped"] == 2  # excluded.js + notes.txt
    paths = {f["path"] for f in doc["findings"]}
    assert paths and all("touched" in p or "fresh" in p for p in paths)


def test_pathless_gate_outside_repo_is_loud(tmp_path, monkeypatch, capsys):
    from unwaffle.cli import main

    monkeypatch.chdir(tmp_path)
    assert main(["gate", "--baseline", "git:HEAD"]) == 2
    err = capsys.readouterr().err
    assert "repository" in err


def test_pathless_gate_needs_git_baseline(tmp_path, monkeypatch, capsys):
    from unwaffle.cli import main

    monkeypatch.chdir(tmp_path)
    (tmp_path / "base").mkdir()
    assert main(["gate", "--baseline", str(tmp_path / "base")]) == 2
    assert "needs a git: baseline" in capsys.readouterr().err


def test_gate_paths_aggregates(tmp_path):
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    _write(old_dir, "a.js", OLD)
    _write(new_dir, "a.js", NEW)
    result = gate_paths([new_dir], str(old_dir), Config())
    assert result.files_scanned == 1
    assert result.new_comments == 2
    assert {f.rule for f in result.findings} >= {"UC002", "UC003"}

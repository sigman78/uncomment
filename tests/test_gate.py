"""Gate mode: only comments new relative to the baseline are judged."""

from __future__ import annotations

from pathlib import Path

from uncomment.config import Config
from uncomment.gate import gate_file, gate_paths

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
    assert "UC003" in rules  # "Changed ... as requested"
    assert "UC002" in rules  # "Then we ..."
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
    noise = "".join(f"// narrative filler line number {i} explaining nothing\n" for i in range(14))
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


def test_git_baseline(tmp_path):
    import shutil
    import subprocess

    import pytest

    if shutil.which("git") is None:
        pytest.skip("git not available")
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        subprocess.run(
            ["git", *args], cwd=repo, check=True, capture_output=True,
            env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                 "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"]},
        )

    git("init", "-q")
    f = repo / "a.js"
    f.write_text(OLD, encoding="utf-8")
    git("add", "a.js")
    git("commit", "-q", "-m", "base")
    f.write_text(NEW, encoding="utf-8")

    findings, _, stats = gate_file(f, "git:HEAD", repo, Config())
    assert stats["new_comments"] == 2
    assert {x.rule for x in findings} >= {"UC002", "UC003"}


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

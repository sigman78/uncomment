"""Python support: # comments, docstrings as doc comments, directives."""

from __future__ import annotations

from unwaffle.config import Config
from unwaffle.extract import extract_source, strip_docstring_quotes, strip_markers
from unwaffle.gate import gate_file
from unwaffle.languages import is_interface_file, spec_for_path
from unwaffle.model import Attachment, Kind
from unwaffle.rules import run_rules

PY = spec_for_path("x.py")


def _extract(src: str):
    return extract_source("x.py", src, PY)


def test_hash_comments_group_and_strip():
    sf = _extract("# one line\n# and another\nx = 1\n")
    assert len(sf.comments) == 1
    c = sf.comments[0]
    assert c.kind is Kind.LINE
    assert c.content == "one line\nand another"
    assert c.attachment is Attachment.PRECEDING
    assert c.attached_code == "x = 1"


def test_strip_markers_keeps_banner_and_shebang():
    assert strip_markers("##########", "#") == "#########"
    assert strip_markers("#!/usr/bin/env python", "#") == "!/usr/bin/env python"


def test_docstrings_are_doc_comments():
    src = (
        '"""Module doc."""\n'
        "\n"
        "class Greeter:\n"
        '    """Class doc."""\n'
        "\n"
        "    def hello(self):\n"
        '        """Say hello politely."""\n'
        "        return 1\n"
    )
    sf = _extract(src)
    kinds = [(c.kind, c.attachment, c.attached_code) for c in sf.comments]
    assert kinds[0] == (Kind.DOC, Attachment.FILE_HEADER, "")
    assert kinds[1] == (Kind.DOC, Attachment.PRECEDING, "class Greeter:")
    assert kinds[2] == (Kind.DOC, Attachment.PRECEDING, "def hello(self):")
    # a function's own docstring is its API doc, not an interior comment
    assert all(not c.in_function for c in sf.comments)


def test_docstring_lines_are_not_code():
    src = 'def f():\n    """Doc line.\n\n    More doc.\n    """\n    return 1\n'
    sf = _extract(src)
    assert sf.code_line_count == 2  # def line + return line


def test_non_docstring_string_is_not_a_comment():
    sf = _extract('def f():\n    x = 1\n    "not a docstring"\n    return x\n')
    assert sf.comments == []


def test_strip_docstring_quotes_prefixes():
    assert strip_docstring_quotes('r"""raw doc"""') == "raw doc"
    assert strip_docstring_quotes("'''single'''") == "single"
    assert strip_docstring_quotes('"one liner"') == "one liner"


def test_python_directives_exempt():
    src = (
        "#!/usr/bin/env python\n"
        "# -*- coding: utf-8 -*-\n"
        "import os  # noqa: F401\n"
        "x = []  # type: ignore[assignment]\n"
        "if os.name:  # pragma: no cover\n"
        "    pass  # fmt: off\n"
    )
    sf = _extract(src)
    assert all(c.is_directive for c in sf.comments)
    assert run_rules(sf, Config()) == []


def test_redundant_docstring_flagged():
    sf = _extract('def get_name(self):\n    """Get the name."""\n    return self.name\n')
    assert any(f.rule == "UC007" for f in run_rules(sf, Config()))


def test_pyi_is_interface_file():
    assert is_interface_file("stubs/mod.pyi")
    assert spec_for_path("stubs/mod.pyi") is PY


def test_gate_python(tmp_path):
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    (old_dir / "a.py").write_text("# The registry drops the first request.\nx = 1\n", encoding="utf-8")
    (new_dir / "a.py").write_text(
        "# The registry drops the first request.\nx = 1\n# Updated the constant as requested\ny = 2\n",
        encoding="utf-8",
    )
    findings, _, stats = gate_file(new_dir / "a.py", str(old_dir), new_dir, Config())
    assert stats["new_comments"] == 1
    assert any(f.rule == "UC003" for f in findings)
    assert all(f.line != 1 for f in findings)


def test_suppression_marker_in_python():
    src = (
        "# unwaffle-ignore[UC005]: kept as a worked example\n"
        "# x = compute()\n"
        "y = 1\n"
    )
    sf = _extract(src)
    assert not any(f.rule == "UC005" for f in run_rules(sf, Config()))

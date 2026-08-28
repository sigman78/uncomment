#!/usr/bin/env python3
"""Extraction parity harness: diff the Rust port against the Python
reference over the corpus (or any given paths).

Compared per comment: start_line, end_line, col, kind, attachment, content,
attached_code, is_directive, in_function, function_name; per file:
code_line_count, comment_line_count, and the functions list.

Usage: python rust/parity.py [paths...]   (default: tests/corpus)
Exit 0 = parity, 1 = differences, 2 = harness failure.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from unwaffle.config import Config  # noqa: E402
from unwaffle.extract import extract_file  # noqa: E402
from unwaffle.rules import run_rules  # noqa: E402
from unwaffle.languages import EXTENSIONS  # noqa: E402

FIELDS = ("start_line", "end_line", "col", "kind", "attachment", "content",
          "attached_code", "is_directive", "in_function", "function_name")


def py_dump(path: Path) -> dict | None:
    sf = extract_file(path)
    if sf is None:
        return None
    return {
        "code_line_count": sf.code_line_count,
        "comment_line_count": sf.comment_line_count,
        "comments": [
            {
                "start_line": c.start_line,
                "end_line": c.end_line,
                "col": c.col,
                "kind": c.kind.value,
                "attachment": c.attachment.value,
                "content": c.content,
                "attached_code": c.attached_code,
                "is_directive": c.is_directive,
                "in_function": c.in_function,
                "function_name": c.function_name,
            }
            for c in sf.comments
        ],
        "functions": [
            [f.name, f.start_line, f.end_line, f.body_line_count] for f in sf.functions
        ],
        "findings": [
            [f.rule, f.line, f.end_line, f.severity.name.lower()]
            for f in run_rules(sf, Config())
        ],
    }


def main(argv: list[str]) -> int:
    roots = [Path(a) for a in argv] or [REPO / "tests" / "corpus"]
    files = sorted(
        p for root in roots
        for p in (root.rglob("*") if root.is_dir() else [root])
        if p.is_file() and p.suffix.lower() in EXTENSIONS
    )
    if not files:
        print("parity: no supported files found", file=sys.stderr)
        return 2

    proc = subprocess.run(
        ["cargo", "run", "--quiet", "--bin", "dump_comments", "--"] + [str(f) for f in files],
        cwd=REPO / "rust", capture_output=True, text=True, encoding="utf-8",
    )
    if proc.returncode != 0:
        print(f"parity: rust dump failed:\n{proc.stderr}", file=sys.stderr)
        return 2
    rust_dumps = {Path(d["path"]).resolve(): d for d in json.loads(proc.stdout)}

    mismatched_files = 0
    for f in files:
        rust = rust_dumps.get(f.resolve())
        py = py_dump(f)
        if rust is None or not rust["supported"]:
            print(f"SKIP {f} (not yet supported in rust)")
            continue
        diffs: list[str] = []
        for counter in ("code_line_count", "comment_line_count"):
            if rust[counter] != py[counter]:
                diffs.append(f"  {counter}: rust={rust[counter]} py={py[counter]}")
        rc, pc = rust["comments"], py["comments"]
        if len(rc) != len(pc):
            diffs.append(f"  comment count: rust={len(rc)} py={len(pc)}")
            rust_spans = [(c["start_line"], c["end_line"]) for c in rc]
            py_spans = [(c["start_line"], c["end_line"]) for c in pc]
            diffs.append(f"    rust spans: {rust_spans}")
            diffs.append(f"    py spans:   {py_spans}")
        else:
            for i, (r, p) in enumerate(zip(rc, pc)):
                for field in FIELDS:
                    if r[field] != p[field]:
                        diffs.append(
                            f"  comment[{i}] line {p['start_line']} {field}: "
                            f"rust={r[field]!r} py={p[field]!r}"
                        )
        rust_funcs = [[f["name"], f["start_line"], f["end_line"], f["body_line_count"]]
                      for f in rust.get("functions", [])]
        if rust_funcs != py["functions"]:
            diffs.append(f"  functions: rust={rust_funcs} py={py['functions']}")
        rust_findings = [[f["rule"], f["line"], f["end_line"], f["severity"]]
                         for f in rust.get("findings", [])]
        if rust_findings != py["findings"]:
            gone = [f for f in py["findings"] if f not in rust_findings]
            extra = [f for f in rust_findings if f not in py["findings"]]
            diffs.append(f"  findings: missing in rust={gone} extra in rust={extra}")
        if diffs:
            mismatched_files += 1
            print(f"DIFF {f}")
            print("\n".join(diffs[:12]))

    checked = sum(1 for f in files if rust_dumps.get(f.resolve(), {}).get("supported"))
    print(f"\nparity: {checked - mismatched_files}/{checked} files match "
          f"({len(files) - checked} skipped)")
    return 1 if mismatched_files else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

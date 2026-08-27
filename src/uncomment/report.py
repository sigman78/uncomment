"""Renderers: human text, machine JSON, and agent-feedback markdown.

The 'agent' format is designed to be fed back verbatim to a coding agent as a
corrective prompt: policy first, then per-file actionable items.
"""

from __future__ import annotations

import json
from collections import Counter

from .model import Finding, Severity

SCHEMA_VERSION = 1

_SEV_LABEL = {Severity.INFO: "info", Severity.WARN: "warn", Severity.ERROR: "error"}

_ASCII_MAP = str.maketrans(
    {"→": "->", "←": "<-", "…": "...", "—": "--", "–": "-", "·": "*",
     "“": '"', "”": '"', "‘": "'", "’": "'", " ": " "}
)


def to_ascii(text: str) -> str:
    """Transliterate the tool's own typography, then strip anything else
    non-ASCII (source excerpts may contain arbitrary Unicode)."""
    return text.translate(_ASCII_MAP).encode("ascii", "replace").decode("ascii")


def _loc(f: Finding) -> str:
    return f"L{f.line}" if f.line == f.end_line else f"L{f.line}-L{f.end_line}"


def render_text(findings: list[Finding], stats: dict) -> str:
    out: list[str] = []
    for f in findings:
        out.append(f"{f.path}:{f.line}: [{_SEV_LABEL[f.severity]}] {f.rule} {f.message}")
        if f.excerpt:
            out.append(f"    > {f.excerpt}")
        out.append(f"    fix: {f.action}")
    counts = Counter(f.severity for f in findings)
    out.append("")
    out.append(
        f"{stats.get('files_scanned', 0)} file(s) scanned: "
        f"{counts[Severity.ERROR]} error(s), {counts[Severity.WARN]} warning(s), {counts[Severity.INFO]} hint(s)"
    )
    for key in ("new_comments", "new_comment_lines", "added_code_lines"):
        if key in stats:
            out.append(f"  {key.replace('_', ' ')}: {stats[key]}")
    return "\n".join(out)


def render_json(findings: list[Finding], stats: dict) -> str:
    counts = Counter(f.severity for f in findings)
    doc = {
        "schema_version": SCHEMA_VERSION,
        "tool": "uncomment",
        "stats": stats,
        "summary": {
            "error": counts[Severity.ERROR],
            "warn": counts[Severity.WARN],
            "info": counts[Severity.INFO],
            "by_rule": dict(Counter(f.rule for f in findings)),
        },
        "findings": [f.to_dict() for f in findings],
    }
    return json.dumps(doc, indent=2)


_POLICY = """\
# Comment review feedback

An automated comment linter reviewed your changes. Fix every item below, then
re-run the check. Comment policy:

1. Comments explain WHY, never WHAT. If a comment restates the adjacent code, delete it.
2. Never describe the edit you made ("added X", "changed Y", "as requested").
   That history belongs in the commit message.
3. Do not narrate your process ("now we...", "first...", "step 1"). State intent once, briefly.
4. Delete commented-out code; version control preserves it.
5. Delete banner/divider and label comments ("// helpers", "// end of loop").
6. Long guide-level prose belongs in project docs or a doc comment, not inside code.
7. Wording follows Simplified Technical English: short sentences (max 20 words),
   active voice, simple common words.

When you delete a comment, delete only the comment; never change the code around it
unless an item explicitly asks for it.
"""


def render_agent(findings: list[Finding], stats: dict) -> str:
    if not findings:
        return "# Comment review feedback\n\nNo comment issues found. No action needed.\n"

    gating = [f for f in findings if f.severity >= Severity.WARN and not f.rule.startswith("STE")]
    docs = [f for f in findings if f.rule == "UC008"]
    wording = [f for f in findings if f.rule.startswith("STE")]
    hints = [f for f in findings if f.severity == Severity.INFO and f.rule != "UC008" and not f.rule.startswith("STE")]

    out = [_POLICY]

    def section(title: str, items: list[Finding], required: bool) -> None:
        if not items:
            return
        out.append(f"\n## {title}\n")
        by_path: dict[str, list[Finding]] = {}
        for f in items:
            by_path.setdefault(f.path, []).append(f)
        for path, fs in by_path.items():
            out.append(f"### `{path}`\n")
            for f in fs:
                mark = "MUST FIX" if required and f.severity >= Severity.WARN else "consider"
                out.append(f"- **{_loc(f)}** `{f.rule}` [{mark}]: {f.message}")
                if f.excerpt:
                    out.append(f"  - comment: `{f.excerpt}`")
                out.append(f"  - action: {f.action}")
            out.append("")

    section("Comments to delete or fix", gating, required=True)
    section("Documentation migration candidates (keep the code lean, move the knowledge)", docs, required=False)
    section("Wording (Simplified Technical English)", wording, required=False)
    section("Other hints", hints, required=False)

    counts = Counter(f.severity for f in findings)
    out.append(
        f"\n---\nSummary: {counts[Severity.ERROR]} error(s), {counts[Severity.WARN]} warning(s), "
        f"{counts[Severity.INFO]} hint(s) across {stats.get('files_scanned', 0)} file(s)."
    )
    return "\n".join(out)


RENDERERS = {"text": render_text, "json": render_json, "agent": render_agent}

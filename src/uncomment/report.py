"""Renderers: human text, machine JSON, agent-feedback markdown, and SARIF.

The 'agent' format is designed to be fed back verbatim to a coding agent as a
corrective prompt: policy first, then per-file actionable items. The 'sarif'
format (SARIF 2.1.0) plugs into GitHub code scanning and other annotators.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

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
8. API documentation on public interfaces (header files, exported symbols,
   Doxygen/JSDoc/rustdoc) is WANTED — prune noise, never strip real docs.
   Existing comments nearby are not an invitation to add more.

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


_SARIF_LEVEL = {Severity.ERROR: "error", Severity.WARN: "warning", Severity.INFO: "note"}
_SARIF_LEVEL_BY_NAME = {"error": "error", "warn": "warning", "info": "note"}


def _artifact_uri(path: str) -> str:
    p = Path(path)
    return p.as_uri() if p.is_absolute() else p.as_posix()


def render_sarif(findings: list[Finding], stats: dict) -> str:
    from . import __version__
    from .rules import GATE_SIGNALS, all_rules

    meta = {r.id: (r.title, r.doc, _SARIF_LEVEL[r.severity]) for r in all_rules()}
    meta.update({rid: (title, doc, _SARIF_LEVEL_BY_NAME[sev]) for rid, sev, title, doc in GATE_SIGNALS})

    rule_ids = sorted({f.rule for f in findings})
    index = {rid: i for i, rid in enumerate(rule_ids)}
    descriptors = []
    for rid in rule_ids:
        title, doc, level = meta.get(rid, (rid, "", "warning"))
        desc: dict = {
            "id": rid,
            "shortDescription": {"text": title},
            "defaultConfiguration": {"level": level},
        }
        if doc:
            desc["fullDescription"] = {"text": doc}
        descriptors.append(desc)

    results = []
    for f in findings:
        region: dict = {"startLine": f.line, "endLine": f.end_line}
        if f.excerpt:
            region["snippet"] = {"text": f.excerpt}
        results.append(
            {
                "ruleId": f.rule,
                "ruleIndex": index[f.rule],
                "level": _SARIF_LEVEL[f.severity],
                "message": {"text": f"{f.message}. Fix: {f.action}"},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": _artifact_uri(f.path)},
                            "region": region,
                        }
                    }
                ],
            }
        )

    doc = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "uncomment",
                        "version": __version__,
                        "informationUri": "https://github.com/sigman78/uncomment",
                        "rules": descriptors,
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(doc, indent=2)


RENDERERS = {"text": render_text, "json": render_json, "agent": render_agent, "sarif": render_sarif}

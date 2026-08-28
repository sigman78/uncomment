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


def render_text(findings: list[Finding], stats: dict, cfg=None) -> str:
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


def render_json(findings: list[Finding], stats: dict, cfg=None) -> str:
    counts = Counter(f.severity for f in findings)
    doc = {
        "schema_version": SCHEMA_VERSION,
        "tool": "unwaffle",
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


# policy points paired with the rule families they correct; the preamble
# emits only the points the findings actually need, so a one-rule report
# does not spend the agent's context on seven unrelated instructions
_POLICY_POINTS: list[tuple[tuple[str, ...], str]] = [
    (("UC001", "UC007"),
     "Comments explain WHY, never WHAT. If a comment restates the adjacent code, delete it."),
    (("UC003",),
     'Never describe the edit you made ("added X", "changed Y", "as requested"). '
     "That history belongs in the commit message."),
    (("UC002",),
     'Do not narrate your process ("now we...", "first...", "step 1"). State intent once, briefly.'),
    (("UC005",),
     "Delete commented-out code; version control preserves it."),
    (("UC004", "UC010"),
     'Delete banner/divider and label comments ("// helpers", "// end of loop").'),
    (("UC006", "UC008", "UC100", "UC101"),
     "Long guide-level prose belongs in project docs or a doc comment, not inside code."),
    (("STE",),
     "Wording follows Simplified Technical English: short sentences (max 20 words), "
     "active voice, simple common words."),
]

# guardrails hold in every report: they prevent overcorrection
_POLICY_GUARD = (
    "API documentation on public interfaces (header files, exported symbols, "
    "Doxygen/JSDoc/rustdoc) is WANTED — prune noise, never strip real docs. "
    "Existing comments nearby are not an invitation to add more."
)

_POLICY_CLOSING = (
    "When you delete a comment, delete only the comment; never change the code around it\n"
    "unless an item explicitly asks for it.\n"
)


def _policy(findings: list[Finding], cfg) -> str:
    fired = {f.rule for f in findings}
    points = [
        text for prefixes, text in _POLICY_POINTS
        if any(rule.startswith(p) for rule in fired for p in prefixes)
    ]
    points.append(_POLICY_GUARD)
    if cfg is not None:
        points.extend(cfg.agent_policy)
    numbered = "\n".join(f"{i}. {text}" for i, text in enumerate(points, 1))
    return (
        "# Comment review feedback\n\n"
        "An automated comment linter reviewed your changes. Fix every item below, then\n"
        "re-run the check. Comment policy:\n\n"
        f"{numbered}\n\n{_POLICY_CLOSING}"
    )


def render_agent(findings: list[Finding], stats: dict, cfg=None) -> str:
    if not findings:
        return "# Comment review feedback\n\nNo comment issues found. No action needed.\n"

    gating = [f for f in findings if f.severity >= Severity.WARN and not f.rule.startswith("STE")]
    docs = [f for f in findings if f.rule == "UC008"]
    wording = [f for f in findings if f.rule.startswith("STE")]
    hints = [f for f in findings if f.severity == Severity.INFO and f.rule != "UC008" and not f.rule.startswith("STE")]

    out = [_policy(findings, cfg)]

    def section(title: str, items: list[Finding]) -> None:
        if not items:
            return
        out.append(f"\n## {title}\n")
        by_path: dict[str, list[Finding]] = {}
        for f in items:
            by_path.setdefault(f.path, []).append(f)
        for path, fs in by_path.items():
            out.append(f"### `{path}`\n")
            # one group per (rule, action): the instruction prints once, the
            # sites list stays one line each
            groups: dict[tuple[str, str], list[Finding]] = {}
            for f in fs:
                groups.setdefault((f.rule, f.action), []).append(f)
            for (rule_id, action), grouped in groups.items():
                head = grouped[0]
                # the mark mirrors EFFECTIVE severity, config promotions and
                # demotions included: agents follow the label literally, and
                # a promoted rule labeled "consider" gets skipped while still
                # failing the gate
                mark = "MUST FIX" if any(g.severity >= Severity.WARN for g in grouped) else "consider"
                count = f" ×{len(grouped)}" if len(grouped) > 1 else ""
                label = f" — {head.message}" if head.excerpt else ""
                out.append(f"- `{rule_id}` [{mark}]{count}{label}")
                out.append(f"  fix: {action}")
                for f in grouped:
                    detail = f"`{f.excerpt}`" if f.excerpt else f.message
                    out.append(f"  - **{_loc(f)}**: {detail}")
            out.append("")

    section("Comments to delete or fix", gating)
    section("Documentation migration candidates (keep the code lean, move the knowledge)", docs)
    section("Wording (Simplified Technical English)", wording)
    section("Other hints", hints)

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


def render_sarif(findings: list[Finding], stats: dict, cfg=None) -> str:
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
                        "name": "unwaffle",
                        "version": __version__,
                        "informationUri": "https://github.com/sigman78/unwaffle",
                        "rules": descriptors,
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(doc, indent=2)


RENDERERS = {"text": render_text, "json": render_json, "agent": render_agent, "sarif": render_sarif}

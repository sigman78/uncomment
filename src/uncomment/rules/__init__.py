"""Rule framework and registry."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from ..config import Config
from ..model import Comment, Finding, Severity, SourceFile


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    severity: Severity
    fn: Callable[[SourceFile, Config], Iterable[Finding]]
    doc: str = ""


_REGISTRY: list[Rule] = []


def rule(rule_id: str, title: str, severity: Severity, doc: str = ""):
    def decorate(fn):
        _REGISTRY.append(Rule(rule_id, title, severity, fn, doc))
        return fn

    return decorate


def all_rules() -> list[Rule]:
    return list(_REGISTRY)


_LICENSE_RE = re.compile(
    r"copyright|license|licence|permission is hereby granted|spdx-license|apache|gnu general public|redistribution and use",
    re.IGNORECASE,
)


def is_license_header(comment: Comment) -> bool:
    # a license block at the very top counts even when code follows directly
    # (which classifies it as 'preceding' rather than 'file_header')
    at_top = comment.attachment.value == "file_header" or comment.start_line == 1
    return at_top and bool(_LICENSE_RE.search(comment.content))


# owned, auditable escape hatch: `uncomment-ignore[UC003]: reason` inside a
# comment suppresses the listed rules for it; without a rule list it
# suppresses everything anchored inside its target. A standalone marker
# comment also covers the comment or line directly below it.
_IGNORE_RE = re.compile(r"uncomment-ignore(?:\[(?P<rules>[A-Za-z0-9 ,]+)\])?")


def _suppressions(sf: SourceFile) -> list[tuple[frozenset[str] | None, int, int]]:
    sups = []
    for i, c in enumerate(sf.comments):
        m = _IGNORE_RE.search(c.content)
        if not m:
            continue
        rules = (
            frozenset(r.strip() for r in m.group("rules").split(",") if r.strip())
            if m.group("rules")
            else None
        )
        start, end = c.start_line, c.end_line
        if c.content.strip().startswith("uncomment-ignore"):
            nxt = sf.comments[i + 1] if i + 1 < len(sf.comments) else None
            if nxt is not None and nxt.start_line == c.end_line + 1:
                end = nxt.end_line
            else:
                end = c.end_line + 1  # covers the code line below
        sups.append((rules, start, end))
    return sups


def _suppressed(f: Finding, sups) -> bool:
    for rules, start, end in sups:
        if rules is None:
            if start <= f.line and f.end_line <= end:
                return True
        elif f.rule in rules and not (f.end_line < start or f.line > end):
            return True
    return False


def _is_marker(c: Comment) -> bool:
    return c.content.strip().startswith("uncomment-ignore")


def visible_comments(sf: SourceFile, cfg: Config) -> list:
    """Comments that rules may judge: tooling directives and standalone
    suppression markers are exempt, plus anything matching the user's extra
    `directive-patterns` config."""
    extra = [re.compile(p) for p in cfg.directive_patterns]
    return [
        c
        for c in sf.comments
        if not c.is_directive
        and not _is_marker(c)
        and not any(rx.search(c.content) for rx in extra)
    ]


def run_rules(sf: SourceFile, cfg: Config) -> list[Finding]:
    from dataclasses import replace

    sups = _suppressions(sf)
    sf = replace(sf, comments=visible_comments(sf, cfg))
    findings: list[Finding] = []
    for r in _REGISTRY:
        if not cfg.rule_enabled(r.id):
            continue
        rule_findings = []
        for f in r.fn(sf, cfg):
            if _suppressed(f, sups):
                continue
            override = cfg.severity_override(r.id)
            if override is not None:
                f.severity = override
            rule_findings.append(f)
        findings.extend(_cap_hints(r.id, rule_findings, cfg))
    findings.sort(key=lambda f: (f.path, f.line, f.rule))
    return findings


def _cap_hints(rule_id: str, findings: list[Finding], cfg: Config) -> list[Finding]:
    """Collapse repetitive INFO findings so one systemic pattern (e.g. passive
    voice in every doc comment) does not drown the report. Gating severities
    (warn/error) are never suppressed."""
    hints = [f for f in findings if f.severity == Severity.INFO]
    if len(hints) <= cfg.max_hints_per_rule:
        return findings
    dropped = len(hints) - cfg.max_hints_per_rule
    out = [f for f in findings if f.severity != Severity.INFO]
    out.extend(hints[: cfg.max_hints_per_rule])
    last = hints[cfg.max_hints_per_rule - 1]
    out.append(
        Finding(
            rule=rule_id,
            severity=Severity.INFO,
            path=last.path,
            line=last.line,
            end_line=last.line,
            message=f"{dropped} more {rule_id} hint(s) in this file, not listed",
            action="The pattern repeats through this file; apply the same fix everywhere.",
        )
    )
    return out


# importing registers the rules
from . import core as _core  # noqa: E402,F401
from . import ste as _ste  # noqa: E402,F401

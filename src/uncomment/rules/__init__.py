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
    return comment.attachment.value == "file_header" and bool(_LICENSE_RE.search(comment.content))


def run_rules(sf: SourceFile, cfg: Config) -> list[Finding]:
    findings: list[Finding] = []
    for r in _REGISTRY:
        if not cfg.rule_enabled(r.id):
            continue
        rule_findings = []
        for f in r.fn(sf, cfg):
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

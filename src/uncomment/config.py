"""Configuration: thresholds, disabled rules, severity overrides.

Loaded from `uncomment.toml` or `[tool.uncomment]` in `pyproject.toml`,
searched upward from the scanned path. All settings have defaults tuned for
gating agent-introduced comment noise.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

from .model import Severity


@dataclass
class Config:
    # UC001 restates-code
    restate_overlap: float = 0.6
    # UC005 commented-out code: fraction of code-looking lines
    code_line_fraction: float = 0.5
    # UC006 density: interior comment lines / body lines
    max_function_comment_ratio: float = 0.4
    min_interior_comment_lines: int = 4
    # UC008 doc migration: comment length that suggests real documentation
    doc_migration_lines: int = 12
    # UC009 trailing comment length
    max_trailing_chars: int = 60
    # UC007 redundant doc
    redundant_doc_overlap: float = 0.75
    # gate: comment flood (added comment lines vs added code lines)
    flood_ratio: float = 0.75
    flood_min_lines: int = 12
    # STE wording
    ste_max_sentence_words: int = 20
    ste_max_paragraph_sentences: int = 6
    # cap on INFO findings per rule per file; the rest collapse into one summary
    max_hints_per_rule: int = 8

    disable: list[str] = field(default_factory=list)
    severity: dict[str, str] = field(default_factory=dict)

    def rule_enabled(self, rule_id: str) -> bool:
        return not any(rule_id.startswith(d) for d in self.disable)

    def severity_override(self, rule_id: str) -> Severity | None:
        name = self.severity.get(rule_id)
        return Severity.parse(name) if name else None


def _from_table(table: dict) -> Config:
    cfg = Config()
    valid = {f.name for f in fields(Config)}
    for key, value in table.items():
        norm = key.replace("-", "_")
        if norm in valid:
            setattr(cfg, norm, value)
    return cfg


def load_config(start: str | Path = ".", explicit: str | None = None) -> Config:
    if explicit:
        with open(explicit, "rb") as fh:
            data = tomllib.load(fh)
        return _from_table(data.get("tool", {}).get("uncomment", data))

    directory = Path(start).resolve()
    if directory.is_file():
        directory = directory.parent
    for candidate_dir in [directory, *directory.parents]:
        toml_path = candidate_dir / "uncomment.toml"
        if toml_path.is_file():
            with open(toml_path, "rb") as fh:
                return _from_table(tomllib.load(fh))
        pyproject = candidate_dir / "pyproject.toml"
        if pyproject.is_file():
            with open(pyproject, "rb") as fh:
                data = tomllib.load(fh)
            table = data.get("tool", {}).get("uncomment")
            if table is not None:
                return _from_table(table)
    return Config()

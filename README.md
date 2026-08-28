# unwaffle

Lint and gate the comment noise that coding agents leave behind.

Coding agents tend to over-comment: they narrate their process ("First, we
validate the input"), describe their edits ("Changed to use memcpy as
requested"), restate the code ("// return the total"), drop banners and label
comments, and leave commented-out code. `unwaffle` detects this with
tree-sitter parsing, judges only what an edit *added* (gate mode), and emits
feedback a coding harness can feed straight back to the agent as a corrective
prompt. What it never touches: real API documentation, WHY-comments, license
headers, and tooling directives.

Supported languages: **C, C++, JavaScript (JSX), TypeScript (TSX), Rust, Go,
Python** (docstrings included), **Java, C#, Kotlin, Swift**.

## Quick start

Requires Python ≥ 3.13 and [uv](https://docs.astral.sh/uv/):

```console
uvx unwaffle check .                            # one-shot, from PyPI
uv run unwaffle check src/                      # scan everything
uv run unwaffle gate src/ --baseline git:HEAD   # judge only new comments
git diff | uv run unwaffle gate --diff -        # judge only what a diff added
uv run unwaffle verify                          # prove working-tree changes are comment-only
uv run unwaffle rules                           # list rules
```

Exit codes: `0` clean, `1` gated findings, `2` bad input — always loud, never
a silently green gate. **`check`** scans every comment; **`gate`** compares
against a baseline (directory, `git:REF`, or a unified diff) and judges only
comments that are genuinely new — moves, typo fixes, and renames are never
re-judged. Scans respect `.gitignore` and skip generated files by default,
with `include`/`exclude` globs for the rest, so `unwaffle check .` behaves
on real trees. Configuration lives in `unwaffle.toml` or `pyproject.toml`
(`[tool.unwaffle]`), discovered upward from the scanned path.

## Integration

Run the gate after the agent edits; on exit `1`, hand the `--format agent`
output back to the agent as its next instruction and re-run:

```console
unwaffle gate . --baseline git:origin/main --format agent > comment-feedback.md
```

Also available: `--format json` (stable machine schema), `--format sarif`
(GitHub code scanning), a stdin diff mode for edit hooks, and a Claude Code
hook recipe — see [integrations](docs/integrations.md).

## Documentation

- [Rules](docs/rules.md) — the full rule table, what is deliberately not
  flagged, tooling-directive exemptions, and in-place suppressions.
- [Gate mode](docs/gate.md) — baselines, staged matching, the flood and
  amplification signals, diff input, performance.
- [Configuration](docs/configuration.md) — every setting, `disable`/
  `severity`, `directive-patterns`, `approved-terms`.
- [Output formats and integrations](docs/integrations.md) — exit codes, the
  four formats, CI recipes, the Claude Code hook.
- [Development](docs/development.md) — the corpus contract, self-linting,
  architecture notes, the planned Rust port.

## Development

```console
uv run pytest
uv run unwaffle check src/ tests/test_*.py   # dogfood: CI enforces this
```

The test base is corpus-driven: noisy files carry sidecars with the exact
expected findings, clean files must stay at zero, and the tool lints its own
source in CI. Details in [development](docs/development.md).

MIT licensed.

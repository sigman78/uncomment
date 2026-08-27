# uncomment

Lint and gate the comment noise that coding agents leave behind.

Coding agents tend to over-comment: they narrate their process ("First, we
validate the input"), describe their edits ("Changed to use memcpy as
requested"), restate the code ("// return the total"), drop banners and label
comments, and leave commented-out code. `uncomment` detects this with
tree-sitter parsing, judges only what an edit *added* (gate mode), and emits
feedback a coding harness can feed straight back to the agent as a corrective
prompt.

Supported languages: **C, C++, JavaScript (JSX), TypeScript (TSX), Rust, Go**.

## Install / run

Requires Python ≥ 3.13 and [uv](https://docs.astral.sh/uv/):

```console
uv run uncomment check src/                      # scan everything
uv run uncomment gate src/ --baseline git:HEAD   # judge only new comments
uv run uncomment rules                           # list rules
```

Exit codes: `0` clean (or below the `--fail-on` threshold), `1` gated findings,
`2` usage/config error.

## The two modes

**`check`** scans every comment in the given files/directories.

**`gate`** is the harness workflow: it compares against a baseline — a
directory, a single file, or `git:REF` — and only judges comments that do not
exist in the baseline (matched by normalized content, so moved comments stay
silent). It also computes a *comment flood* signal (`UC100`): when an edit adds
far more comment lines than code lines, that alone is an error.

```console
uncomment gate src/parser.c --baseline git:main --format agent
```

## Output formats

- `--format text` — human-readable, one finding per block.
- `--format json` — stable machine schema (`schema_version: 1`): findings with
  `rule`, `severity`, `path`, `line`, `end_line`, `message`, `action`,
  `excerpt`, plus summary counts and gate stats.
- `--format agent` — a ready-to-send corrective prompt: the comment policy,
  then per-file items marked **MUST FIX** (warn/error) or *consider* (hints),
  each with the offending excerpt and the concrete action. Feed this back to
  the agent that made the edit and re-run the gate on its next attempt.

## Rules

| id | severity | catches |
|-------|----------|---------|
| UC001 | warn | comment restates the adjacent code (word-overlap vs. identifiers) |
| UC002 | warn | process narration: "now we…", "first,…", "step 1", numbered steps |
| UC003 | error | edit narration: "added/changed/fixed X", "as requested", "the previous version" |
| UC004 | warn | banner / divider comments (`// ======…`) |
| UC005 | warn | commented-out code |
| UC006 | warn | function body saturated with comments (default: >40% and ≥4 lines) |
| UC007 | warn | doc comment that restates the symbol name ("Gets the name." on `get_name`) |
| UC008 | info | **docs-migration hint**: guide-level prose (sections, essays, long file headers) that belongs in project docs or module docs |
| UC009 | warn | trailing comment too long to sit on the code line |
| UC010 | warn | boilerplate labels: "// imports", "// helpers", "// end of loop" |
| UC011 | info | TODO/FIXME without owner or ticket |
| UC100 | error | (gate only) comment flood: edit adds far more comment lines than code |
| STE01 | info | sentence over 20 words (ASD-STE100 style) |
| STE02 | info | passive voice |
| STE03 | info | non-simple wording ("utilize" → use, "in order to" → to, …) |
| STE04 | info | paragraph over 6 sentences |

What is deliberately **not** flagged: license headers, module/package docs
(Go `doc.go`, Rust `//!`), doc comments with real API content (params, errors,
invariants), short WHY-comments ("because…", "workaround…", links), and
anything already present in the baseline.

**Tooling directives are never judged.** Linter/compiler control comments are
functional lines, so no rule sees them, they are never suggested for removal,
and they do not count toward gate/flood statistics. Recognized out of the box:
`eslint-*`, `@ts-ignore`/`@ts-expect-error`/`@ts-nocheck`, `prettier-ignore`,
`biome-ignore`, `deno-lint-ignore`, webpack/vite magic comments, `@__PURE__`,
`sourceMappingURL`, istanbul/c8/v8 coverage markers, `NOLINT*`,
`clang-format on/off`, `cppcheck-suppress`, `IWYU pragma`, coverity,
`//go:*` (build/generate/embed/linkname/…), `// +build`, `//nolint`,
`//lint:ignore`, cgo preambles (the comment above `import "C"`), rustfmt/
compiletest markers, coverage exclusions (`LCOV_EXCL_*`), `NOSONAR`,
fallthrough hints, and `#region`/`#endregion`. Add project-specific ones via
`directive-patterns` in the config.

The STE rules are wording guidance inspired by ASD-STE100 (Simplified
Technical English): short sentences, active voice, one simple word per
meaning. They never gate by default; raise them via config if you want them to.

## Configuration

`uncomment.toml` (or `[tool.uncomment]` in `pyproject.toml`), discovered
upward from the scanned path:

```toml
[tool.uncomment]
restate-overlap = 0.6              # UC001 word-overlap threshold
max-function-comment-ratio = 0.4   # UC006
doc-migration-lines = 12           # UC008
max-trailing-chars = 60            # UC009
flood-ratio = 0.75                 # UC100: new comment lines / new code lines
flood-min-lines = 12
ste-max-sentence-words = 20
max-hints-per-rule = 8             # collapse repetitive info hints per file
disable = ["STE02", "UC011"]       # rule ids or prefixes ("STE" disables all STE)
directive-patterns = ["^MY-LINT:"] # extra tooling-directive regexes to exempt

[tool.uncomment.severity]          # promote/demote rules
STE03 = "warn"
UC004 = "info"
```

## Harness integration

The contract is plain: run the gate after the agent edits, and if the exit
code is `1`, hand the `--format agent` output back to the agent as its next
instruction, then re-run. No harness-specific coupling.

CI example:

```console
uncomment gate . --baseline git:origin/main --format agent > comment-feedback.md
```

Claude Code hook example (`.claude/settings.json`) — blocks a noisy edit and
shows the feedback to the agent:

```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Edit|Write",
      "hooks": [{
        "type": "command",
        "command": "sh -c 'f=$(jq -r .tool_input.file_path); uv run uncomment gate \"$f\" --baseline git:HEAD --format agent 1>&2; [ $? -eq 1 ] && exit 2 || exit 0'"
      }]
    }]
  }
}
```

## Development

```console
uv run pytest
```

The test base is corpus-driven and every change must keep it green:

- `tests/corpus/<lang>/agent_noise.*` — files full of agent-style noise, with
  a `.expected.json` sidecar holding the **exact** set of expected
  warn/error findings (a missing one is a recall regression, an extra one is
  new noise) and the hints that must appear.
- `tests/corpus/<lang>/clean.*` — idiomatic, well-commented code that must
  produce **zero** findings (false-positive guard).
- `test_every_rule_is_exercised` fails if a rule loses corpus coverage.

Design notes: parsing uses tree-sitter via `tree-sitter-language-pack`;
adjacent line comments are merged into logical comments, then classified by
kind (line / block / doc, including Go's convention docs) and attachment
(file header / preceding / trailing / floating / in-function). Rules operate
on that model, so a future Rust port can reuse the same corpus and expected
findings unchanged.

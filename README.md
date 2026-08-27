# uncomment

Lint and gate the comment noise that coding agents leave behind.

Coding agents tend to over-comment: they narrate their process ("First, we
validate the input"), describe their edits ("Changed to use memcpy as
requested"), restate the code ("// return the total"), drop banners and label
comments, and leave commented-out code. `uncomment` detects this with
tree-sitter parsing, judges only what an edit *added* (gate mode), and emits
feedback a coding harness can feed straight back to the agent as a corrective
prompt.

Supported languages: **C, C++, JavaScript (JSX), TypeScript (TSX), Rust, Go,
Python**.

## Install / run

Requires Python ≥ 3.13 and [uv](https://docs.astral.sh/uv/):

```console
uv run uncomment check src/                      # scan everything
uv run uncomment gate src/ --baseline git:HEAD   # judge only new comments
git diff | uv run uncomment gate --diff -        # judge only what a diff added
uv run uncomment rules                           # list rules
```

Exit codes: `0` clean (or below the `--fail-on` threshold), `1` gated findings,
`2` bad input. Failure is loud by design: nonexistent paths, an unverifiable
`git:` baseline ref, and any invalid config key/type/value all exit `2` with a
named cause — a typo can never produce a silently green gate. Explicitly named
files in unsupported languages are counted in `files_skipped` and noted on
stderr. `uncomment --version` prints the version.

Output is UTF-8 regardless of console codepage; pass `--ascii` (or set
`unicode-output = false`) to transliterate the tool's typography to plain
ASCII for legacy terminals and log processors.

## The two modes

**`check`** scans every comment in the given files/directories.

**`gate`** is the harness workflow: it compares against a baseline — a
directory, a single file, or `git:REF` — and only judges comments that are
genuinely new. Matching is staged so ordinary edits are never re-judged:
exact match within the file, then across the other scanned files (cross-file
moves), then against the rest of the baseline tree when a file has no
counterpart (renames), and finally fuzzy (`baseline-similarity`, default
0.85), so typo fixes and light rewording of an existing comment do not count
as new.

The *comment flood* signal (`UC100`) counts only **noisy** new comment lines —
new comments that triggered at least one finding. Adding a license header,
API docs, or clean WHY-comments never floods; fourteen lines of narration
still does.

The *comment amplification* signal (`UC101`) targets the signature habit of
over-eager agents: seeing existing comments and answering with more. When an
edit adds `growth-min-lines` (6) or more prose comment lines to a file whose
prose comments it at least doubles, UC101 fires on volume alone — even when
every individual comment is worded cleanly enough to evade the per-comment
rules. Documentation and license text never count on either side.

```console
uncomment gate src/parser.c --baseline git:main --format agent
```

**Diff input** (`--diff FILE`, `-` for stdin) takes the edit itself as the
baseline: new content comes from the working tree, old content from
reverse-applying the hunks. No `--baseline` needed, no repository walk — only
the files the diff touched are gated, so it drops straight into any harness
that has the edit as a diff:

```console
git diff | uncomment gate --diff - --format agent
```

Both git diffs (renames, new/deleted files, `diff.mnemonicPrefix`, quoted
paths) and plain unified diffs are accepted; positional paths, when given,
restrict gating to files under them. A diff that no longer matches the
working tree is a hard error (exit `2`) — a stale diff must never silently
mis-judge comments.

## Output formats

- `--format text` — human-readable, one finding per block.
- `--format json` — stable machine schema (`schema_version: 1`): findings with
  `rule`, `severity`, `path`, `line`, `end_line`, `message`, `action`,
  `excerpt`, plus summary counts and gate stats.
- `--format agent` — a ready-to-send corrective prompt: the comment policy,
  then per-file items marked **MUST FIX** (warn/error) or *consider* (hints),
  each with the offending excerpt and the concrete action. Feed this back to
  the agent that made the edit and re-run the gate on its next attempt.
- `--format sarif` — SARIF 2.1.0 for GitHub code scanning and other
  annotators: rule metadata with default levels, per-finding regions and
  snippets, error/warn/info mapped to error/warning/note.

## Rules

| id | severity | catches |
|-------|----------|---------|
| UC001 | warn | comment restates the adjacent code (word-overlap vs. identifiers) |
| UC002 | warn | process narration: "now we…", "first,…", "step 1", numbered steps |
| UC003 | error/warn | edit narration, in two evidence tiers: explicit edit context ("as requested", "the previous version") is an error; a past-tense opener alone ("Simplified X", "Now uses Y") is a warning |
| UC004 | warn | banner / divider comments (`// ======…`) |
| UC005 | warn | commented-out code |
| UC006 | warn | function body saturated with comments (default: >40% and ≥4 lines) |
| UC007 | warn | doc comment that restates the symbol name ("Gets the name." on `get_name`) |
| UC008 | info | **docs-migration hint**: guide-level prose (sections, essays, long file headers) that belongs in project docs or module docs |
| UC009 | warn | trailing comment too long to sit on the code line |
| UC010 | warn | boilerplate labels: "// imports", "// helpers", "// end of loop" |
| UC011 | info | TODO/FIXME without owner or ticket |
| UC012 | warn | emoji/decorative symbols in comments; with `ascii-comments = true`, any non-ASCII character |
| UC100 | error | (gate only) comment flood: edit adds far more *noisy* comment lines than code |
| UC101 | warn | (gate only) comment amplification: edit multiplies a file's prose comments |
| STE01 | info | sentence over 20 words (ASD-STE100 style) |
| STE02 | info | passive voice |
| STE03 | info | non-simple wording ("utilize" → use, "in order to" → to, …) |
| STE04 | info | paragraph over 6 sentences |

What is deliberately **not** flagged: license headers, module/package docs
(Go `doc.go`, Rust `//!`), doc comments with real API content (params, errors,
invariants), short WHY-comments ("because…", "workaround…", links), ASCII
tables and box diagrams, prose invariant sketches, product names that look
like narration ("Let's Encrypt rate-limits renewals" is a fact, "let's
encrypt the payload" is a story), and anything already present in the
baseline.

**Documentation in its rightful place stays.** Doxygen/JSDoc-tagged docs
(`@brief`, `\param`, `@returns`…), rustdoc conventional sections
(`# Examples`, `# Errors`, `# Panics`, `# Safety`), and Google-style
docstring sections (`Args:`, `Returns:`, `Raises:`) mark structured API
documentation; the docs-migration hint leaves them alone, and never suggests
moving doc comments out of interface files (`.h`, `.hpp`, `.d.ts`, `.pyi`) —
that is where they belong. The agent feedback states this policy explicitly
so an agent prunes noise without stripping real docs.

**Python docstrings are doc comments.** A module, class, or function
docstring is extracted as a doc comment attached to what it documents, so
`"""Get the name."""` on `get_name` is flagged as redundant (UC007), a
docstring essay earns the docs-migration hint, and module docstrings are
recognized as the legitimate home for long documentation. Docstring lines
never count as code in the gate's flood/amplification math, and a docstring
is never treated as commented-out code.

`uncomment rules --format json` emits the full rule table (including the
gate-only UC100/UC101) for harnesses that map findings to annotations.

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
fallthrough hints, and `#region`/`#endregion`. For Python: shebangs, PEP 263
encoding declarations, editor modelines, `# noqa`, `# type:` comments,
`# mypy:`/`# pylint:`/`# ruff:`/`# flake8: noqa`, `# fmt: off/on/skip`,
`# isort:`, `# yapf:`, `# pragma: no cover`, `# nosec`, `# noinspection`,
and `# cython:`. Add project-specific ones via `directive-patterns` in the
config.

The exemption is per-line and syntax-checked so noise cannot hide behind it:
a multi-line block comment is only exempt when it contains nothing but the
directive, and pseudo-forms like `NOLINT: <prose>` or `coverage: ignore --
<prose>` are judged like any other comment.

**Disagree with a finding?** Suppress it in place, auditable and scoped:

```c
int x = parse();  // retried upstream, so failure here is fine uncomment-ignore[UC009]: reviewed

// uncomment-ignore[UC005]: kept as a worked example for the FFI docs
// int old = compute();
// use(old);
```

`uncomment-ignore[RULE,RULE]: reason` inside a comment suppresses those rules
for it; a standalone marker comment covers the comment or line directly below.
Without a rule list it suppresses everything in its target. Markers are never
judged and never counted by the gate.

The STE rules are wording guidance inspired by ASD-STE100 (Simplified
Technical English): short sentences, active voice, one simple word per
meaning. They never gate by default; raise them via config if you want them to.

## Configuration

`uncomment.toml` (bare keys or a `[tool.uncomment]` table — both work) or
`[tool.uncomment]` in `pyproject.toml`, discovered upward from the scanned
path. Unknown keys, wrong types, and invalid values are errors, not silent
no-ops.

```toml
[tool.uncomment]
restate-overlap = 0.6              # UC001 word-overlap threshold
ascii-comments = false             # UC012: true = flag ANY non-ASCII in comments
unicode-output = true              # false = ASCII-only tool output (same as --ascii)
max-function-comment-ratio = 0.4   # UC006
doc-migration-lines = 12           # UC008
max-trailing-chars = 60            # UC009
baseline-similarity = 0.85         # gate: this similar to baseline = same comment
flood-ratio = 0.75                 # UC100: noisy new comment lines / new code lines
flood-min-lines = 12
growth-min-lines = 6               # UC101: new prose comment lines to consider amplification
growth-factor = 1.0                # UC101: new prose lines >= factor * existing prose lines
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
instruction, then re-run. No harness-specific coupling. Decide explicitly what
exit `2` (bad path/baseline/config) means for your pipeline: the hook example
below fails open on it; a stricter setup should fail closed.

CI examples:

```console
uncomment gate . --baseline git:origin/main --format agent > comment-feedback.md
git diff origin/main...HEAD | uncomment gate --diff - --format sarif > uncomment.sarif
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
uv run uncomment check src/ tests/test_*.py   # dogfood: CI enforces this
```

The tool lints its own source in CI: `src/` and the test files must stay
clean at warn severity (the corpus files are deliberate noise and stay out of
the scan). The test base is corpus-driven and every change must keep it green:

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
findings unchanged. Baseline access goes through a provider seam
(directory / git / diff); the git provider serves file content from one
`git cat-file --batch` process per repository, so a gate over hundreds of
files costs two subprocesses, not two per file.

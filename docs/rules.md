# Rules

Severities: `info` findings are guidance and never gate by default, `warn`
and `error` gate (see [`--fail-on`](integrations.md#exit-codes) and the
[severity overrides](configuration.md#disable-and-severity) to change that).

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

`uncomment rules --format json` emits this table (including the gate-only
UC100/UC101) for harnesses that map findings to annotations. The gate-only
signals are described in [gate mode](gate.md#gate-only-signals).

## What is deliberately not flagged

License headers, module/package docs (Go `doc.go`, Rust `//!`), doc comments
with real API content (params, errors, invariants), short WHY-comments
("because…", "workaround…", links), ASCII tables and box diagrams, prose
invariant sketches, product names that look like narration ("Let's Encrypt
rate-limits renewals" is a fact, "let's encrypt the payload" is a story),
and anything already present in the baseline.

## Documentation in its rightful place stays

Doxygen/JSDoc-tagged docs (`@brief`, `\param`, `@returns`…), rustdoc
conventional sections (`# Examples`, `# Errors`, `# Panics`, `# Safety`),
and Google-style docstring sections (`Args:`, `Returns:`, `Raises:`) mark
structured API documentation; the docs-migration hint leaves them alone, and
never suggests moving doc comments out of interface files (`.h`, `.hpp`,
`.d.ts`, `.pyi`) — that is where they belong. The agent feedback states this
policy explicitly so an agent prunes noise without stripping real docs.

**Python docstrings are doc comments.** A module, class, or function
docstring is extracted as a doc comment attached to what it documents, so
`"""Get the name."""` on `get_name` is flagged as redundant (UC007), a
docstring essay earns the docs-migration hint, and module docstrings are
recognized as the legitimate home for long documentation. Docstring lines
never count as code in the gate's flood/amplification math, and a docstring
is never treated as commented-out code.

## Tooling directives are never judged

Linter/compiler control comments are functional lines, so no rule sees them,
they are never suggested for removal, and they do not count toward gate/flood
statistics. Recognized out of the box:

- **JS/TS**: `eslint-*`, `@ts-ignore`/`@ts-expect-error`/`@ts-nocheck`,
  `prettier-ignore`, `biome-ignore`, `deno-lint-ignore`, webpack/vite magic
  comments, `@__PURE__`, `sourceMappingURL`, istanbul/c8/v8 coverage markers.
- **C/C++**: `NOLINT*`, `clang-format on/off`, `cppcheck-suppress`,
  `IWYU pragma`, coverity.
- **Go**: `//go:*` (build/generate/embed/linkname/…), `// +build`, `//nolint`,
  `//lint:ignore`, cgo preambles (the comment above `import "C"`).
- **Rust**: rustfmt/compiletest markers.
- **Python**: shebangs, PEP 263 encoding declarations, editor modelines,
  `# noqa`, `# type:` comments, `# mypy:`/`# pylint:`/`# ruff:`/
  `# flake8: noqa`, `# fmt: off/on/skip`, `# isort:`, `# yapf:`,
  `# pragma: no cover`, `# nosec`, `# noinspection`, `# cython:`.
- **Everywhere**: coverage exclusions (`LCOV_EXCL_*`), `NOSONAR`, fallthrough
  hints, `#region`/`#endregion`.

Add project-specific ones via
[`directive-patterns`](configuration.md#directive-patterns) in the config.

The exemption is per-line and syntax-checked so noise cannot hide behind it:
a multi-line block comment is only exempt when it contains nothing but the
directive, and pseudo-forms like `NOLINT: <prose>` or `coverage: ignore --
<prose>` are judged like any other comment.

## Disagree with a finding?

Suppress it in place, auditable and scoped:

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

When the disagreement is about a word rather than a site — a product name or
a domain term the wording rules keep flagging — declare it once in
[`approved-terms`](configuration.md#approved-terms) instead of annotating
every occurrence.

## STE wording rules

The STE rules are wording guidance inspired by ASD-STE100 (Simplified
Technical English): short sentences, active voice, one simple word per
meaning. They never gate by default; raise them via
[severity overrides](configuration.md#disable-and-severity) if you want them
to.

Sentence measurement understands comment structure: doc-tag lines, list
items (`- probe the bus`), and `fast - no checksum` legend lines each count
on their own for the length rule, and the paragraph rule counts only real
`[.!?]`-terminated sentences of flowing prose. Fragments need no terminal
periods — adding periods to line ends is never the fix, and the STE01 action
text says so.

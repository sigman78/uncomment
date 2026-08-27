# Development

```console
uv run pytest
uv run uncomment check src/ tests/test_*.py   # dogfood: CI enforces this
```

## The corpus contract

The test base is corpus-driven and every change must keep it green:

- `tests/corpus/<lang>/agent_noise.*` — files full of agent-style noise, with
  a `.expected.json` sidecar holding the **exact** set of expected warn/error
  findings (a missing one is a recall regression, an extra one is new noise)
  and the hints that must appear.
- `tests/corpus/<lang>/clean.*` — idiomatic, well-commented code that must
  produce **zero** findings of any severity (false-positive guard).
- `test_every_rule_is_exercised` fails if a rule loses corpus coverage.

Precision is tuned against real repositories, and every fixed false positive
earns a line in a `clean.*` file so it cannot return without breaking the
contract.

## Self-linting

The tool lints its own source in CI: `src/` and the test files must stay
clean at warn severity. The corpus files are deliberate noise and stay out of
the scan. STE hints remain visible but never gate — they are guidance by
design.

## Architecture notes

Parsing uses tree-sitter via `tree-sitter-language-pack`. Adjacent line
comments are merged into logical comments, then classified by kind
(line / block / doc — including Go's convention docs and Python docstrings)
and attachment (file header / preceding / trailing / floating /
in-function). Rules operate on that model, not on raw text.

Gate baseline access goes through a provider seam (directory / git / diff);
the git provider serves file content from one `git cat-file --batch` process
per repository, so a gate over hundreds of files costs two subprocesses, not
two per file. Diff input reverse-applies hunks to the working tree to
reconstruct the old content, then reuses the same matching pipeline.

The long-term plan is a Rust port once the Python prototype settles. The
corpus and its expected-findings sidecars are designed to survive the port
unchanged, which is why rules operate on the extracted comment model and why
mechanisms stay deliberately simple (literal term lists, plain regexes, a
provider interface).

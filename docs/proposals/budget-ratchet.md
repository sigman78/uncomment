---
title: Comment-density ratchet (unwaffle budget)
status: draft
created: 2026-08-28
target: 0.17.0
depends: []
tracking: []
---

# Comment-density ratchet (`unwaffle budget`)

## Why

The gate is edit-local: it judges one edit against one baseline. UC100
catches a single flood, UC101 a single amplification spree — but agent noise
in practice accretes *across* edits: each commit adds or enlarges a little,
every step under the per-edit thresholds. Nothing in the current tool can
see the trend.

The ratchet closes that hole by flipping the invariant. Instead of "no
single edit is bad", it enforces "**a file's comment density can never go
up**" — recorded in a committed budget file, checked in CI, tightened
automatically whenever cleanup lowers the number. Slow creep then fails
loudly on the first commit that crosses a file's own recorded high-water
mark, no matter how small the step.

The gate and the ratchet are complementary and both run in CI: the gate
judges the *quality of the new comments* in a PR; the ratchet is the
accretion backstop on *totals*, indifferent to who added what when.

## How

### The metric

Per file: `prose` and `code`, both integers.

- `prose` = the gate's existing prose measure (`_prose_lines` semantics in
  gate.py): line count of visible comments that are neither `Kind.DOC` nor
  license headers, minus suppression-marker lines. Doc comments and license
  text are free by design — the ratchet must never pressure anyone to strip
  documentation, and interface files (`.h`, `.pyi`, `.d.ts`) stay naturally
  unconstrained.
- `code` = `SourceFile.code_line_count`.
- density = `prose / max(code, 1)`, always computed, never stored — the lock
  holds only the two integers, so serialization has no float-formatting
  churn and every diff of the lock is human-readable ("prose went 42→31").

Density rather than an absolute cap, so legitimate growth scales: a file
that doubles its code may double its prose without tripping anything. The
min-lines guard (below) keeps small files from failing on a single added
comment.

### The lock file

`unwaffle.lock`, committed, TOML, maintained by the tool. Lives next to the
config root (the directory whose `unwaffle.toml`/`pyproject.toml` config was
discovered; falls back to the repo top). Paths are repo-relative POSIX,
sorted, LF-terminated — byte-stable across platforms and re-runs.

```toml
# Maintained by `unwaffle budget`. Numbers may only go down
# (`budget tighten`); raising one is a reviewed act, visible in this diff.
version = 1

[files]
"src/display/render.c" = { prose = 42, code = 480 }
"tools/flash.py" = { prose = 7, code = 133 }
```

Only measured integers live in the lock. Thresholds live in config, where
policy belongs.

### Commands

All three share `check`'s discovery and filtering (include/exclude,
respect-gitignore, skip-generated) — the ratchet governs exactly the set of
files a scan would see. Standard `cmd_*` + `set_defaults(fn=...)` wiring.

#### `unwaffle budget init [PATHS]`

Measure the current tree and (re)write the lock as-is. **The only operation
that can loosen a budget**, and it is deliberately manual: the diff of the
lock in the PR is the audit trail. With PATHS, re-inits only those files'
entries (the per-file escape hatch when one file legitimately needs more
prose). Exit 0, or 2 on bad input.

#### `unwaffle budget check [PATHS]`

Measure and compare; never writes. For a file listed in the lock:

```
violation  iff  cur_density > rec_density + budget_tolerance
           and  cur_prose  >= rec_prose + budget_min_lines
```

For a file not in the lock (new file):

```
violation  iff  cur_density > budget_default_density
           and  cur_prose  >= budget_min_lines
```

Lock entries whose file no longer exists are ignored (pruning is tighten's
job). Violations are emitted as findings — rule `UC110 budget-exceeded`,
severity ERROR, anchored at the file's first prose comment, message carrying
the numbers (`comment budget exceeded: density 0.19 vs recorded 0.11 (+4
prose lines over budget)`), action text telling the agent to cut restating/
narrating comments back under the recorded level, not to touch the lock.
All existing output formats work (`--format text|json|agent|sarif`); exit
codes follow the house contract: 0 clean, 1 violations, 2 bad input
(missing lock = bad input, with a hint to run `budget init`).

UC110 joins the `GATE_SIGNALS`-style listing (it is synthesized, not a
registered per-comment rule) so `unwaffle rules` and SARIF metadata cover
it, and the corpus-coverage test is not affected.

#### `unwaffle budget tighten [PATHS]`

Measure; for every scanned file whose current numbers are *better* than the
lock (lower density, or equal density with fewer prose lines), lower the
record. Prune entries for files that no longer exist or are no longer
selected. Never raises anything. Exit 0 (whether or not anything changed;
`--check`-style dry-run flag can come later if wanted).

### Config keys

Following the existing kebab-case/dataclass pattern in `config.py`:

| key | default | meaning |
|-----|---------|---------|
| `budget-tolerance` | `0.02` | density slack over the recorded value before a listed file violates |
| `budget-min-lines` | `4` | minimum prose-line growth (listed) or prose size (new file) for a violation — the small-file guard, mirroring `flood-min-lines`'s role |
| `budget-default-density` | `0.30` | cap for files not in the lock; deliberately loose — the ratchet's power is per-file history, the default only catches egregious newcomers |

### Escape hatches, all auditable

- **Raise one file's budget**: `unwaffle budget init path/to/file.c` — the
  lock diff shows exactly what was granted, in the PR where it happened.
- **Hand-editing the lock** upward works too and is equally diff-visible;
  the file header says so.
- **Suppression**: `unwaffle-ignore-file[UC110]` in a file exempts it, and
  the gate's existing UC102 self-grant notice announces any newly added
  file-wide exception to the reviewer. Span markers cannot reach UC110
  (file-level signal), consistent with UC100/UC101.

What there deliberately is *not*: any automatic loosening. `check` never
writes, `tighten` never worsens, and time alone never relaxes a budget.

### CI recipe

```yaml
- name: Comment budget
  run: uv run unwaffle budget check
```

runs on every PR next to the gate. On the main branch, after merge:

```yaml
- name: Tighten comment budget
  run: |
    uv run unwaffle budget tighten
    git diff --quiet unwaffle.lock || git commit -am "chore: tighten comment budget" && git push
```

so every cleanup becomes irreversible without a reviewed loosening. Solo
repos can skip the bot commit and run `tighten` locally as part of cleanup
PRs — the semantics don't depend on where tighten runs.

The debt-burndown loop composes from existing pieces, no new tool code:
pick the worst files (highest density vs budget), run the comment-fixer
subagent, `unwaffle verify` proves the sweep was comments-only, `budget
tighten` locks in the gain.

### Edge cases

- **Renames**: v1 identity is the path. A renamed file re-enters as "new"
  (default cap — loose, so no false failure) and its old entry is pruned on
  the next tighten; the recorded history is lost. Acceptable for v1; git
  rename-detection could carry entries across later.
- **Deleted files**: ignored by check, pruned by tighten.
- **Generated/excluded files**: never in the lock, never checked — same
  filtering as every other command. Note: files excluded *after* being
  recorded are pruned by tighten like deletions.
- **Empty/new repos**: `budget check` without a lock is exit 2 with a
  pointer to `budget init` — never a silent pass.
- **Line-ending/platform drift**: metrics come from the extractor, which is
  already CRLF-safe; the lock stores integers only, serialized sorted with
  LF — `tighten` on Windows and Linux produces identical bytes.

## Expectations

Once shipped: slow comment accretion fails CI at the first commit that
crosses a file's own recorded high-water mark; cleanup gains are
irreversible without a reviewed lock diff; the gate keeps judging per-edit
quality unchanged.

### Out of scope

The other two longitudinal ideas ride the same seams later: the history
trend sampler (`unwaffle trend`, blob-SHA-cached metrics over sampled
commits) and per-comment lifetime tracking (identity matcher chained across
revisions). Both are diagnosis instruments; the ratchet is the enforcement
and stands alone. Also out: rename-following, per-directory or global
budgets (per-file blocks cross-file laundering; a global number invites it),
and any auto-loosening.

### Tests

`tests/test_budget.py`, unit-level (corpus sidecars do not apply — UC110 is
not a comment-judging rule):

- init → check on unchanged tree is clean; adding prose over tolerance +
  min-lines fails with UC110; adding code without prose stays clean
  (density falls).
- min-lines guard: one added comment on a tiny file stays clean even when
  the ratio jumps.
- new file over/under `budget-default-density`; missing lock exits 2.
- tighten lowers improved entries, prunes deleted ones, never raises;
  serialization is byte-stable (round-trip, sorted, LF).
- per-file `budget init PATH` loosens only that entry.
- `unwaffle-ignore-file[UC110]` exempts; doc-heavy interface file records
  zero prose (DOC exemption holds).
- CLI: exit codes and `--format agent` output shape.

### Checklist

- [ ] `budget.py`: measure, lock read/write (stable serialization), the
      three verbs
- [ ] `config.py`: three `budget-*` keys + validation
- [ ] `cli.py`: `budget` subcommand (init/check/tighten), shared discovery
- [ ] UC110 in the synthesized-signals listing (rules listing + SARIF)
- [ ] `tests/test_budget.py` per the plan above
- [ ] docs: `docs/gate.md` sibling section or new `docs/budget.md`; README
      one-liner; CI recipe in `docs/integrations.md`
- [ ] dogfood: `budget init` + CI check on this repo itself
- [ ] version 0.16.0

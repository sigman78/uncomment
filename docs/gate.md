# Gate mode

`gate` is the harness workflow: it compares against a baseline and only
judges comments that are genuinely new, then emits feedback the harness can
feed straight back to the agent (see
[output formats](integrations.md#output-formats)).

```console
uncomment gate src/parser.c --baseline git:main --format agent
```

## Baselines

The baseline is an older copy of the tree, in one of three forms:

- a **directory** (or a single file),
- a **git ref** via `git:REF` — e.g. `git:HEAD`, `git:main`,
  `git:origin/main`,
- a **unified diff** via `--diff` (see below), where the edit itself is the
  baseline.

An unusable baseline — a nonexistent path, an unverifiable git ref — is a
hard error (exit `2`), never a silent "everything is new". A per-file miss
inside a valid baseline still means "new file" and stays permitted.

## Matching stages

Matching is staged so ordinary edits are never re-judged:

1. exact match against the same file's baseline (whitespace-normalized
   content),
2. exact match against leftover baseline comments from the other scanned
   files (cross-file moves),
3. when a scanned file has no baseline counterpart (renames, file splits),
   exact match against the rest of the baseline tree,
4. fuzzy match (`baseline-similarity`, default 0.85), so typo fixes and
   light rewording of an existing comment do not count as new.

## Gate-only signals

The *comment flood* signal (`UC100`, error) counts only **noisy** new comment
lines — new comments that triggered at least one finding. Adding a license
header, API docs, or clean WHY-comments never floods; fourteen lines of
narration still does. Thresholds: `flood-min-lines` (12) noisy lines and more
than `flood-ratio` (0.75) noisy comment lines per added code line.

The *comment amplification* signal (`UC101`, warn) targets the signature
habit of over-eager agents: seeing existing comments and answering with more.
When an edit adds `growth-min-lines` (6) or more prose comment lines to a
file whose prose comments it at least doubles (`growth-factor`), UC101 fires
on volume alone — even when every individual comment is worded cleanly enough
to evade the per-comment rules. Documentation and license text never count on
either side.

## Diff input

`--diff FILE` (`-` for stdin) takes the edit itself as the baseline: new
content comes from the working tree, old content from reverse-applying the
hunks. No `--baseline` needed, no repository walk — only the files the diff
touched are gated, so it drops straight into any harness that has the edit as
a diff:

```console
git diff | uncomment gate --diff - --format agent
```

Both git diffs (renames, new/deleted files, binary markers,
`diff.mnemonicPrefix`, `--no-prefix`, C-quoted paths) and plain unified diffs
are accepted; positional paths, when given, restrict gating to files under
them. Diff paths resolve against the working directory first, then against
the enclosing repository top (git prints top-relative paths). A diff that no
longer matches the working tree is a hard error (exit `2`) — a stale diff
must never silently mis-judge comments.

## Performance

Baseline access goes through a provider seam (directory / git / diff). The
git provider serves file content from one `git cat-file --batch` process per
repository — both per-file counterparts and the rename sweep — so a gate over
hundreds of files costs two subprocesses, not two per file. A dying
`cat-file` process is a hard error, never a silent "everything is new".

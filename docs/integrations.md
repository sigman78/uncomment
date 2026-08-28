# Output formats and integrations

## Exit codes

`0` clean (or below the `--fail-on` threshold), `1` gated findings, `2` bad
input. Failure is loud by design: nonexistent paths, an unverifiable `git:`
baseline ref, a stale diff, and any invalid config key/type/value all exit
`2` with a named cause — a typo can never produce a silently green gate.
Explicitly named files in unsupported languages are counted in
`files_skipped` and noted on stderr. `--fail-on info|warn|error|never` sets
the lowest severity that causes exit `1` (default: `warn`).
`unwaffle --version` prints the version.

Output is UTF-8 regardless of console codepage; pass `--ascii` (or set
`unicode-output = false`) to transliterate the tool's typography to plain
ASCII for legacy terminals and log processors.

## Output formats

- `--format text` — human-readable, one finding per block.
- `--format json` — stable machine schema (`schema_version: 1`): findings
  with `rule`, `severity`, `path`, `line`, `end_line`, `message`, `action`,
  `excerpt`, plus summary counts and gate stats.
- `--format agent` — a ready-to-send corrective prompt, built to spend as
  little of the receiving agent's context as possible: the policy preamble
  lists only the points whose rules actually fired (guardrails always
  included, plus any [`agent-policy`](configuration.md#agent-policy) house
  rules), and repeated findings group per rule — the fix instruction prints
  once, the sites stay one line each (`×182` findings cost 182 short lines,
  not 182 repeated paragraphs). Items are marked **MUST FIX** (warn/error)
  or *consider* (hints). Feed this back to the agent that made the edit and
  re-run the gate on its next attempt.
- `--format sarif` — SARIF 2.1.0 for GitHub code scanning and other
  annotators: rule metadata with default levels, per-finding regions and
  snippets, error/warn/info mapped to error/warning/note.

`unwaffle rules --format json` emits the machine-readable rule table for
harnesses that map findings to annotations.

## The harness contract

Run the gate after the agent edits; if the exit code is `1`, hand the
`--format agent` output back to the agent as its next instruction, then
re-run. No harness-specific coupling. Decide explicitly what exit `2` (bad
path/baseline/config) means for your pipeline: the hook example below fails
open on it; a stricter setup should fail closed.

## CI

```console
unwaffle gate --baseline git:origin/main --format agent > comment-feedback.md
git diff origin/main...HEAD | unwaffle gate --diff - --format sarif > unwaffle.sarif
```

To surface SARIF findings as GitHub code-scanning annotations:

```yaml
      - name: Comment gate
        run: |
          git fetch origin main
          git diff origin/main...HEAD | uv run unwaffle gate --diff - \
            --fail-on never --format sarif > unwaffle.sarif

      - uses: github/codeql-action/upload-sarif@v4
        with:
          sarif_file: unwaffle.sarif
```

(`--fail-on never` when annotations alone should not fail the build; drop it
to gate.)

## Claude Code

The field-proven setup uses three pieces:

**1. A repo-root `unwaffle.toml`** holding the project's thresholds,
`approved-terms`, and any disabled rules, so every entry point (hook, CI,
manual runs) judges identically.

**2. A PostToolUse hook** (`.claude/settings.json`) that gates each agent
edit against `git:HEAD` and, on findings, blocks the edit and feeds the
corrective prompt back to the agent (exit 2 shows stderr to the agent):

```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Edit|Write",
      "hooks": [{
        "type": "command",
        "command": "sh -c 'f=$(jq -r .tool_input.file_path); uv run unwaffle gate \"$f\" --baseline git:HEAD --format agent 1>&2; [ $? -eq 1 ] && exit 2 || exit 0'"
      }]
    }]
  }
}
```

**3. A thin wrapper script** (e.g. `tools/check_comments.py`) that owns path
scope — which directories are checked, which are skipped (vendored deps,
build output, generated code) — and runs the branch-level gate
(`gate <paths> --baseline git:origin/main --format agent`). The hook keeps
the per-edit loop tight; the wrapper is what CI and humans run.

Two practical notes from real deployments: the gate never re-judges
pre-existing comments, so adopting the tool on a codebase with a large
comment backlog does not block anyone; and the `--format agent` report is
self-contained enough to hand to a cheap subagent that performs just the
comment fixes, keeping the main agent's context clean. The next section
makes that pattern concrete.

## Autonomous comment fixing (subagent + verify)

Comment fixes are among the most mechanical edits in an agent loop — a
mid-tier model handles them reliably (field-proven: a full-tree sweep of 726
findings ran to zero with no code damage). Two pieces make the loop safe
and cheap:

**The verifier.** `unwaffle verify` proves working-tree changes touch
*nothing but comments*: it runs `git diff` itself (against `git:HEAD` by
default, or `--baseline git:REF` — pass a `git stash create` snapshot to
scope the proof to a fixer's own edits amid other uncommitted work;
`--diff FILE|-` verifies an explicit diff instead). Both sides of every
changed file are comment-stripped and the remaining code must be identical
(deletions, binary changes, and unsupported languages count as violations —
conservative by design). Any fixer loop should end with it; if the fixer
drifted into code, the loop reverts instead of trusting. Two caveats:
tooling directives are comments to the verifier, so the fixer's
instructions must forbid touching them — the gate never flags them, so a
findings-driven fixer never will; and `git diff` does not see untracked
files, so a fixer must never create files (the subagent's tool list
enforces Edit-only).

**The fixer subagent** (recipe B — recommended). Save as
`.claude/agents/comment-fixer.md`:

```markdown
---
name: comment-fixer
description: Fixes comment-lint findings from unwaffle. Use when the comment gate reports findings.
tools: Read, Edit, Bash
model: sonnet
---

You fix comment-lint findings and nothing else.

Procedure (unwaffle = `uvx unwaffle` if not installed in the project):
1. Snapshot the tree before touching anything, so step 4 can prove YOUR
   edits are comment-only even amid other uncommitted work:
   `SNAP=$(git stash create); SNAP=${SNAP:-HEAD}`
2. Run `unwaffle gate --baseline git:HEAD --format agent` (no paths —
   the tool asks git for the changed files, scoped by unwaffle.toml).
   Apply every MUST FIX item exactly as its action says. Delete only
   comments; never change code, strings, or tooling directives
   (eslint/noqa/MARK and similar control comments). Consider items are
   optional; apply them when the fix is obvious.
3. Re-run the gate until it exits 0.
4. Prove you touched only comments: `unwaffle verify --baseline git:$SNAP`
   If verify fails, revert your non-comment change and fix again.
5. Report one line: files touched, findings fixed, verify result.
```

The hook then delegates instead of lecturing — the report never enters the
main agent's context at all:

```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Edit|Write",
      "hooks": [{
        "type": "command",
        "command": "sh -c 'f=$(jq -r .tool_input.file_path); uv run unwaffle gate \"$f\" --baseline git:HEAD --format text >/dev/null 2>&1; [ $? -eq 1 ] && { echo \"Comment findings in $f - delegate to the comment-fixer subagent, then re-read the file before further edits.\" 1>&2; exit 2; } || exit 0'"
      }]
    }]
  }
}
```

**Recipe A — the hook fixes autonomously (headless).** Instead of
delegating, the hook itself runs a pinned-model headless session and
verifies, so the main agent never sees the noise at all:

```sh
unwaffle gate "$f" --baseline git:HEAD --format agent > /tmp/report.md || {
  claude -p --model sonnet --allowedTools "Read,Edit" \
    "$(cat /tmp/report.md) Fix only these comments in $f; touch nothing else."
  unwaffle verify || git checkout -- "$f"
  echo "comments auto-fixed in $f - re-read it before further edits" 1>&2
  exit 2
}
```

Trade-offs: per-edit latency rises from ~0.6s to a model call whenever the
fixer engages, and the main agent's copy of the file goes stale — the exit-2
message must tell it to re-read.

**Recipe C — fix at turn boundaries.** For heavy editing sessions, keep the
per-edit hook as a fast tripwire (or drop it) and run the fixer once per
burst — a Claude Code `Stop` hook or a pre-commit hook that gates the whole
diff, invokes the fixer, verifies, and only then lets the turn or commit
complete. Amortizes cost and latency; no mid-edit staleness because the
main agent is idle when it runs.

If the tool is not installed in the project, `uvx unwaffle …` works in both
the hook and CI (about 0.6 s warm start); pin a version (`uvx
unwaffle==0.15.0`) where gate stability matters.

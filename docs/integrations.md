# Output formats and integrations

## Exit codes

`0` clean (or below the `--fail-on` threshold), `1` gated findings, `2` bad
input. Failure is loud by design: nonexistent paths, an unverifiable `git:`
baseline ref, a stale diff, and any invalid config key/type/value all exit
`2` with a named cause — a typo can never produce a silently green gate.
Explicitly named files in unsupported languages are counted in
`files_skipped` and noted on stderr. `--fail-on info|warn|error|never` sets
the lowest severity that causes exit `1` (default: `warn`).
`uncomment --version` prints the version.

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

`uncomment rules --format json` emits the machine-readable rule table for
harnesses that map findings to annotations.

## The harness contract

Run the gate after the agent edits; if the exit code is `1`, hand the
`--format agent` output back to the agent as its next instruction, then
re-run. No harness-specific coupling. Decide explicitly what exit `2` (bad
path/baseline/config) means for your pipeline: the hook example below fails
open on it; a stricter setup should fail closed.

## CI

```console
uncomment gate . --baseline git:origin/main --format agent > comment-feedback.md
git diff origin/main...HEAD | uncomment gate --diff - --format sarif > uncomment.sarif
```

To surface SARIF findings as GitHub code-scanning annotations:

```yaml
      - name: Comment gate
        run: |
          git fetch origin main
          git diff origin/main...HEAD | uv run uncomment gate --diff - \
            --fail-on never --format sarif > uncomment.sarif

      - uses: github/codeql-action/upload-sarif@v4
        with:
          sarif_file: uncomment.sarif
```

(`--fail-on never` when annotations alone should not fail the build; drop it
to gate.)

## Claude Code

The field-proven setup uses three pieces:

**1. A repo-root `uncomment.toml`** holding the project's thresholds,
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
        "command": "sh -c 'f=$(jq -r .tool_input.file_path); uv run uncomment gate \"$f\" --baseline git:HEAD --format agent 1>&2; [ $? -eq 1 ] && exit 2 || exit 0'"
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
comment fixes, keeping the main agent's context clean.

If the tool is not installed in the project, `uvx --from
git+https://github.com/sigman78/uncomment uncomment …` works in both the
hook and CI (about 0.6 s warm start).

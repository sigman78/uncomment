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
- `--format agent` — a ready-to-send corrective prompt: the comment policy,
  then per-file items marked **MUST FIX** (warn/error) or *consider* (hints),
  each with the offending excerpt and the concrete action. Feed this back to
  the agent that made the edit and re-run the gate on its next attempt.
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

## Claude Code hook

`.claude/settings.json` — blocks a noisy edit and shows the feedback to the
agent:

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

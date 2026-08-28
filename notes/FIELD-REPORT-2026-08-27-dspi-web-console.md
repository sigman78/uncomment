# Field report: false positives from a real-repo run (dspi-web-console)

Filed by a Claude Code session running a diagnostic in `D:\non-esp\dspi-web-console`
(TypeScript + Svelte web app for a DSP device console; wire-protocol-heavy code).

- Version: uncomment 0.10.0, installed via `uvx --from git+https://github.com/sigman78/uncomment uncomment`
- Command: `uncomment check src test scripts --fail-on never`
- Result: 230 files scanned — 1 error, 80 warnings, 476 hints

This note covers only the findings verified as false positives against the source.
Each item is written as an issue with a verbatim repro.

---

## Issue 1 — UC003: "previous <runtime-noun>" triggers the edit-narration ERROR

**Severity of impact: high** — this was the only error-level finding in the entire
run, and it is wrong. In gate mode an error blocks, so error-tier precision matters
most.

**Tool output:**

```
src\runtime\actions.ts:1056: [error] UC003 comment describes the edit, not the code ('as requested', 'the previous version'...)
    > Drop any previous result synchronously, BEFORE the device round-trip:
    fix: Delete this comment. Edit history belongs in the commit message, not in the source.
```

**Actual source (src/runtime/actions.ts:1055-1059):**

```ts
export async function csIrLearnArm(s: ReadySession): Promise<boolean> {
  // Drop any previous result synchronously, BEFORE the device round-trip:
  // the panel's completion effect runs during the await, and a stale
  // DONE/TIMEOUT would complete the new learn instantly with the old code.
  s.controlSurfaces.irLearn = null;
```

**Analysis:** The comment is an imperative, present-tense WHY comment documenting a
race condition — exactly the kind the tool promises to keep. The trigger appears to
be "previous result" matching an edit-context marker in the family of "the previous
version". But "previous/old/stale + noun" overwhelmingly refers to *runtime data*
(previous result, old value, stale cache), especially in async/state-machine code.

**Suggested direction:** Require the edit-context vocabulary to reference code or
versioning specifically ("previous version/implementation/code", "as requested",
"per review"), and/or suppress when the sentence opens with an imperative verb —
imperative mood describes what the code does, not what an edit did.

---

## Issue 2 — UC003: adjectival participle at sentence start read as past-tense opener

**Tool output:**

```
src\domain\snapshotDiff.ts:245: [warn] UC003 comment starts like edit narration ('changed/simplified/now uses...')
    > Fixed input x output grid; iterate the live side. A route in `b` but
```

**Actual source (src/domain/snapshotDiff.ts:245-249):**

```ts
  // Fixed input x output grid; iterate the live side. A route in `b` but
  // absent in `a` counts as a change.
  for (let i = 0; i < b.routes.length; i++) {
    const ra = a.routes[i];
    if (ra === undefined || routeDiffers(ra, b.routes[i])) out.push({ kind: 'route', index: i, value: b.routes[i] });
```

**Analysis:** "Fixed" here is the adjective (fixed-size grid), not the verb "fixed
(a bug)". The past-tense-opener heuristic misfires on participial adjectives heading
a noun phrase. "Fixed/Given/Derived/Sorted/Packed <noun>..." are common comment
openers in technical prose.

**Suggested direction:** When the opening participle directly premodifies a noun
phrase and the clause has no object/complement structure of an edit description
("Fixed the race", "Fixed handling of X"), don't count it as a past-tense opener.
A small allowlist of adjectival participles (fixed, given, sorted, packed, derived,
bounded...) followed by a noun would cover most of it.

---

## Issue 3 — UC005: byte-layout and math annotations classified as commented-out code

**Scope:** ~8 of the 11 UC005 hits in this repo are not disabled code — they are
annotations of binary fixtures, wire layouts, enum encodings, or math identities.
This will be systematic in any wire-protocol / DSP / embedded-adjacent codebase.

**Example A — packet annotation above a binary fixture** (the same shape recurs at
notifyChannel.test.ts:247, 326, 339, 352, 366, 384):

```
src\runtime\notifyChannel.test.ts:101: [warn] UC005 commented-out code (1 of 1 lines look like code)
    > PARAM_CHANGED, source=HOST(1), size=0
```

```ts
    // PARAM_CHANGED, source=HOST(1), size=0
    mock.pushNotify(new Uint8Array([2, 2, 0, 1, 0x80, 0x0b, 0, 0, 1, 0, 0, 0]));
```

The comment is the only human-readable decoding of the byte array under it. Deleting
it (the suggested fix) would strictly hurt the code.

**Example B — arithmetic explaining an expected test value:**

```
src\device\DspDevice.v22.test.ts:32: [warn] UC005 commented-out code (1 of 1 lines look like code)
    > qp = round(1.5*512) = 768, little-endian at bytes 16-17.
```

```ts
    // qp = round(1.5*512) = 768, little-endian at bytes 16-17.
    const qpRaw = call!.data[16] | (call!.data[17] << 8);
    expect(qpRaw).toBe(768);
```

**Example C — wire-layout gloss for a reply being built:**

```
src\transport\MockTransport.ts:709: [warn] UC005 commented-out code (1 of 1 lines look like code)
    > {current pipeline Hz, selected I2S input Hz}
```

```ts
      case WireCmd.GetInputRate.code: {
        // {current pipeline Hz, selected I2S input Hz}
        const out = new Uint8Array(8);
        const dv = new DataView(out.buffer);
        dv.setUint32(0, 48_000, true);
        dv.setUint32(4, this.#i2sRateHz(), true);
```

**Example D — DSP math identity (a WHY comment):**

```
src\components\bode\xoverCurve.ts:62: [warn] UC005 commented-out code (1 of 1 lines look like code)
    > LR(N) = BW(N/2) squared: every half-order pole doubled.
```

```ts
    case 'lr': {
      // LR(N) = BW(N/2) squared: every half-order pole doubled.
      const half = meta.order >> 1;
      const bw = butterworthPairs(half);
```

**Example E — multi-line enum/wire-convention doc** (`src/domain/platform.ts:19`,
flagged "2 of 4 lines look like code"): lines like `0 = unified (...)`, `1 = split
(...)` documenting a wire encoding on a struct field.

**Analysis:** The code-likeness classifier appears to key on `=`, `NAME(N)`, and
`{...}` shapes. Those are exactly the shapes of legitimate byte-layout and encoding
annotations. Possible distinguishers:

- Real commented-out code usually **parses** as the file's language — tree-sitter is
  already a dependency, so try parsing the comment text as a statement/expression of
  the host language and require a reasonably clean parse before flagging.
- `key=value(N), key=value` comma lists and `N = meaning` glosses are not statements
  in any supported language.
- Annotations tend to sit directly above live code that shares their identifiers /
  numeric literals (768, 0x80 …); genuinely disabled code duplicates *structure*,
  not values referenced by the adjacent live line.

Per-repo `exclude` is too blunt a workaround here: the same files also contain
genuine UC005/UC001 hits worth keeping.

---

## Appendix — not false positives, but noticed during the run

- **Silent language skip:** 70 `.svelte` files under `src/` were skipped with no
  mention in the summary ("230 file(s) scanned" only). A `N file(s) skipped
  (unsupported language)` line would make coverage gaps visible.
- **PyPI name collision:** `uvx uncomment` installs an unrelated `uncomment` 3.5.2
  from PyPI (a Rust comment stripper). README's quick-start should show the
  `uvx --from git+https://github.com/sigman78/uncomment uncomment ...` form until
  the name situation is resolved.

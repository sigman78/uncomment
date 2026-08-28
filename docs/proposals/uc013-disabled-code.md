---
title: UC013 disabled-code — constant-false regions are commented-out code
status: draft
created: 2026-08-28
target: 0.16.0
depends: []
tracking: []
---

# UC013 `disabled-code`

## Why

UC005 catches disabled code only when it hides behind comment markers,
because rules judge extracted `Comment` objects and nothing else. Every
language has at least one way to disable code without a comment marker, and
tree-sitter parses the disabled body as ordinary code. Two consequences:

1. **Evasion**: an agent that wraps code in `#if 0` instead of commenting it
   out passes UC005 untouched.
2. **Metric pollution**: the disabled lines count toward `code_line_count`,
   so in gate mode a new `#if 0` block *inflates* `added_code_lines` — the
   denominator of the UC100 flood ratio. Disabling code doesn't just evade;
   it dilutes the flood signal.

`verify` is already correct here: disabled regions stay in the code
fingerprint, so a comment-fixer that edits them is flagged as a code change.
That behavior must not change.

## How

### Survey: unconditional disable constructs per supported language

Verified against the tree-sitter grammars in `tree-sitter-language-pack`
(probe scripts, 2026-08-28). "In scope" means the construct is provably
constant-false from syntax alone — no build-system knowledge needed.

| language | construct | AST shape (verified) | scope |
|----------|-----------|----------------------|-------|
| C / C++ | `#if 0` … `#endif` (also `#if false`) | `preproc_if` with condition child `number_literal` `0` / identifier `false`; body parsed as real code | **in** |
| C / C++ | `#else` branch of `#if 1` / `#if true` | `preproc_else` child of a `preproc_if` whose condition is `1`/`true` | **in** |
| C / C++ | `#ifdef NEVER`, `#if defined(X)` | `preproc_ifdef` / `preproc_defined` — truth depends on the build | out |
| C# | `#if false` … `#endif` | `preproc_if` with `boolean_literal` `false`; body parsed as real code | **in** |
| C# | `#else` branch of `#if true` | `preproc_else` child, same as C | **in** |
| C# | `#if SOME_SYMBOL` | condition is `identifier` — build-defined | out |
| Swift | `#if false` … `#endif` | **flat** `directive` nodes (no nesting in this grammar): `#if` with `boolean_literal` `false`, siblings up to the matching `#endif` | **in** |
| Swift | `#if os(macOS)`, `#if DEBUG` | `directive` with `os(...)` / `simple_identifier` condition | out |
| Rust | `#[cfg(any())]` on an item | `attribute_item` → `attribute` (`identifier` `cfg` + `token_tree` `(any())`); the disabled item is the **next sibling** | **in** |
| Rust | `if false { … }` | `if_expression` with condition `boolean_literal` `false` | **in** |
| Rust | `#[cfg(FALSE)]` | identifier condition — conventionally never defined, but not provable | out |
| Python | `if False:` / `if 0:` | `if_statement` with condition node `false` / `integer` `0` | **in** |
| Python | bare string wrapping code (non-docstring) | `string` in statement position, not first statement of module/def/class | **in**, code-ish test required |
| Java | `if (false) { … }` | `if_statement`, condition `parenthesized_expression` → `false` (JLS 14.21 explicitly permits this as the Java `#if 0` analogue) | **in** |
| JS / TS / TSX | `if (false)` / `if (0)` | `if_statement`, `parenthesized_expression` → `false` / `number` `0` | **in** |
| JS / TS | `false && expr()` | `binary_expression` — expression-level, `DEBUG && log()`-shaped FP risk | out |
| Go | `if false { … }` | `if_statement` with condition `false` | **in** |
| Go | `//go:build ignore` | legitimate generator/example convention | out |
| Kotlin | `if (false) { … }` | `if_expression` with `boolean_literal` `false` | **in** |
| all C-likes | `do { … } while (0)` | macro hygiene idiom; a `do_statement`, never an `if` — naturally outside the detector | out (must stay clean) |
| all | unreachable code after `return`/`throw` | compiler/linter territory, not comment hygiene | out |

Runtime `if (true) { } else { dead }` is out for v1 everywhere: the toggle
idiom in practice is the preprocessor form; the runtime form is rare and the
else-branch analysis doubles the surface for little recall.

### Rule definition

```
UC013  disabled-code  WARN
Code disabled by a constant-false condition or dead branch instead of being deleted.
```

Message: `disabled code: {construct} spans {n} lines`
(e.g. `disabled code: '#if 0' spans 12 lines`,
`disabled code: dead '#else' branch of '#if 1' spans 4 lines`).

Action: `Delete it or gate it on a real condition. Version control preserves
removed code; a constant-false guard is commented-out code wearing different
syntax.`

Severity WARN, matching UC005 — same disease, different marker.

#### Firing conditions

- The region's disabled body has **≥ 1 non-blank line** (an empty
  `if (false) {}` scaffold is skipped — nothing is being preserved).
- Preprocessor / cfg / if-false regions fire **unconditionally**: the
  construct itself is the evidence; no code-ish heuristic needed.
- Python bare strings fire only when the string content passes UC005's
  code-ish test (same thresholds: ≥2 lines with `codeish/len >=
  code_line_fraction` and `codeish >= 2`, or 1 line matching
  `_looks_like_code(strong_only=True)`). Prose bare strings used as block
  comments never fire.
- Nested regions collapse to the **outermost**: one finding per maximal dead
  region (`#if 0` containing another `#if` yields one finding).

#### Finding anchor

`line` = first line of the construct (`#if 0` line, `if (false)` line,
`#[cfg(any())]` line, `#else` line for a dead else-branch);
`end_line` = last line of the construct (`#endif`, closing brace, end of the
attributed item). The full span makes suppression ergonomic: a standalone
`unwaffle-ignore[UC013]: reason` comment on the line above covers the
anchor, and the existing overlap check in `_suppressed` does the rest —
no suppression changes needed.

#### `#elif` correctness detail (C/C++)

The dead region of `#if 0` ends at the first `preproc_elif` /
`preproc_else` child — those alternatives may be live. Symmetrically, only
the `preproc_else` of a constant-**true** `#if` is dead; `#elif` chains are
not analyzed further in v1.

### Architecture

#### Extraction (`extract.py`, `model.py`)

Rules receive a `SourceFile`, not a tree, so extraction must surface the
regions. New dataclass in `model.py`:

```python
@dataclass
class DisabledRegion:
    path: str
    construct: str      # "#if 0" | "#else of #if 1" | "#[cfg(any())]" | "if (false)" | "bare-string"
    start_line: int     # 1-based, first line of the construct (finding anchor)
    end_line: int       # last line incl. #endif / closing brace
    body_start: int     # first disabled line
    body_end: int       # last disabled line
    body: str           # disabled body text (gate matching + code-ish test)
```

`SourceFile` gains `disabled_regions: list[DisabledRegion]` and
`disabled_line_count: int` (non-blank body lines that are currently counted
in `code_line_count`).

Collection rides the existing single tree walk in `extract_source`:

- **c/cpp/csharp**: on `preproc_if`, inspect the condition child; constant
  false → region up to first `preproc_elif`/`preproc_else`/`#endif`;
  constant true → the `preproc_else` child (if any) is a region. Do not
  descend into a dead body looking for nested regions.
- **rust**: on `attribute_item` whose attribute normalizes
  (whitespace-collapsed) to `cfg(any())`, the next non-attribute named
  sibling is the region. `cfg(all())` is constant-TRUE — never flag.
  Also `if_expression` with `boolean_literal` false. Inner attribute
  `#![cfg(any())]` (whole-file disable) is out of scope v1.
- **swift**: the grammar emits **flat** `directive` nodes; a linear pass
  pairs `#if`/`#endif` with a depth counter, bounds the dead region at a
  same-depth `#elseif`/`#else`, and marks the sibling span of a
  `boolean_literal false` condition.
- **js/ts/tsx/java/go/kotlin/python (+ c-likes)**: `if_statement` /
  `if_expression` whose condition — after unwrapping
  `parenthesized_expression` — is exactly the `false` node (or `0` literal:
  `integer` in Python, `number` in JS/TS, `number_literal` in C/C++). A
  compound condition (`false && x`) never matches: the condition child is a
  `binary_expression`, not the literal.
- **python bare strings**: a `string` in statement position that is not in
  the docstring set the walk already computes. Recorded as construct
  `"bare-string"`; the rule applies the code-ish test.

Comments inside a disabled region stay in the comment stream and are judged
normally. A `#if 0` block containing a narration comment yields UC013 plus
UC002 — both true, and the fix (delete the block) resolves both.

#### Rule (`rules/core.py`)

Trivial once extraction does the work:

```python
@rule("UC013", "disabled-code", Severity.WARN,
      "Code disabled by a constant-false condition or dead branch instead of being deleted.")
def disabled_code(sf: SourceFile, cfg: Config) -> Iterable[Finding]:
    for r in sf.disabled_regions:
        ...  # empty-body skip; bare-string code-ish test; yield Finding
```

No new config keys: `disable`/severity overrides and both `unwaffle-ignore`
marker forms apply through the existing machinery.

### Gate integration (`gate.py`)

UC013 findings are region-anchored, but `_finalize` filters findings by
overlap with **unmatched comment** spans — without changes, gate mode would
drop every UC013 finding. Changes:

1. **Region newness.** `_FileState` gains `unmatched_regions`. Matching is
   per-file exact only: normalize `construct + body` with the same `_WS_RE`
   collapse used for comments; a region present in the baseline file is not
   new. No cross-file or fuzzy stages in v1 — a moved or lightly reworded
   `#if 0` block counts as new, which is fine: it should be deleted anyway.
2. **`touches_new`** accepts a UC013 finding when it overlaps an unmatched
   region span; all other rules keep the comment-span filter unchanged.
3. **Metric correction.** `added_code_lines` becomes
   `max(0, new_live - old_live)` where
   `live = code_line_count - disabled_line_count`. A new `#if 0` block no
   longer inflates the UC100 denominator. (`code_line_count` itself is
   untouched — scan-mode stats and UC006 keep their meaning.)

`verify` is deliberately unchanged: disabled regions remain part of the code
fingerprint, so a fixer that rewrites `#if 0` content still fails the
comments-only proof.

## Expectations

Once shipped: `#if 0`/`cfg(any())`/`if (false)` regions warn like the
commented-out code they are, in scan and gate alike; a new disabled block no
longer inflates `added_code_lines` (UC100 denominator); `verify` still
treats disabled regions as code.

### Corpus plan

Corpus contract as usual: exact `(rule, line)` sets in `.expected.json`,
clean files stay at zero findings. **Append** all snippets at end-of-file so
existing expected line numbers stay valid; each addition contributes one
`["UC013", <line>]` entry (line numbers fixed at implementation time).
`test_every_rule_is_exercised` then covers UC013 automatically.

#### agent_noise additions (one UC013 each unless noted)

`c/agent_noise.c` — two findings, anchor at `#if 0` and at `#else`:

```c
#if 0
static int legacy_sum(int a, int b) {
    return a + b;
}
#endif

#if 1
static int active_path(int v) { return v; }
#else
static int shelved_path(int v) { return -v; }
#endif
```

`cpp/agent_noise.cpp`:

```cpp
#if 0
int legacy_scale(int v) { return v * 2; }
#endif
```

`csharp/agent_noise.cs` (inside the class):

```csharp
#if false
    private int LegacyScale(int v) => v * 2;
#endif
```

`swift/agent_noise.swift`:

```swift
#if false
func legacyScale(_ v: Int) -> Int { return v * 2 }
#endif
```

`rust/agent_noise.rs` — two findings, anchor at the attribute and at `if false`:

```rust
#[cfg(any())]
fn legacy_scale(v: u32) -> u32 { v * 2 }

fn probe_disabled(v: u32) -> u32 {
    if false {
        return v * 2;
    }
    v
}
```

`python/agent_noise.py` — two findings, anchor at `if False:` and at the
opening quotes:

```python
if False:
    result = legacy_scale(value)
    emit(result)

"""
value = legacy_scale(raw)
emit(value)
"""
```

`java/agent_noise.java` (inside the class):

```java
    void probeDisabled() {
        if (false) {
            legacyEmit();
        }
    }
```

`js/agent_noise.js`:

```javascript
if (false) {
    legacyEmit();
}
```

`ts/agent_noise.ts` — the `0` variant:

```typescript
if (0) {
    legacyEmit();
}
```

`tsx/agent_noise.tsx`:

```tsx
if (false) {
    legacyEmit();
}
```

`go/agent_noise.go`:

```go
func probeDisabled(v int) int {
    if false {
        return v * 2
    }
    return v
}
```

`kotlin/agent_noise.kt`:

```kotlin
fun probeDisabled(v: Int): Int {
    if (false) {
        return v * 2
    }
    return v
}
```

#### clean-file guards (must stay at zero findings)

- `c/clean.c`: `#ifdef _WIN32` platform guard; `#define ONCE(x) do { x; }
  while (0)`; `#if 1 … #endif` with **no** `#else`.
- `csharp/clean.cs`: `#if DEBUG … #endif`.
- `swift/clean.swift`: `#if os(macOS) … #endif` and `#if DEBUG … #endif`.
- `rust/clean.rs`: `#[cfg(test)] mod tests`, `#[cfg(feature = "extra")]`,
  and the adversarial constant-true cousin `#[cfg(all())]`.
- `python/clean.py`: `if TYPE_CHECKING:` guard; a bare **prose** string in
  non-docstring position (block-comment habit — fails the code-ish test).
- `java/clean.java`: `if (DEBUG)` on a `static final` field (identifier
  condition, naturally clean — present as a regression tripwire).
- `js/clean.js`: `if (process.env.DEBUG)` conditioned block.

#### gate tests (`tests/test_gate.py`)

- Baseline contains an `#if 0` block, edit leaves it alone → no UC013.
- Edit introduces an `#if 0` block → UC013 present in gate findings.
- Edit wraps N existing code lines in `#if 0` → `added_code_lines` does not
  grow by N (metric-correction proof).
- `unwaffle-ignore[UC013]` on the line above the region suppresses it.

### Out of scope

`#ifdef NEVER` and every identifier-conditioned form (C `defined(X)`, C#
symbols, Swift `#if DEBUG`, Rust `#[cfg(FALSE)]`); expression-level disables
(`false && f()`); `while (false)` and `do…while(0)`; Go `//go:build ignore`;
runtime `if (true) … else`; `#elif` reachability chains; unreachable code
after `return`/`throw`. Each is either build-dependent, an established
idiom, or another tool's job. Revisit `#[cfg(FALSE)]` (exact-name form) if
field reports show it in agent output.

### Checklist

- [ ] `model.py`: `DisabledRegion`, `SourceFile.disabled_regions`,
      `SourceFile.disabled_line_count`
- [ ] `extract.py`: per-grammar collectors (preproc, cfg-attr, swift linear
      directive pass, if-false, bare strings)
- [ ] `rules/core.py`: UC013 rule (empty-body skip, bare-string code-ish test)
- [ ] `gate.py`: region matching, `touches_new` extension, `added_code_lines`
      correction
- [ ] corpus: 12 agent_noise additions + expected entries, clean guards
- [ ] `tests/test_gate.py`: the four gate cases above
- [ ] `docs/rules.md`: table row + a short section with the suppression example
- [ ] version bump 0.15.0, changelog

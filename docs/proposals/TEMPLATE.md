# Proposal template

Every file in `docs/proposals/` follows this shape. Copy, fill, delete the
guidance comments. `Why`, `How`, and `Expectations` are mandatory; the other
sections appear when they have real content — an empty "Alternatives" is
noise, a missing "Backward compatibility" on a behavior change is a hole.

```markdown
---
title: Short noun-phrase name of the change
status: draft        # draft -> accepted -> implemented | rejected | superseded
created: YYYY-MM-DD
target: 0.X.0        # intended release, or TBD
depends: []          # proposals/features this builds on, e.g. ["uc013-disabled-code"]
tracking: []         # PR/issue links once implementation starts
---

# <title>

## Why

The problem, the evidence it is real, and why the current tool cannot
already handle it. If a user decision shaped the scope (hard cut, severity
tier), record it here with the date.

## How

The design. Free-form subsections (`###`) — detection mechanics, file
formats, command surface, config keys, edge cases. Verified facts (AST
shapes, measured numbers) beat assumptions; say which is which. Performance
notes belong here when the change touches a hot path (gate over hundreds of
files, history walks).

## Backward compatibility        <!-- when the change alters observable behavior -->

What existing users see differently: findings that appear or move on
unchanged trees, gate metrics that shift, config/marker/exit-code contract
changes, migration steps if any. New files or formats state their
versioning story. Include a **Rust port** note: which seam the change rides
and whether anything about it is Python-specific — the corpus and every
committed format must survive the port unchanged.

## Alternatives considered       <!-- optional -->

Designs that were rejected, each with the reason — especially ones a future
reader would otherwise re-propose.

## Expectations

Open with the observable outcomes: what fails/passes differently once this
ships, in one short paragraph.

### Out of scope

What this deliberately does not do, each with its reason.

### Tests

How correctness is proven — corpus additions with expected findings, unit
tests, gate cases.

### Checklist

- [ ] implementation steps, docs, version bump

## Open questions                <!-- optional, drafts only -->

Unresolved decisions blocking `accepted`; resolve and delete before
implementation starts.
```

Status semantics: `draft` = being shaped, `accepted` = agreed to build,
`implemented` = shipped (set `target` to the actual release and fill
`tracking`), `rejected`/`superseded` = kept for the record with a line
saying why.

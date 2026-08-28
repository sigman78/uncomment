# Proposal template

Every file in `docs/proposals/` follows this shape. Copy, fill, delete the
guidance comments.

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
shapes, measured numbers) beat assumptions; say which is which.

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
```

Status semantics: `draft` = being shaped, `accepted` = agreed to build,
`implemented` = shipped (set `target` to the actual release and fill
`tracking`), `rejected`/`superseded` = kept for the record with a line
saying why.

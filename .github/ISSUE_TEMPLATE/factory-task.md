---
name: Factory work order
about: A work order for the factory; the issue number is its ID
title: ''
labels: ''
assignees: ''
---

*A work order for the factory ([way of working](https://github.com/Zerosteps1/Aicepeak_V2.0.0/blob/testing/docs/way-of-working.md)). Only issues opened by a configured maintainer count. Fill in the sections and delete the guidance in italics, then comment `/review`: the factory proposes `allowed_paths` and fixes for weak or missing sections, which you copy into this description by hand. A maintainer's `/accept` writes the proposed paths into the block below and approves the work order. Any later edit of the title or the description withdraws the approval until it is accepted again (`/review`, then `/accept`). Then: `factory start workorder <issue number>`. One work order is one PR: its branch is `<issue number>-<title words>` (as GitHub's "Create a branch" names it), its PR says `Closes #<issue number>`, and merging it into `testing` closes this issue; follow-up work is a new work order.*

```factory-task
{"status":"draft","kind":"factory","allowed_paths":[]}
```

*Block rules: exactly one block; exactly the keys `status`, `kind` and `allowed_paths`; no comments inside the JSON. Only the factory sets `status` to `approved`, after `/accept`. `kind`: `factory` (factory work), `product` (blocked until `northstar_approved` and `product_checks_ready` are true in `factory/config.json`) or `smoke` (controlled fixtures only); it decides the validation branch the implementation targets. `allowed_paths`: repository-relative files, or directory prefixes ending in `/`, that the implementation may change; leave it empty for the factory's proposal or write your own as a starting point. Paths in `protected_paths` are control paths that the isolated author cannot write.*

requirements: []

*North star requirement IDs (`AIC-NNN`) this work order implements. Mandatory for `kind: product`; keep `requirements: []` for factory and smoke work.*

## Goal

*One or two sentences: the observable outcome for the user or maintainer once this work order is done.*

## Non-goals

- *What this work order deliberately does not change (neighbouring features, refactors, other requirements, product scope not in the north star).*

## Context and constraints

*Relevant existing files, decisions (`docs/decisions/`), north star sections and known risks. Mark unresolved decisions as open; do not fill them with defaults.*

## Acceptance criteria

*One observable, testable statement per line, for example in EARS style ("When <trigger>, the <component> shall <response>." / "If <condition>, then the <component> shall <response>."). Include the negative cases that matter (wrong input, missing data, stale state).*

1. AC-1: When ..., the ... shall ....
2. AC-2: If ..., then the ... shall ....

## Verification

*Exact commands from the repository root and the output that proves success. A claim without command and output is not evidence.*

```sh
python3 -I -m unittest discover -s tools/factory/tests
python3 tools/factory/verify.py --root .
```

## Open questions

- *Questions that block or shape the implementation, with the person who decides.*

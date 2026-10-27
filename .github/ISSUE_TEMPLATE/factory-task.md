---
name: Factory task
about: Define a bounded task before an author run
title: ''
labels: ''
assignees: ''
---

Describe the outcome, acceptance criteria, scope limits, and an existing `docs/work/NAME.md` task. Assign a configured verified human owner.

Author handoff (exact fields; values must be replaced):

```json
{"runner":"codex","task":"docs/work/NAME.md","owner":"verified login"}
```

Allowed runner values: `codex`, `claude`. This handoff contains no shell command and does not authorize merging.

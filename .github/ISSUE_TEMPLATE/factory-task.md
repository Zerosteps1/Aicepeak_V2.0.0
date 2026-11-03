---
name: Factory task
about: Propose a bounded task; the work order itself is a file in docs/work/
title: ''
labels: ''
assignees: ''
---

An issue does not authorize factory work: work orders are files in `docs/work/`, approved and merged to `main`. Describe the outcome, acceptance criteria and scope limits here for discussion, and assign a configured verified human owner.

A maintainer then creates the work order with `factory issue` and activates it with `factory submit workorders` (see the [factory command reference](https://github.com/Zerosteps1/Aicepeak_V2.0.0/blob/main/docs/factory-cli.md#factory-issue)). The implementing PR gets its handoff from `factory submit --finished` (exact fields; values must be replaced):

```json
{"runner":"claude","task":"docs/work/NAME.md","owner":"verified login"}
```

Allowed runner value: `claude` (`runners` in `factory/config.json`). This handoff contains no shell command and does not authorize merging.

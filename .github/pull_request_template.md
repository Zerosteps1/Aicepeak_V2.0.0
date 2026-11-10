## Work order and intent

Work order: #57

Closes #57

Replace `57` with the number of the approved work-order issue. One work order is one PR: `Closes #57` links this PR to its issue, and merging it into `testing` closes the issue. Describe the intended outcome and what changed.

## Validation

Record the checks performed and any limits. The factory reports the deterministic tests and the senior review as separate checks; a maintainer merges with `factory merge` once the required checks are green and the review threads are resolved (no second human approval is required).

## Author handoff

`factory submit --finished` writes this block for you. Otherwise replace the values below with the approved work-order issue and a verified configured maintainer as owner. Use the configured runner allowlist (currently `claude`; the Business-authenticated isolated Codex author is not yet verified). Do not add commands or credentials.

```factory-handoff
{"runner":"claude","task":"#57","owner":"verified login"}
```

Human feedback can be left as PR comments or review comments. The factory acknowledges eligible maintainer feedback and reports its outcome; it does not resolve review threads automatically.

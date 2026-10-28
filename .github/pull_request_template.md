## Task and intent

Task: `docs/work/NAME.md`

Describe the intended outcome and what changed.

## Validation

Record the checks performed and any limits. The factory reports deterministic tests and senior review separately; a human code owner approves and merges.

## Author handoff

Replace the values below with an existing task and a verified configured human owner. Use the configured runner allowlist (currently `claude`; the Business-authenticated isolated Codex author is not yet verified). Do not add commands or credentials.

```factory-handoff
{"runner":"claude","task":"docs/work/NAME.md","owner":"verified login"}
```

Human feedback can be left as PR comments or review comments. The factory acknowledges eligible maintainer feedback and reports its outcome; it does not resolve review threads automatically.

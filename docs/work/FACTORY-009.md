# FACTORY-009 – Issues as workorders

```factory-task
{"status":"approved","kind":"factory","allowed_paths":["factory/", ".github/", "docs/"]}
```

## Goal

Workorders can be issued by humans by creating issues containing a factory-task block.

using `factory issue` command creates a github issue using the factory-task template.

as every issue on github already has an unique id, use that (talking about the #37 for example).

When the issue was created by the human, an agent (probably sonnet) should propose the allowed paths in a comment on the issue, when reacted with a :thumbs_up: by a maintainer they are accepted. In that case the AI adapts the issue's description (visibly in issue description history as the factory)
Likewise the agent should create another issue that talks about possible problems based on the issue's sections, like unclear formulations. It should always propose a solution. Similar if any section is lacking or missing, it should propose them. In that case the human would have to manually edit the issue description using copy paste.

## Non-goals

The factory does not create github issues itself, only humans do.

## Context and constraints



## Acceptance criteria

*One observable, testable statement per line, for example in EARS style ("When <trigger>, the <component> shall <response>." / "If <condition>, then the <component> shall <response>."). Include the negative cases that matter (wrong input, missing data, stale state).*

1. AC-1: When an issue WITH a `factory-task` block is created on github, the issue reviewer shall review the issue's description and propose the allowed paths as well as fixes for the sections.
2. AC-2: If the issue reviewer's suggestion receives a :thumbs_up: by a maintainer, then the allowed paths shall be updated in the issue's description.
3. AC-3: If an agent makes changes to the issue's description or posts a comment, it is visibly coming from the factory and it shows as such in the issue's description's history.

## Verification

## Handoff

```factory-handoff
{"runner":"claude","task":"docs/work/FACTORY-009.md","owner":"ftrutschnig"}
```

## Open questions

* How to start the issue reviewer on github
* How to let the issue reviewer adapt the issue when instructed to do so.
* How to let the issue reviewer be shown as such in the github UI

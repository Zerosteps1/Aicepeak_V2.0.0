# Contributing

Read `AGENTS.md`, the [policy](factory/policy.md) and `factory/config.json`. Start the isolated client as described in the [README](README.md); work with fresh context and on your own branch. A product task needs the approved canonical north star and matching product checks. Missing foundations are reported as blockers.

## Task → change → review

1. `factory-start`: record goal, scope, non-goals, risks and observable acceptance criteria in `docs/work/NAME.md`, starting from the [task template](docs/work/TEMPLATE.md). The task must be human-reviewed before it is implemented and must exist in the protected base commit; an `approved` text in your own PR is not enough. [Example](docs/work/FACTORY-001.md).
2. `factory-change`: a small, appropriate implementation and meaningful evidence. Check API and library assumptions against versioned vendor documentation; with Context7 call `resolve-library-id` first, then `query-docs`. No precautionary abstractions, invented interfaces or tests that mock away critical logic.
3. `factory-review`: check your own change and the actual results against the task. After skill or role changes run `python3 tools/factory/clients.py sync --root .`, then `check --root .`; run the full check with `python3 tools/factory/verify.py --root .`. Name blocked checks openly. A local review does not replace the independent server run.
4. Check the patch outside the model worker, apply it on the task branch and open the PR. In the PR describe the change, the evidence and open limits; use exactly one handoff block with a real task and a verified maintainer:

```factory-handoff
{"runner":"codex","task":"docs/work/FACTORY-001.md","owner":"Zerosteps1"}
```

`runner` must be one of the `runners` in `factory/config.json`. Under the operating model in [ADR-0005](docs/decisions/0005-operating-model-without-api-billing.md) the author runner becomes `claude` once PR B2 is merged.

Rules, skills, requirements, tests and budgets are loaded from the pinned protected base commit. Changes to this foundation are separate, human-reviewed factory or requirement changes; the current PR cannot weaken its own check by revising its own rules. Automatic corrections must not change protected files.

## Feedback and resumption

After activation, ordinary PR comments, reviews and inline comments from configured human maintainers are automatically read again from GitHub and checked. No special bot syntax is needed. The independent reviewer relates them to the current task and head. Bot and third-party comments do not authorize work; review threads are not resolved automatically.

`factory-fix-review` answers every point with **done**, **disputed with reasons** or **blocked**, each with evidence. Justified findings are fixed and checked again. Factual conflicts go back to the human; new product wishes first need a versioned, human-reviewed task. Do not change requirements or tests to make a finding disappear.

`P0`/`P1` block; `P2` are notes. A fully correct small PR may pass without findings. `pass` requires the complete check scope and sufficient evidence. `blocked`, missing credentials, no progress, conflicts or exhausted limits lead to `needs-author-action`; at most three automatic correction rounds, no silent switch between Codex and Claude.

To resume, fix the cause named in the PR, check out the current branch freshly and start the runner named there:

```sh
python3 tools/factory/doctor.py --root . --runner codex
python3 tools/factory/clients.py launch --root . --runner codex
# In the client: factory-fix-review for PR #<number>, the current task and the findings.
```

Secret presence in the launcher does not prove valid API access. If access is missing, provide the secrets and models named in the [README](README.md); in a conflict, first record the human decision in the task. Check the patch and update the branch; the new head starts fresh checks. Without a code change, a verified maintainer can start a new run with `gh workflow run factory.yml --ref main -f pr=<number> -f retry=true`. GitHub's "Re-run jobs" is rejected because it would reuse old budget reservations. Old checks never approve a new head or base.

## Merge

Merge only after the App-bound required checks (both once the shadow phase has ended, see below), a human CODEOWNER approval and resolved threads. A human decides and merges. A PR opened by one code owner needs the approval of the other code owner; nobody approves their own PR ([ADR-0001](docs/decisions/0001-maintainer-model.md)). Models have no GitHub credentials; no direct pushes to `main`, no automatic merges and no unilateral changes to protection rules.

## Dependabot PRs

Dependabot writes no handoff block, so its PRs stay blocked until a maintainer adds one. The task [FACTORY-DEPS](docs/work/FACTORY-DEPS.md) defines the allowed paths and the procedure:

1. Check that the PR changes only the paths listed in FACTORY-DEPS.
2. Edit the PR description and append exactly one block that references `docs/work/FACTORY-DEPS.md`, with a configured runner and your own verified login as `owner`. The edit starts a new run; edit once.
3. If Dependabot later rewrites the description, add the block again.

These PRs change only factory control paths, so the factory never corrects them automatically; a needed fix goes into a separate, manually managed PR. The test stage builds its image from the trusted base, so build a Dockerfile or npm change yourself from the PR head before approving. Dependabot is the PR author, so either code owner can approve.

## Shadow phase

Until the senior review is calibrated, it is advisory:

- At activation, `required_checks` contains only `factory/deterministic`. (`factory/config.json` and `factory/github-settings.json` still list both checks today; reducing them is part of activation.)
- `factory/senior-review` is still published on every PR. A maintainer checks each verdict by hand and notes in the PR where it was wrong (false alarm or missed defect). Blocking findings are answered like any review: fixed, or disputed with evidence.
- The phase ends after 10–20 real PRs have been reviewed and checked by hand and a golden PR eval set shows the reviewer's precision. A reviewed control PR then adds `factory/senior-review` to the required checks.
- Automatic correction rounds stay disabled during the shadow phase.
- `@codex review` can serve as a free second opinion; it never replaces either check.

## Operating model

The decided operating model is S1 ([ADR-0005](docs/decisions/0005-operating-model-without-api-billing.md)): the gate reviewer runs `codex exec --output-schema` with GPT-6 Astra under a ChatGPT Business access token on the maintainer's trusted machine, in a fresh session; the author is Claude Code behind the existing credential broker, funded by the Claude Team plan's monthly API credit; there is no `OPENAI_API_KEY`. Until PR B1 and B2 implement this, the code and the README still describe the API-key review stage. Follow the README for the current setup, and do not add new dependencies on `OPENAI_API_KEY`.

## Decisions and language

Permanent decisions go into `docs/decisions/` ([index and template](docs/decisions/README.md)). Write in English; only the north star stays German ([ADR-0004](docs/decisions/0004-language.md)).

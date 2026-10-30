# FACTORY-005 – One developer checkout with a managed control checkout

Status: draft; it authorizes work only after a maintainer sets `status` to `approved` and this file is merged to protected `main` in its own reviewed PR. [FACTORY-006](FACTORY-006.md) (issues as work orders) builds on it.

```factory-task
{"status":"approved","kind":"factory","allowed_paths":["tools/factory/","factory/","AGENTS.md","README.md","CONTRIBUTING.md","docs/dev-setup.md","docs/way-of-working.md","docs/software-factory.md","docs/decisions/"]}
```

requirements: []

## Goal

A developer works in one checkout of their choice (for example `Aicepeak_V2.0.0`) and runs every factory command from it. The tools create and maintain the control checkout themselves as a sibling folder named `.aicepeak-control-checkout`, and they always run the trusted code from that control checkout.

## Non-goals

- No change to the GitHub Actions pipeline, the gate, the review binding, models, limits or rulesets.
- No weakening of the control checkout: it stays a byte-identical, clean copy of current `main`, and the trusted code still runs only from it.
- No automatic deletion of files in a control checkout that has unexpected changes.
- No change to the isolated container or the credential broker.

## Context and constraints

Today the developer manages two clones. `session.py`, `doctor.py`, `local_review.py`, `engine.py`, `merge_safety.py` and `settings.py` take the control checkout from their own file location (`ROOT = Path(__file__).resolve().parents[2]`), so they must be started from the control checkout. `session.py` and `merge_safety.py` require a separate `--candidate` (`session.py:195`, `merge_safety.py:56`). `clients.py launch` passes the same root as candidate and trusted root (`clients.py:768`), although `run()` and `sanitized_copy()` already separate the two (the pipeline uses this). `verify.py` already takes `--root` and `--trusted-root`.

Places to change:

- **New shared module** in `tools/factory/` that finds the developer checkout (`git rev-parse --show-toplevel` of the working directory) and its sibling `<parent>/.aicepeak-control-checkout`, and creates, verifies and updates it.
- **Entry points** `session.py` (all subcommands), `clients.py` (`launch`, `smoke`), `doctor.py`, `local_review.py --smoke` and `verify.py`. When started outside the control checkout, they ensure the control checkout and then re-execute the same command from the control checkout's copy of the script. Nothing else from the developer checkout runs.
- **Defaults:** `--candidate`, `clients.py launch --root` and `verify.py --root` default to the developer checkout; `--trusted-root` defaults to the control checkout. Explicit arguments keep working, and so does starting a command from the control checkout itself.
- **`clients.py launch`** copies the developer checkout with the control paths taken from the control checkout, so the returned patch applies directly in the developer checkout.
- **Messages and hints** that mention the old flow: `session.py:4`, `session.py:160`, `session.py:348`, `merge_safety.py:3`, the `needs-author-action` comment in `engine.py:412`.
- **Docs:** `AGENTS.md`, `README.md`, `CONTRIBUTING.md`, `docs/dev-setup.md` (one clone instead of two), `docs/way-of-working.md` (no `cd` between checkouts), `docs/software-factory.md` (the control checkout section), `factory/clients.md`, `factory/github.md`, and a decision record in `docs/decisions/`.
- **Tests** in `tools/factory/tests/`.

Rules for the control checkout:

1. **Location and name:** always `<parent of the developer checkout>/.aicepeak-control-checkout`. All commands and all developer checkouts in the same folder share it. A second one is never created.
2. **Creation:** only if it does not exist, as a fresh `git clone` from `https://github.com/<repository>.git`, with `<repository>` from `factory/config.json`, never from the developer checkout's remote or configuration. Then on `main`.
3. **Update before every command:** `git fetch origin main`, then a fast-forward to `origin/main`. If it is not clean, has extra or ignored files, is not on `main` or cannot fast-forward, the command stops and names the problem and the fix. It never deletes or resets files.
4. **Concurrency:** a lock prevents an update while another command (for example a running `watch`) uses the control checkout. A command that needs an update waits for a bounded time or stops with a clear message.
5. **Trust boundary:** the small start code in the developer checkout is the only code that runs from there. It does nothing but locate, create and update the control checkout and re-execute. If its own file differs from the copy in the control checkout, it stops and asks the developer to update the branch. The decision record names the remaining risk: a developer who changes this start code by hand runs their own change.

A PR may change at most 40 files. If the implementation exceeds that, split it into consecutive PRs under this work order.

## Acceptance criteria

1. AC-1: When a factory command is started in a developer checkout and no `.aicepeak-control-checkout` sibling exists, the tool shall create it as a fresh clone of the configured repository on `main` and then run the command from it.
2. AC-2: When the sibling exists and is clean, the tool shall fast-forward it to `origin/main` before the command runs and shall not create a second control checkout.
3. AC-3: If the control checkout has uncommitted, extra or ignored files, is not on `main` or cannot fast-forward, then the tool shall stop with a message that names the problem, and shall not change any file.
4. AC-4: When started outside the control checkout, `session.py`, `clients.py launch`/`smoke`, `doctor.py`, `local_review.py --smoke` and `verify.py` shall execute only the control checkout's copy of their code, apart from the start code of rule 5.
5. AC-5: `session.py submit`, `collisions`, `preflight` and `merge` shall use the developer checkout as candidate without `--candidate`; explicit `--candidate` and starting from the control checkout shall keep working.
6. AC-6: When `clients.py launch` runs in a developer checkout, the author shall see that checkout's files with every control path taken from the control checkout, and the returned patch shall apply with `git apply` in the developer checkout.
7. AC-7: If an update is needed while another command holds the control checkout, then the tool shall not change it and shall wait for a bounded time or stop with a message.
8. AC-8: If the start code in the developer checkout differs from the control checkout's copy, then the tool shall stop before running anything else.
9. AC-9: The docs shall describe one clone, the hidden `.aicepeak-control-checkout` and the simplified daily flow; no doc shall tell the developer to create or `cd` into a second checkout.

## Verification

```sh
python3 -I -m unittest discover -s tools/factory/tests
python3 tools/factory/clients.py check --root .
python3 tools/factory/verify.py --root .
```

Expected output:

- unittest ends with `OK`, with regression tests for AC-1 to AC-8 using temporary Git repositories, including every stop case;
- `clients.py check` passes;
- `verify.py` prints its `PASS:` lines and exits with code 0;
- live evidence in `factory/evidence.md`: from a single developer checkout on a maintainer device, the first command creates `.aicepeak-control-checkout`, a second command reuses and updates it, and one smoke PR goes from `submit` to two green checks.

## Handoff

```factory-handoff
{"runner":"claude","task":"docs/work/FACTORY-005.md","owner":"ftrutschnig"}
```

## Open questions

- Should `launch` copy the developer checkout's working tree including uncommitted changes, or only its committed `HEAD`? Recommendation: committed `HEAD` plus a warning about uncommitted changes. Decided by a maintainer.
- Is the remaining risk of rule 5 acceptable, or should the start code instead be a small wrapper installed once per device outside every checkout? Decided by a maintainer.
- Should the hidden folder be shown in the docs' folder diagrams, so developers who see it in a terminal know not to touch it? Decided by a maintainer.

# FACTORY-007 – Global factory CLI for daily work

Status: approved by the maintainer on 2026-11-01. Supersedes the withdrawn FACTORY-005 (managed control checkout) and FACTORY-006 (issues as work orders); both files are removed.

```factory-task
{"status":"approved","kind":"factory","allowed_paths":["tools/factory/","factory/clients.md","factory/evidence.md","docs/factory-cli.md","docs/way-of-working.md","docs/dev-setup.md","docs/software-factory.md","docs/decisions/","docs/work/TEMPLATE.md",".github/ISSUE_TEMPLATE/factory-task.md","README.md","CONTRIBUTING.md","AGENTS.md"]}
```

requirements: []

## Goal

A maintainer installs one global `factory` command and does all daily factory work with it, from any directory: issue and activate work orders, start, stop and cancel the isolated author, fix and hotfix, review locally, submit, watch and merge. The command manages a control checkout (trusted code on current `main`) and a candidate checkout (where changes land) and runs every step in the right place.

## Non-goals

- No change to the GitHub Actions pipeline, the gate, the binding review, models, limits, rulesets or required checks.
- No change to the credential broker or the isolation of the author container, apart from labels, a read-only review mode and an optional event stream in `tools/factory/clients.py`.
- No weakening of the control checkout: it stays a clean copy of current `main`, and trusted code runs only from it or from a pinned export of it.
- No automatic deletion or reset of files in either checkout, except the documented move of submitted work orders.
- No GitHub issues as work orders (the former FACTORY-006).

## Context and constraints

- Today a maintainer manages two clones (`docs/dev-setup.md`), runs `tools/factory/session.py` and `tools/factory/clients.py` by hand and edits the `factory-task` status manually.
- Trust boundary: the shim outside every checkout runs `tools/factory/cli/factory.py` from the configured control checkout. Before each command the control checkout is verified (identity, `main`, clean including ignored files), fetched and fast-forwarded. `session.py` only ever receives disposable checkouts built from Git objects. Candidate content never executes on the host. Git runs with hooks, fsmonitor, global and system configuration disabled.
- The isolated author cannot write the control paths in `CONTROL_PATHS` of `tools/factory/clients.py`; the CLI refuses author runs for work orders that lie entirely inside them.
- `hotfix` pushes automatically only changes inside `allowed_paths`, outside `protected_paths`, without binary, symlink or submodule entries, with a passing preflight on exactly the pushed commit; otherwise it behaves like `fix`.
- One `start`/`fix`/`hotfix` run stays within `max_cost_usd`; each model run within `max_run_cost_usd`.
- Delivered locally by the maintainer outside the factory pipeline (maintainer decision of 2026-11-01). Decision record: `docs/decisions/0007-factory-cli.md`.

## Acceptance criteria

1. AC-1: When `tools/factory/cli/install-factory-cli.sh` runs, it shall clone or reuse a clean control checkout on `main` from `https://github.com/<repository>.git`, reuse or clone the candidate checkout, store both on-disk paths in a 0600 device configuration, install a shim that runs a pinned Python ≥ 3.11 with `-I -S -B`, and add a PATH block only when needed; a second run shall change nothing.
2. AC-2: `factory --help` and `factory <command> --help` shall work without configuration, lock or network, create no bytecode, and show for every command what it does, when to use it, examples and documentation links.
3. AC-3: If `factory.py` runs from a path other than the configured control checkout or a run's pinned export, then it shall exit non-zero before any other action.
4. AC-4: If the control checkout is not a clean `main` (untracked and ignored files included), cannot fast-forward, or its lock stays busy for 60 s, then the command shall stop, name the cause and the lock holder, and change no control file.
5. AC-5: When `factory issue` runs, it shall create `docs/work/<KIND>-<NNN>.md` in the candidate with status `draft`, where NNN is one higher than every number ever added on `main`, present in the candidate or added by a maintainer's open pull request.
6. AC-6: If a changed work order breaks the `factory-task` block rules (apart from status), has unsafe or placeholder paths, a title that does not match its ID, template placeholders or an ID already in use, then `factory submit workorders` shall name the file and rule and push nothing.
7. AC-7: `factory submit` shall commit only staged files, refuse `main`, a detached HEAD and a branch behind its upstream, and never force-push; with `--finished` it shall open or update the pull request through `session.py` on a disposable checkout.
8. AC-8: When `factory start workorder <n>` runs for an approved work order, it shall start exactly one background run and attach to it; Ctrl-C shall only detach; `factory continue <n>` shall reattach or exit non-zero with the last result.
9. AC-9: `factory stop workorder <n>` shall end the run after its current step and apply what exists; `factory cancel workorder <n>` shall end all processes of the run, leave no Docker container, network or volume carrying the run label and apply nothing.
10. AC-10: A run shall go author → advisory preflight → at most `max_rounds` corrections while P0/P1 findings remain → apply; empty, oversized, out-of-scope, `main`-moved and budget cases shall end with a stated reason, and a patch that cannot be applied shall be kept with exact commands.
11. AC-11: The CLI shall execute no candidate file, run Git hardened, pass only disposable checkouts to `session.py`, and keep author keys out of every file, log, argument and environment except that of the launcher child.
12. AC-12: When given labels, `clients.py run` shall label every container, network and volume; in read-only mode the worker shall get only Read, Glob, Grep, Skill and the documentation MCP tools and no patch shall be returned; without events its arguments and result parsing shall be unchanged.
13. AC-13: The tests shall pass in the factory image with a read-only root filesystem and no network, Docker, `gh` or `ps` within 180 s per pass, and the test suite of `main` shall pass against this change.

## Verification

```sh
python3 tools/factory/verify.py --root /candidate --trusted-root /policy --ci   # in the factory image, see docs/factory-cli.md
bash -n tools/factory/cli/install-factory-cli.sh
```

Expected output:

- both unittest passes end with `OK`;
- `verify.py` prints its `PASS:` lines and exits with code 0;
- `bash -n` prints nothing and exits with code 0.

Live acceptance on a maintainer device after the merge is recorded in `factory/evidence.md`.

## Handoff

```factory-handoff
{"runner":"claude","task":"docs/work/FACTORY-007.md","owner":"ftrutschnig"}
```

## Open questions

- None. Live acceptance (installer on a fresh device, real stream-json capture of Claude Code 2.1.311) is open until recorded in `factory/evidence.md`.

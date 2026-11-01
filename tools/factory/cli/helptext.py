"""Help catalogue of the factory CLI: what each command does, when to use it, examples and documentation.

Standard library only: `factory --help` must work without configuration, lock or network.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True  # Keep trusted control checkouts clean during CLI use.

ROOT = Path(__file__).resolve().parents[3]
FLOW = 'docs/way-of-working.md#daily-use-step-by-step'

COMMANDS = {
    'issue': {
        'summary': 'Create a new work order from the template and open it in your editor.',
        'what': 'Writes docs/work/<KIND>-<NNN>.md into the candidate checkout with the next free number (one counter for '
                'all kinds; numbers of deleted work orders are never reused), status draft and you as handoff owner, then '
                'opens it in $VISUAL/$EDITOR (macOS default text editor otherwise).',
        'when': 'You want the factory to build something new: one work order per feature, not per commit.',
        'examples': ['factory issue --title "Export energy costs as CSV"',
                     'factory issue --kind smoke --title "Reviewer device smoke" --noedit',
                     'factory issue          # title later, in the editor'],
        'docs': ['docs/factory-cli.md#factory-issue', FLOW, 'docs/work/TEMPLATE.md'],
    },
    'submit workorders': {
        'summary': 'Activate work orders: commit only docs/work changes, push <login>/new-workorders and open the PR.',
        'what': 'Collects your uncommitted changes of docs/work/*.md, checks every block rule, asks whether drafts should '
                'become approved and confirms edits and deletions, then commits them alone on <login>/new-workorders, '
                'pushes and opens (or updates) the pull request with handoff FACTORY-001 and watches its review. Other '
                'changes in your checkout stay untouched; submitted files move to the work-order branch.',
        'when': 'After `factory issue`, when the work order text is final. A work order authorizes work only once merged.',
        'examples': ['factory submit workorders'],
        'docs': ['docs/factory-cli.md#factory-submit-workorders', FLOW],
    },
    'start': {
        'summary': 'Start the isolated author on an approved work order (background run, attached).',
        'what': 'Runs the author in the isolated container, an advisory Astra preflight and up to max_rounds corrections '
                'for P0/P1 findings, then applies the result unstaged to <login>/<ID> in the candidate. Ctrl-C only '
                'detaches; the run goes on. One run per work order; at most max_cost_usd of model spend per run.',
        'when': 'The work order is merged with status approved and you want the factory to implement it.',
        'examples': ['factory start workorder 7', 'factory start workorder FACTORY-007'],
        'docs': ['docs/factory-cli.md#factory-start-workorder', 'docs/software-factory.md#the-isolated-author-session'],
    },
    'continue': {
        'summary': 'Reattach to the running factory run of a work order.',
        'what': 'Shows the run log from the start and follows it until the run ends. Fails, naming the last result, '
                'when no run of that work order is active.',
        'when': 'You detached with Ctrl-C or closed the terminal and want to watch the run again.',
        'examples': ['factory continue 7', 'factory continue      # the only active run'],
        'docs': ['docs/factory-cli.md#factory-continue'],
    },
    'stop': {
        'summary': 'Stop a run after its current step; what exists is still applied.',
        'what': 'Asks the run to finish the step it is in (author, preflight, correction) and then skip every further '
                'model step. Its result so far is applied to the candidate as usual. Nothing on GitHub changes.',
        'when': 'The run is going in the wrong direction or you need the machine, but the current step may finish.',
        'examples': ['factory stop workorder 7'],
        'docs': ['docs/factory-cli.md#factory-stop-workorder', 'docs/way-of-working.md#stop-or-cancel-a-task'],
    },
    'cancel': {
        'summary': 'Emergency stop: end a run at once and remove its containers.',
        'what': 'Terminates the run and its processes immediately, removes every Docker container, network and volume '
                'with the run label and applies nothing. It changes no GitHub state; a review already claimed stays '
                'claimed (the command prints the retry).',
        'when': 'Something is clearly wrong (cost, scope, a runaway step) and waiting for the step is not acceptable.',
        'examples': ['factory cancel workorder 7'],
        'docs': ['docs/factory-cli.md#factory-cancel-workorder', 'docs/way-of-working.md#stop-or-cancel-a-task'],
    },
    'fix': {
        'summary': 'Fix a bug within a work order: review, fix plan, fix, preflight; you submit.',
        'what': 'Reviews the problem read-only, lets the author plan and implement the smallest fix inside the work '
                "order's allowed paths, runs the preflight/correction loop and applies the result to the work order's "
                'open PR branch or a new <login>/<ID>-fix-<k>. Without a prompt it fixes the open PR\'s latest '
                'senior-review findings and maintainer feedback. Prints the exact `factory submit` command.',
        'when': 'A problem belongs to an approved work order and you want to look at the fix before it is pushed.',
        'examples': ['factory fix 7 "CSV export drops rows with empty tariffs"',
                     'factory fix 7 "#42"                # a maintainer-written issue or comment',
                     'factory fix 7                      # the open PR\'s review findings'],
        'docs': ['docs/factory-cli.md#factory-fix-and-factory-hotfix', 'docs/way-of-working.md#fix-findings-yourself'],
    },
    'hotfix': {
        'summary': 'Like fix, but pushes and opens or updates the PR automatically when it is safe.',
        'what': 'Runs fix and pushes automatically only if every change is inside the allowed paths and outside protected '
                'paths, with no binary/symlink entry, a passing preflight on exactly that result and an unchanged main; '
                'then it opens the PR (or updates the open one) and watches its review. Otherwise it ends like fix.',
        'when': 'An urgent, small fix outside the protected factory paths.',
        'examples': ['factory hotfix 7 "Totals use the wrong VAT rate"', 'factory hotfix 7 --pr 51'],
        'docs': ['docs/factory-cli.md#factory-fix-and-factory-hotfix', 'docs/way-of-working.md#merge-rules'],
    },
    'review': {
        'summary': 'Local read-only review of your candidate: a list of problems, nothing changed.',
        'what': 'Runs the read-only reviewer role in the isolated container over your candidate checkout (committed and '
                'uncommitted files) and prints the problems with file:line, evidence and a suggested fix. Advisory only; '
                'control paths are listed as not reviewed because the reviewer sees their version on main.',
        'when': 'Before you submit, or to hunt a suspected problem.',
        'examples': ['factory review "Are there error paths in the CSV export without tests?"',
                     'factory review "Check the acceptance criteria" --workorder 7'],
        'docs': ['docs/factory-cli.md#factory-review', 'docs/software-factory.md#how-the-factory-works'],
    },
    'submit': {
        'summary': 'Commit the staged files and push; with --finished open the PR for the work order.',
        'what': 'Commits only what you staged (title defaults to "<ID>: <work order title>") and pushes the branch, never '
                'main and never with force. The work order comes from the branch (<login>/<ID>…) or --workorder; any '
                'other branch gets a warning and 5 seconds to abort. --finished opens the PR through session.py '
                '(collision sweep, advisory preflight, ready on pass) and watches its review; an existing PR is watched.',
        'when': 'Daily: commit and push your work. When the work order is done: --finished.',
        'examples': ['factory submit --title "feat(export): CSV export" --desc "Adds the endpoint and tests"',
                     'factory submit --finished', 'factory submit --finished --workorder 7 --draft'],
        'docs': ['docs/factory-cli.md#factory-submit', FLOW, 'docs/way-of-working.md#working-in-parallel'],
    },
    'watch': {
        'summary': 'Run the binding senior review for a PR on this device (or for all waiting PRs).',
        'what': 'Runs session.py watch from a clean copy of current main: the binding Astra review happens only while a '
                'maintainer device watches. --all reviews every PR labelled awaiting-senior-review, once a minute.',
        'when': 'A PR waits for review: after Ctrl-C in submit, after new pushes or comments, or for other maintainers.',
        'examples': ['factory watch 42', 'factory watch --all'],
        'docs': ['docs/factory-cli.md#factory-watch', 'docs/way-of-working.md#review-all-waiting-prs'],
    },
    'merge': {
        'summary': 'Merge a PR with the verified, locked merge (session.py merge).',
        'what': 'Verifies both required checks on exactly this head and current main, the handoff, feedback and open '
                'threads, takes the repository merge lock and merges with --match-head-commit. --dry-run shows the verdict.',
        'when': 'Both checks are green and you decided to merge. One PR at a time.',
        'examples': ['factory merge 42 --dry-run', 'factory merge 42'],
        'docs': ['docs/factory-cli.md#factory-merge', 'docs/way-of-working.md#merge-rules'],
    },
    'status': {
        'summary': 'List active and recent factory runs on this device.',
        'what': 'Shows work order, kind, current step or result, start time, branch and PR of the latest runs.',
        'when': 'You want to know what the factory is doing or did.',
        'examples': ['factory status'],
        'docs': ['docs/factory-cli.md#factory-status'],
    },
    'doctor': {
        'summary': 'Check this device: shim, checkouts, keys, Docker image, Codex and GitHub login.',
        'what': 'Runs the CLI checks and summarises doctor.py. Prints the fix for every failed check.',
        'when': 'After installing, after updates of your tools, or when a command fails for environmental reasons.',
        'examples': ['factory doctor'],
        'docs': ['docs/factory-cli.md#factory-doctor', 'docs/dev-setup.md#check-the-tools'],
    },
}

OVERVIEW = [
    ('Work orders', ['issue', 'submit workorders']),
    ('Implementation', ['start', 'continue', 'stop', 'cancel', 'fix', 'hotfix']),
    ('Review and publication', ['review', 'submit', 'watch', 'merge']),
    ('Device', ['status', 'doctor']),
]


def repository():
    try:
        return json.loads((ROOT / 'factory/config.json').read_text())['repository']
    except (OSError, ValueError, KeyError):
        return 'Zerosteps1/Aicepeak_V2.0.0'


def link(target):
    return f'{target}  (https://github.com/{repository()}/blob/main/{target})'


def description(name):
    entry = COMMANDS[name]
    return f'{entry["summary"]}\n\nWhat it does: {entry["what"]}\n\nWhen to use it: {entry["when"]}'


def epilog(name):
    entry = COMMANDS[name]
    return ('Examples:\n' + '\n'.join('  ' + example for example in entry['examples'])
            + '\n\nDocumentation:\n' + '\n'.join('  ' + link(target) for target in entry['docs']))


def overview():
    lines = ['Daily flow: factory issue → factory submit workorders → (merge) → factory start workorder <n> → '
             'factory submit → factory submit --finished → factory watch → factory merge', '']
    for title, names in OVERVIEW:
        lines.append(title + ':')
        lines += [f'  factory {name:<18} {COMMANDS[name]["summary"]}' for name in names]
        lines.append('')
    lines.append('Help for one command: factory <command> --help')
    lines.append('Documentation: ' + link('docs/factory-cli.md'))
    return '\n'.join(lines)

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
APPROVALS = 'approvals from as many maintainers as work_order_approvals in factory/config.json names'

COMMANDS = {
    'start': {
        'summary': 'Start the isolated author on an approved work-order issue (background run, attached).',
        'what': 'Runs the author in the isolated container, an advisory Astra preflight and up to max_rounds corrections '
                "for P0/P1 findings, then applies the result unstaged to the issue's branch in the candidate: "
                "57-<issue title>, named as GitHub names an issue's branch. An existing branch of the issue (local or on "
                "GitHub) is continued; a new one starts from the validation branch routed for the work order's kind. "
                'Ctrl-C only detaches; the run goes on. One run per work order; at most max_cost_usd of model spend per run.',
        'when': 'The work-order issue is approved (after /review and /accept on GitHub) and you want it implemented.',
        'examples': ['factory start workorder 57', 'factory start workorder "#57"      # the same, quoted for the shell'],
        'docs': ['docs/factory-cli.md#factory-start-workorder', 'docs/software-factory.md#the-isolated-author-session'],
    },
    'continue': {
        'summary': 'Reattach to the running factory run of a work order.',
        'what': 'Shows the run log from the start and follows it until the run ends. Fails, naming the last result, '
                'when no run of that work order is active. `hotfix` names the run of a hotfix without a work order.',
        'when': 'You detached with Ctrl-C or closed the terminal and want to watch the run again.',
        'examples': ['factory continue workorder 57', 'factory continue hotfix         # the hotfix without a work order'],
        'docs': ['docs/factory-cli.md#factory-continue-workorder'],
    },
    'stop': {
        'summary': 'Stop a run after its current step; what exists is still applied.',
        'what': 'Asks the run to finish the step it is in (author, preflight, correction) and then skip every further '
                'model step. Its result so far is applied to the candidate as usual. Before a hotfix\'s push gate '
                'nothing on GitHub changes; after it, the push and the PR finish and only the watch stops. `hotfix` '
                'names the run of a hotfix without a work order.',
        'when': 'The run is going in the wrong direction or you need the machine, but the current step may finish.',
        'examples': ['factory stop workorder 57', 'factory stop hotfix         # the hotfix without a work order'],
        'docs': ['docs/factory-cli.md#factory-stop-workorder', 'docs/way-of-working.md#stop-or-cancel-a-task'],
    },
    'cancel': {
        'summary': 'Emergency stop: end a run at once and remove its containers.',
        'what': 'Terminates the run and its processes immediately, removes every Docker container, network and volume '
                'with the run label and applies nothing. It changes no GitHub state; a review already claimed stays '
                'claimed (the command prints the retry). `hotfix` names the run of a hotfix without a work order.',
        'when': 'Something is clearly wrong (cost, scope, a runaway step) and waiting for the step is not acceptable.',
        'examples': ['factory cancel workorder 57', 'factory cancel hotfix         # the hotfix without a work order'],
        'docs': ['docs/factory-cli.md#factory-cancel-workorder', 'docs/way-of-working.md#stop-or-cancel-a-task'],
    },
    'fix': {
        'summary': "Fix a problem in a work order's implementation: review, fix plan, fix, preflight; you submit.",
        'what': 'Needs a work-order issue that is already being implemented: the fix lands on the branch of its open PR, '
                "or on the issue's branch (57-<issue title>) before the PR exists. One work order is one PR. It reviews "
                "the problem read-only, lets the author plan and implement the smallest fix inside the work order's "
                'allowed paths, runs the preflight/correction loop and applies the result unstaged. Without a prompt it '
                "fixes the open PR's latest senior-review findings and maintainer feedback (before the PR exists: the "
                'problems a review against the acceptance criteria finds). Prints the exact `factory submit` command.',
        'when': 'A problem belongs to an approved work order and you want to look at the fix before it is pushed. A '
                'problem without a work order is a `factory hotfix`.',
        'examples': ['factory fix workorder 57 "CSV export drops rows with empty tariffs"',
                     'factory fix workorder 57 "#42"     # a maintainer-written issue or comment',
                     "factory fix workorder 57           # the open PR's review findings"],
        'docs': ['docs/factory-cli.md#factory-fix-and-factory-hotfix', 'docs/way-of-working.md#fix-findings-yourself'],
    },
    'hotfix': {
        'summary': 'Fix something urgently and push it automatically when it is safe; a work order is optional.',
        'what': 'With a work order it runs fix and pushes automatically only if every change is inside the allowed paths '
                'and outside protected paths, with no binary/symlink entry, a passing preflight on exactly that result '
                'and an unchanged target; then it opens the PR (or updates the open one) and watches its review. '
                'Otherwise it ends like fix. Without a work order (only a prompt) the author fixes the problem on a new '
                'branch hotfix/<date>-<words of the prompt> from the default branch, and factory pushes it when nothing '
                'lies in a protected or guarded path and no binary/symlink entry changed: no preflight and no PR. The '
                'maintainer in charge merges that branch or opens a PR as they see fit.',
        'when': 'An urgent, small fix outside the protected factory paths, with or without a work order.',
        'examples': ['factory hotfix workorder 57 "Totals use the wrong VAT rate"',
                     'factory hotfix workorder 57          # the open PR\'s review findings',
                     'factory hotfix "The CSV export header misspells kWh"'],
        'docs': ['docs/factory-cli.md#factory-fix-and-factory-hotfix', 'docs/way-of-working.md#merge-rules'],
    },
    'review': {
        'summary': 'Local read-only review of your candidate against a work order: a list of problems, nothing changed.',
        'what': 'Runs the read-only reviewer role in the isolated container over your candidate checkout (committed and '
                'uncommitted files), with the work-order issue as context, and prints the problems with file:line, '
                'evidence and a suggested fix. Advisory only; control paths are listed as not reviewed because the '
                'reviewer sees their control checkout version.',
        'when': 'Before you submit, or to hunt a suspected problem.',
        'examples': ['factory review workorder 57 "Are there error paths in the CSV export without tests?"',
                     'factory review workorder 57 "Check the acceptance criteria"'],
        'docs': ['docs/factory-cli.md#factory-review-workorder', 'docs/software-factory.md#how-the-factory-works'],
    },
    'submit': {
        'summary': 'Commit the staged files and push; with --finished open the PR for the work order.',
        'what': 'Commits only what you staged (title defaults to "<issue title> #57") and pushes the branch, never a '
                'listed branch and never with force. The work order comes from the branch name, 57-<issue title> (as '
                '`factory start` and GitHub\'s "Create a branch" name it). A hotfix branch (hotfix/…) is committed and '
                "pushed as it is; any other branch gets a warning and 5 seconds to abort. --finished refuses both; on an "
                "issue branch it opens the PR into the validation branch routed for the work order's kind through session.py (collision "
                "sweep, advisory preflight, opened only on pass) and "
                'watches its review; an existing PR is watched. One work order is one PR: its body says "Closes #57", '
                'and GitHub closes the issue when the PR merges into its default branch.',
        'when': 'Daily: commit and push your work. When the work order is done: --finished.',
        'examples': ['factory submit --desc "Adds the endpoint and tests"',
                     'factory submit --title "Export energy costs as CSV #57"', 'factory submit --finished'],
        'docs': ['docs/factory-cli.md#factory-submit', FLOW, 'docs/way-of-working.md#working-in-parallel'],
    },
    'watch': {
        'summary': 'Run the binding senior review for a PR on this device (or for all waiting PRs).',
        'what': 'Runs session.py watch from a clean copy of the config branch tip: the binding Astra review happens only '
                'while a maintainer device watches. --all reviews every PR labelled awaiting-senior-review, once a minute. '
                'A `/review` that feedback, a moved config branch or a moved target branch made stale is reported (comment `/review` again), '
                'not waited on; --all goes on with the other PRs. It keeps the Mac from idle-sleeping while it watches.',
        'when': 'A PR waits for review: after Ctrl-C in submit, after new pushes or comments, or for other maintainers.',
        'examples': ['factory watch 42', 'factory watch --all'],
        'docs': ['docs/factory-cli.md#factory-watch', 'docs/way-of-working.md#review-all-waiting-prs'],
    },
    'merge': {
        'summary': 'Merge a PR into a validation branch with the verified, locked merge (session.py merge).',
        'what': "Verifies the required checks of the target's gate on exactly this head and the current target tip, the "
                'handoff, feedback and open threads, takes the merge lock of the target and merges with '
                '--match-head-commit. --dry-run shows the verdict. PRs into production branches are merged on GitHub '
                'with a merge commit.',
        'when': 'The required checks are green and you decided to merge. One PR at a time.',
        'examples': ['factory merge 42 --dry-run', 'factory merge 42'],
        'docs': ['docs/factory-cli.md#factory-merge', 'docs/way-of-working.md#merge-rules'],
    },
    'status': {
        'summary': 'List active and recent factory runs on this device.',
        'what': 'Shows work order (#57), run kind (start, fix, hotfix), current step or result, start time, branch and '
                'PR of the latest runs.',
        'when': 'You want to know what the factory is doing or did.',
        'examples': ['factory status'],
        'docs': ['docs/factory-cli.md#factory-status'],
    },
    'promote': {
        'summary': 'Promote a validation branch: bring production into it, or open the promotion PR.',
        'what': 'When the production branch is not contained in the validation branch, brings it into that branch in '
                'the clean candidate (a fast-forward when the validation branch has nothing production lacks, otherwise '
                'a merge commit; never pushed; conflicts stay for you) and prints the push command. '
                'Once it is contained, opens the PR <validation> → <production> and prints the /review hint; when the '
                'promotion of this validation branch is already open, it reports that the PR now carries the new head. '
                'A promotion from another validation branch into it refuses. Never merges.',
        'when': 'The validation branch holds what should go to production. --to names the production branch when '
                'several are listed.',
        'examples': ['factory promote testing', 'factory promote testing --to production'],
        'docs': ['docs/factory-cli.md#factory-promote'],
    },
    'update': {
        'summary': 'Bring the config branch (with factory/config.json) into a branch of the candidate.',
        'what': 'Fast-forwards the target (default: the branch checked out in the candidate; a named one is switched to, '
                'created from GitHub if missing) to the config branch tip, or creates the local merge commit "Merge '
                '<config branch> into <target> (factory update)" when the target has commits the config branch lacks. '
                'Refuses before touching the working tree when that would change anything but factory/config.json and '
                'docs/work/*.md, and refuses production branches, a candidate with uncommitted or untracked files '
                'and a local branch that diverged from GitHub. Never pushes: it prints the push command for a '
                'validation branch; your own branch (an issue branch) goes up with your next `factory submit`. Conflicts stay for you.',
        'when': 'After a promotion or a config PR was merged into the config branch, so that the validation branches '
                '(and your branch) contain it and GitHub no longer reports production ahead of them.',
        'examples': ['factory update', 'factory update testing'],
        'docs': ['docs/factory-cli.md#factory-update', 'docs/way-of-working.md#branches-and-promotion'],
    },
    'branches': {
        'summary': 'Show the branches, gates, routing and review modes; write docs/factory-branches.md.',
        'what': 'Prints the branch table of the config branch and writes the generated docs/factory-branches.md (a '
                'Mermaid diagram: issue branches → validation (gate, kinds) → production (review mode), dotted arrows '
                'from the config branch for what `factory update` brings back into the validation branches) into the '
                'candidate; that changed file never counts as an uncommitted change for other factory commands. --show also writes a '
                'self-contained HTML page with the diagram and opens it.',
        'when': 'You want to see how work flows, or the branch list changed and the diagram should follow.',
        'examples': ['factory branches', 'factory branches --show'],
        'docs': ['docs/factory-cli.md#factory-branches'],
    },
    'use branch': {
        'summary': 'Run this device\'s factory code from another listed branch (control checkout).',
        'what': 'Switches the control checkout to a listed production or validation branch and records it in cli.json. '
                'Only when the control checkout is clean; it never resets or deletes anything. Rules and policy still '
                'come from the config branch; commands still act on the candidate. Works from any state of '
                'the current control branch: unlisted, missing on GitHub, or naming an old config branch.',
        'when': 'You want to use the CLI version of a validation branch, or switch back after a branch was removed or '
                'the config branch changed.',
        'examples': ['factory use branch testing', 'factory use branch production'],
        'docs': ['docs/factory-cli.md#factory-use-branch'],
    },
    'add validation branch': {
        'summary': 'Open a config PR that adds or changes a validation branch (gate, routed kinds).',
        'what': 'Edits only the branches value of factory/config.json on a fresh branch from the config branch tip, '
                f'pushes it and opens the PR into the config branch, which needs {APPROVALS}. --gate is full, tests or '
                'none; --kinds lists the work-order kinds routed to it (they leave their previous branch). The PR lists '
                'the owner steps.',
        'when': 'A new validation stage is needed, or a gate or routing changes.',
        'examples': ['factory add validation branch staging --gate tests --kinds smoke'],
        'docs': ['docs/factory-cli.md#factory-add-validation-branch'],
    },
    'add production branch': {
        'summary': 'Open a config PR that adds or changes a production branch (review mode).',
        'what': 'Edits only the branches value of factory/config.json on a fresh branch from the config branch tip, '
                f'pushes it and opens the PR into the config branch, which needs {APPROVALS}. --review is no, initiated '
                'or maintainer-manual. The PR lists the owner steps (create the branch, apply the settings).',
        'when': 'A further production branch is needed, or its AI review mode changes.',
        'examples': ['factory add production branch release --review maintainer-manual',
                     'factory add production branch production --review initiated   # change the review mode'],
        'docs': ['docs/factory-cli.md#factory-add-production-branch'],
    },
    'remove branch': {
        'summary': 'Open a config PR that removes a branch from the branch list.',
        'what': f'Edits only the branches value of factory/config.json and opens the PR into the config branch, which '
                f'needs {APPROVALS}. Its kinds move to the default branch. The config branch, the default branch and the '
                'last production branch cannot be removed, nor a branch that factory/config.json on the default branch '
                'still names as the config branch. The branch itself stays on GitHub.',
        'when': 'A validation or production branch is retired.',
        'examples': ['factory remove branch staging'],
        'docs': ['docs/factory-cli.md#factory-remove-branch'],
    },
    'set config branch': {
        'summary': 'Open the two config PRs that make another production branch the config branch.',
        'what': 'Opens two config PRs that change only config_branch in factory/config.json: first into the new branch '
                f'(from its own config.json), then into the current config branch; each needs {APPROVALS}. Merged in '
                'that order, the factory follows the new branch. The PRs list the owner steps (settings, WIF rule, '
                'promote, devices, re-run the open PRs). Refuses while the new branch lags behind the current config '
                'branch (its factory/config.json differs apart from config_branch, or a file in docs/work is missing or '
                'differs) and while the default branch still names an earlier config branch.',
        'when': 'Rules and policy should come from another production branch.',
        'examples': ['factory set config branch release'],
        'docs': ['docs/factory-cli.md#factory-set-config-branch'],
    },
    'doctor': {
        'summary': 'Check this device: shim, checkouts, keys, Docker image, pinned Codex and GitHub login.',
        'what': 'Runs the CLI checks and summarises doctor.py. Prints the fix for every failed check. The expected tool '
                'versions come from factory/package.json.',
        'when': 'After installing, after updates of your tools, or when a command fails for environmental reasons.',
        'examples': ['factory doctor'],
        'docs': ['docs/factory-cli.md#factory-doctor', 'docs/dev-setup.md#check-the-tools'],
    },
}

OVERVIEW = [
    ('Implementation', ['start', 'continue', 'stop', 'cancel', 'fix', 'hotfix']),
    ('Review and publication', ['review', 'submit', 'watch', 'merge', 'promote', 'update']),
    ('Branches', ['branches', 'add validation branch', 'add production branch', 'remove branch', 'set config branch']),
    ('Device', ['use branch', 'status', 'doctor']),
]


def configured(key, fallback):
    try:
        return json.loads((ROOT / 'factory/config.json').read_text())[key]
    except (OSError, ValueError, KeyError):
        return fallback


def repository():
    return configured('repository', 'Zerosteps1/Aicepeak_V2.0.0')


def link(target):
    return f'{target}  (https://github.com/{repository()}/blob/{configured("config_branch", "HEAD")}/{target})'


def description(name):
    entry = COMMANDS[name]
    return f'{entry["summary"]}\n\nWhat it does: {entry["what"]}\n\nWhen to use it: {entry["when"]}'


def epilog(name):
    entry = COMMANDS[name]
    return ('Examples (57 is a GitHub issue number, the work order; 42 a pull request number):\n'
            + '\n'.join('  ' + example for example in entry['examples'])
            + '\n\nDocumentation:\n' + '\n'.join('  ' + link(target) for target in entry['docs']))


def overview():
    lines = ['A work order is a GitHub issue opened from the "Factory work order" template; its number is the ID. In the '
             'examples 57 is that issue number (texts write #57; quote "#57" in the shell) and 42 a pull request number.',
             '',
             'Daily flow: issue on GitHub → /review and /accept on the issue → factory start workorder 57 → factory '
             'submit → factory submit --finished → factory watch 42 → factory merge 42 → factory promote <validation '
             'branch> → merge on GitHub → factory update <validation branch>', '']
    for title, names in OVERVIEW:
        lines.append(title + ':')
        lines += [f'  factory {name:<22} {COMMANDS[name]["summary"]}' for name in names]
        lines.append('')
    lines.append('Help for one command: factory <command> --help')
    lines.append('Documentation: ' + link('docs/factory-cli.md'))
    return '\n'.join(lines)

"""Work orders for the factory CLI: issue references, issue branch names and reading approved work orders.

A work order is a GitHub issue opened by a maintainer. Its issue number is the ID: texts name it `#57`, commands take
`57` or "#57", its internal name here is `issue-57` and its handoff task `#57`; tools/factory/issues.py decides whether
one is approved. Its branch is named the way GitHub names the branch of an issue: `57-export-energy-costs-as-csv`.
The only other work orders are files in docs/work/ at the config branch tip, kept for the device smoke
(docs/work/FACTORY-SMOKE.md): `factory submit` recognises them on their branch `<login>/<NAME>[-<k>]`.
"""
from __future__ import annotations

import re
import sys
sys.dont_write_bytecode = True  # Keep trusted control checkouts clean during CLI use.
import unicodedata

import common
import contracts
from common import out, require
import issues

ISSUE_NAME = re.compile(r'issue-([1-9][0-9]{0,8})')
ISSUE_REFERENCE = re.compile(r'#?0*([1-9][0-9]{0,8})')
ISSUE_BRANCH = re.compile(r'([1-9][0-9]{0,8})(?:-[^/]*)?')
BRANCH_LENGTH = 60  # GitHub's issue branch: the number, then the title's words, cut at a word boundary
HOTFIX = 'hotfix/'  # branches of hotfixes without a work order
WORK = 'docs/work/'


def path_of(name):
    return f'{WORK}{name}.md'


def name_of(path):
    require(path.startswith(WORK) and path.endswith('.md') and '/' not in path[len(WORK):], f'not a work order: {path}')
    return path[len(WORK):-3]


def is_order(path):
    return (path.startswith(WORK) and path.endswith('.md') and '/' not in path[len(WORK):]
            and re.fullmatch(r'[A-Za-z0-9_-]+', path[len(WORK):-3]) is not None)


def names_on(repo, sha):
    listing = out(repo, 'ls-tree', '--name-only', sha, WORK)
    return sorted(name_of(path) for path in listing.splitlines() if is_order(path))



def open_pulls(gh, config):
    """Open pull requests of this repository opened by configured maintainers; strangers never count."""
    pulls = gh.pages(f"/repos/{config['repository']}/pulls?state=open")
    return [pull for pull in pulls if (pull.get('head') or {}).get('repo', {}).get('full_name') == config['repository']
            and contracts.maintainer(pull.get('user'), config)]


def resolve(reference):
    """`57` or `#57` names the work-order issue 57; its internal name `issue-57` (run records) is accepted too."""
    text = str(reference).strip()
    match = ISSUE_REFERENCE.fullmatch(text) or ISSUE_NAME.fullmatch(text)
    require(match, f'{common.printable(text, 40)!r} is no GitHub issue number: name the work order as 57 or "#57"')
    return f'issue-{int(match[1])}'


def is_issue(name):
    return isinstance(name, str) and ISSUE_NAME.fullmatch(name) is not None


def number(name):
    return int(ISSUE_NAME.fullmatch(name)[1])


def task_of(name):
    return issues.task_of(number(name)) if is_issue(name) else path_of(name)


def label(name):
    """How texts name the work order: #57 (or the file's name, FACTORY-SMOKE)."""
    return task_of(name) if is_issue(name) else name


def command_reference(name):
    """How a printed command names the work order: 57, since `#57` after a space starts a shell comment."""
    return str(number(name)) if is_issue(name) else name


def read(gh, candidate, config, policy, name):
    """(text, spec) of an approved work order through issues.work_order: an issue through the maintainer's gh, the
    device smoke's file from the config tip fetched into the candidate."""
    text, spec, _ = issues.work_order(gh, config, task_of(name), policy,
                                      lambda path: common.git(candidate, 'show', f'{policy}:{path}').stdout.decode('utf-8'))
    return text, spec


def title_of(text):
    first = text.split('\n', 1)[0]
    parts = re.split(r'\s[–-]\s', first, maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else first.lstrip('# ').strip()


def heading(name, text):
    return f'{title_of(text)} {label(name)}' if is_issue(name) else f'{title_of(text)} ({name})'


def work_order_line(name):
    """The PR body's work-order lines. One work order is one PR: `Closes #57` links the PR to its issue and GitHub
    decides when to close it (on the merge into its default branch; it ignores the keyword for other targets)."""
    if not is_issue(name):
        return f'Work order: `{task_of(name)}`'
    return f'Work order: {label(name)}\n\nCloses {label(name)}'


def slug(text, length):
    """Lowercase ASCII words joined by single hyphens (with a leading one), cut at a word boundary to `length`."""
    plain = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower()
    found = ''
    for word in re.findall(r'[a-z0-9]+', plain):
        if len(found) + len(word) + 1 > length:
            break
        found += '-' + word
    return found


def branch_name(name, title):
    """The branch of a work-order issue, named as GitHub names an issue's branch: `57-export-energy-costs-as-csv`."""
    return f'{number(name)}{slug(title, BRANCH_LENGTH)}'


def is_issue_branch(branch, name):
    """`57` and `57-<anything>`: the branch of work-order issue 57, however its title was spelled."""
    match = ISSUE_BRANCH.fullmatch(branch or '')
    return bool(match) and is_issue(name) and int(match[1]) == number(name)


def is_hotfix_branch(branch):
    return isinstance(branch, str) and branch.startswith(HOTFIX)


def branch_order(branch, names):
    """The work order a branch belongs to: `57-<issue title>` (or `57`) to issue 57; `<login>/<NAME>` and
    `<login>/<NAME>-<k>` to the file work order NAME of the config branch (the device smoke)."""
    if not branch:
        return None
    match = ISSUE_BRANCH.fullmatch(branch)
    if match:
        return f'issue-{int(match[1])}'
    if '/' not in branch:
        return None
    rest = branch.split('/', 1)[1]
    for candidate in (rest, re.sub(r'-\d+$', '', rest)):
        if candidate in names:
            return candidate
    return None

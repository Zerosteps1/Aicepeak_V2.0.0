"""Work orders for the factory CLI: IDs, references, template filling and validation.

The gate's own block rules (engine.task_spec) decide validity; only the status may differ for drafts.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
sys.dont_write_bytecode = True  # Keep trusted control checkouts clean during CLI use.

import common
from common import Blocked, out, require
import engine

ID = re.compile(r'([A-Z]+)-(\d{3,})')
KINDS = ('factory', 'product', 'smoke')
WORK = 'docs/work/'
TEMPLATE = 'docs/work/TEMPLATE.md'
TASK_BLOCK = re.compile(r'```factory-task\s*\n(.*?)\n```', re.S)
HANDOFF_BLOCK = re.compile(r'```factory-handoff\s*\n(.*?)\n```', re.S)
PLACEHOLDERS = ('REPLACE-WITH-EXACT-PATHS', 'TASK-ID', 'Short outcome-oriented title',
                'When ..., the ... shall ....', 'If ..., then the ... shall ....')
DRAFT_STATUS = ('Status: draft until its `factory-task` block says `approved` and the file is merged to `main` '
                '(`factory submit workorders`).')


def path_of(name):
    return f'{WORK}{name}.md'


def name_of(path):
    require(path.startswith(WORK) and path.endswith('.md') and '/' not in path[len(WORK):], f'not a work order: {path}')
    return path[len(WORK):-3]


def is_order(path):
    return (path.startswith(WORK) and path.endswith('.md') and '/' not in path[len(WORK):]
            and path != TEMPLATE and re.fullmatch(r'[A-Za-z0-9_-]+', path[len(WORK):-3]) is not None)


def number(name):
    match = ID.fullmatch(name)
    return int(match[2]) if match else None


def names_on(repo, sha):
    listing = out(repo, 'ls-tree', '--name-only', sha, WORK)
    return sorted(name_of(path) for path in listing.splitlines() if is_order(path))


def text_on(repo, sha, name):
    return common.git(repo, 'show', f'{sha}:{path_of(name)}').stdout.decode('utf-8')


def numbers_ever_added(repo, sha):
    """Every number ever added on main, so deleted work orders never give their number away."""
    listing = out(repo, 'log', '--no-renames', '--diff-filter=A', '--name-only', '--format=', sha, '--', WORK)
    return {number(name_of(path)) for path in listing.splitlines() if is_order(path)} - {None}


def numbers_in(folder):
    folder = Path(folder) / WORK
    if not folder.is_dir():
        return set()
    return {number(item.name[:-3]) for item in folder.iterdir()
            if item.name.endswith('.md') and item.is_file() and not item.is_symlink()} - {None}


def open_pulls(gh, config):
    """Open pull requests of this repository opened by configured maintainers; strangers never count."""
    maintainers = {(m['id'], m['login']) for m in config['maintainers']}
    pulls = gh.pages(f"/repos/{config['repository']}/pulls?state=open")
    return [pull for pull in pulls
            if (pull.get('head') or {}).get('repo', {}).get('full_name') == config['repository']
            and ((pull.get('user') or {}).get('id'), (pull.get('user') or {}).get('login')) in maintainers]


def numbers_in_pulls(gh, config, pulls=None):
    used = set()
    for pull in pulls if pulls is not None else open_pulls(gh, config):
        for change in gh.pages(f"/repos/{config['repository']}/pulls/{pull['number']}/files"):
            if change.get('status') == 'added' and is_order(change.get('filename', '')):
                used.add(number(name_of(change['filename'])))
    return used - {None}


def next_name(kind, used):
    require(kind in KINDS, f'kind must be one of {", ".join(KINDS)}')
    return f'{kind.upper()}-{max(used, default=0) + 1:03d}'


def resolve(reference, names):
    """7, 007 and FACTORY-007 resolve only when exactly one work order matches."""
    reference = str(reference).strip()
    if re.fullmatch(r'\d+', reference):
        matches = [name for name in names if number(name) == int(reference)]
    else:
        matches = [name for name in names if name.upper() == reference.upper()]
    require(matches, f'no work order {reference} on main (docs/work/)')
    require(len(matches) == 1, f'work order {reference} is ambiguous: {", ".join(matches)}; use the full name')
    return matches[0]


def task_block(text):
    """The factory-task block under the gate's rules (engine.task_spec), with any status."""
    blocks = TASK_BLOCK.findall(text)
    require(len(blocks) == 1, 'exactly one factory-task block is required')
    try:
        spec = json.loads(blocks[0])
    except ValueError:
        raise Blocked('the factory-task block is not valid JSON') from None
    require(isinstance(spec, dict) and set(spec) == {'status', 'kind', 'allowed_paths'},
            'the factory-task block needs exactly the keys status, kind and allowed_paths')
    require(isinstance(spec['status'], str) and spec['status'], 'status must be a non-empty string')
    require(isinstance(spec['allowed_paths'], list) and all(isinstance(p, str) for p in spec['allowed_paths']),
            'allowed_paths must be a list of paths')
    try:
        engine.task_spec('```factory-task\n' + json.dumps({**spec, 'status': 'approved'}) + '\n```')
    except (ValueError, Blocked) as exc:
        raise Blocked(f'factory-task block: {exc}') from None
    return spec


def approved_spec(text, config):
    spec = engine.task_spec(text)
    if spec['kind'] == 'product':
        require(config['northstar_path'] and config['northstar_approved'] and config.get('product_checks_ready'),
                'product work orders stay blocked until the north star and product checks are ready (factory/config.json)')
    return spec


def fill_template(template, name, title, kind, owner, runner):
    lines = template.split('\n')
    lines[0] = f'# {name} – {title or "Short outcome-oriented title"}'
    text = '\n'.join(lines)
    text = re.sub(r'^Status: .*$', lambda _: DRAFT_STATUS, text, count=1, flags=re.M)
    spec = json.loads(TASK_BLOCK.findall(text)[0])
    spec.update(status='draft', kind=kind)
    text = TASK_BLOCK.sub(lambda _: '```factory-task\n' + json.dumps(spec, separators=(',', ':')) + '\n```', text, count=1)
    if kind != 'product':
        text = re.sub(r'^requirements: \[.*\]$', 'requirements: []', text, count=1, flags=re.M)
    transfer = {'runner': runner, 'task': path_of(name), 'owner': owner}
    return HANDOFF_BLOCK.sub(lambda _: '```factory-handoff\n' + json.dumps(transfer, separators=(',', ':')) + '\n```',
                             text, count=1)


def set_status(text, status):
    spec = task_block(text)
    spec['status'] = status
    return TASK_BLOCK.sub(lambda _: '```factory-task\n' + json.dumps(spec, separators=(',', ':')) + '\n```', text, count=1)


def problems(path, text, *, new, used_numbers):
    """Every reason this work order would be refused, so the maintainer fixes them in one pass."""
    found = []
    name = name_of(path)
    match = ID.fullmatch(name)
    if new and not match:
        found.append('new work orders are named <KIND>-<NNN>.md, for example FACTORY-008.md')
    if new and not re.fullmatch(rf'# {re.escape(name)} [–-] \S.*', text.split('\n', 1)[0]):
        found.append(f'the first line must be "# {name} – <title>"')
    try:
        spec = task_block(text)
    except Blocked as exc:
        found.append(str(exc))
        spec = None
    if spec and new and match and match[1] != spec['kind'].upper():
        found.append(f'the prefix {match[1]} does not match kind {spec["kind"]}')
    for token in PLACEHOLDERS:
        if token in text:
            found.append(f'template placeholder left: {token}')
    transfers = HANDOFF_BLOCK.findall(text)
    if len(transfers) > 1:
        found.append('at most one factory-handoff example block')
    for raw in transfers[:1]:
        try:
            transfer = json.loads(raw)
            if not isinstance(transfer, dict) or transfer.get('task') != path:
                found.append(f'the factory-handoff example must name task {path}')
        except ValueError:
            found.append('the factory-handoff example is not valid JSON')
    if new and match and int(match[2]) in used_numbers:
        found.append(f'number {match[2]} is already used on main or in an open pull request; '
                     'rename it with `factory issue` numbering')
    return [f'{path}: {item}' for item in found]


def title_of(text):
    first = text.split('\n', 1)[0]
    parts = re.split(r'\s[–-]\s', first, maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else first.lstrip('# ').strip()


def branch_order(branch, names):
    """<login>/<ID>, <login>/<ID>-<k> and <login>/<ID>-fix-<k> belong to work order <ID>."""
    if not branch or '/' not in branch:
        return None
    rest = branch.split('/', 1)[1]
    for candidate in (rest, re.sub(r'-fix-\d+$', '', rest), re.sub(r'-\d+$', '', rest)):
        if candidate in names:
            return candidate
    return None

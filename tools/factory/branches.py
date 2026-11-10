"""The branch model: validation and production branches, their gates and the config branch.

issue branch -> validation branch (gate full | tests | none) -> production branch (promotions and config PRs).
The code, configuration and policy of every gate come from the config branch (`config_branch`).
Standard library only: the dispatcher, the pipeline, the local tools and the factory CLI share it.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import sys
sys.dont_write_bytecode = True  # Keep trusted control checkouts clean during CLI use.

from contracts import KINDS, Blocked, require

GATES = ('full', 'tests', 'none')
REVIEWS = ('no', 'initiated', 'maintainer-manual')
DETERMINISTIC, SENIOR = 'factory/deterministic', 'factory/senior-review'
CHECKS = {'full': (DETERMINISTIC, SENIOR), 'tests': (DETERMINISTIC,), 'none': ()}
NAME = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?')
RESERVED = ('main', 'master', 'head')
LIMITS = {'validation': 20, 'production': 5}


def production_check(name):
    return f'factory/production/{name}'


WORK_ORDER = re.compile(r'docs/work/[^/]+\.md')
CONFIG = 'factory/config.json'


def load_config():
    """factory/config.json of this trusted checkout, the configuration the running code was reviewed with."""
    return json.loads((Path(__file__).resolve().parents[2] / CONFIG).read_text())


def work_order_approvals(config):
    """How many maintainer accounts must /accept a work-order issue and approve a config PR."""
    value = config.get('work_order_approvals')
    require(type(value) is int and 1 <= value <= len(config.get('maintainers') or []),
            'work_order_approvals must be a whole number from 1 to the number of maintainers')
    return value


def config_change(paths):
    """Whether the paths make a config PR into a production branch. Pass every path of the diff, rename sources
    included: a file renamed into docs/work must not hide that its source path changes too."""
    paths = list(paths)
    return bool(paths) and all(isinstance(p, str) and (p == CONFIG or WORK_ORDER.fullmatch(p)) for p in paths)


def problems(config):
    """Every violation of the branch model in one list, so a maintainer fixes them in one pass."""
    found = []
    data = config.get('branches')
    if not isinstance(data, dict) or set(data) != {'schema_version', 'validation', 'production'}:
        return ['branches needs exactly schema_version, validation and production']
    if data['schema_version'] != 1:
        found.append('branches.schema_version must be 1')
    logins = {str(m.get('login', '')).lower() for m in config.get('maintainers', [])}
    seen, routed = set(), {}
    for level in ('validation', 'production'):
        entries = data[level]
        if not isinstance(entries, list) or not entries or len(entries) > LIMITS[level]:
            found.append(f'branches.{level} needs 1 to {LIMITS[level]} entries')
            continue
        for entry in entries:
            keys = {'name', 'gate', 'kinds'} if level == 'validation' else {'name', 'review'}
            if not isinstance(entry, dict) or set(entry) != keys:
                found.append(f'each {level} branch needs exactly {", ".join(sorted(keys))}')
                continue
            name = entry['name']
            if not isinstance(name, str) or not NAME.fullmatch(name):
                found.append(f'invalid branch name {name!r}: lowercase letters, digits and inner hyphens, at most 40')
            elif name in RESERVED or name in logins:
                found.append(f'branch name {name} is reserved')
            elif name in seen:
                found.append(f'branch {name} is listed twice')
            seen.add(name)
            if level == 'production':
                if entry['review'] not in REVIEWS:
                    found.append(f'{name}: review must be one of {", ".join(REVIEWS)}')
                continue
            if entry['gate'] not in GATES:
                found.append(f'{name}: gate must be one of {", ".join(GATES)}')
            kinds = entry['kinds']
            if not isinstance(kinds, list) or len(set(kinds)) != len(kinds) or not set(kinds) <= set(KINDS):
                found.append(f'{name}: kinds must be distinct values of {", ".join(KINDS)}')
                continue
            for kind in kinds:
                if kind in routed:
                    found.append(f'kind {kind} is routed to both {routed[kind]} and {name}')
                routed[kind] = name
    found += [f'kind {kind} is routed to no validation branch' for kind in KINDS if kind not in routed]
    validation = {e.get('name') for e in data['validation'] if isinstance(e, dict)} if isinstance(data['validation'], list) else set()
    production = {e.get('name') for e in data['production'] if isinstance(e, dict)} if isinstance(data['production'], list) else set()
    if config.get('config_branch') not in production:
        found.append('config_branch must be a production branch')
    if config.get('default_branch') not in validation:
        found.append('default_branch must be a validation branch')
    try:
        work_order_approvals(config)
    except Blocked as exc:
        found.append(str(exc))
    return found


class Model:
    """Read-only view of a validated branch configuration."""
    def __init__(self, config):
        found = problems(config)
        require(not found, 'invalid branch configuration: ' + '; '.join(found))
        self.config_branch, self.default_branch = config['config_branch'], config['default_branch']
        self.work_order_approvals = config['work_order_approvals']
        self.validation = {e['name']: e for e in config['branches']['validation']}
        self.production = {e['name']: e for e in config['branches']['production']}

    def level(self, name):
        return 'validation' if name in self.validation else 'production' if name in self.production else None

    def gate(self, name):
        return self.validation[name]['gate'] if name in self.validation else None

    def review(self, name):
        return self.production[name]['review'] if name in self.production else None

    def route(self, kind):
        return next(name for name, entry in self.validation.items() if kind in entry['kinds'])

    @property
    def names(self):
        return [*self.validation, *self.production]

    def gated(self, name):
        return self.gate(name) in ('full', 'tests')

    def review_required(self, name):
        """A promotion into this production branch needs a passed AI review (`/review`) of its own head."""
        return self.review(name) == 'maintainer-manual'

    def required_checks(self, name):
        if name in self.validation:
            return CHECKS[self.gate(name)]
        require(name in self.production, f'{name} is not a listed branch')
        # GitHub matches required checks by commit, not by PR: the production check itself demands the AI review of
        # this PR (review_required), so a review published for another PR on the same commit never counts.
        return (DETERMINISTIC, production_check(name))


def parse(config):
    return Model(config)


def follow(read, name):
    """(config branch, its configuration), starting from the branch `name` that a copy of the code names.
    A finished change of the config branch is followed once: the configuration on `name` may name another production
    branch it lists, whose own configuration must name itself. read(branch) returns that branch's config.json data."""
    config = read(name)
    require(isinstance(config, dict), f'factory/config.json on {name} is unavailable')
    target = config.get('config_branch')
    if target == name:
        return name, config
    found = problems(config)
    require(not found, f'factory/config.json on {name} breaks the branch model: ' + '; '.join(found))
    following = read(target)  # problems() has checked that target is a listed production branch
    require(isinstance(following, dict) and following.get('config_branch') == target,
            f'factory/config.json on {name} names the config branch {target}, whose own configuration does not name '
            'itself: the change of the config branch is not finished')
    return target, following


def with_validation(config, name, gate, kinds):
    """The kinds the branch takes over leave their previous branch, so every kind stays routed to exactly one branch."""
    result = copy.deepcopy(config)
    entries = [e for e in result['branches']['validation'] if e['name'] != name]
    for entry in entries:
        entry['kinds'] = [k for k in entry['kinds'] if k not in kinds]
    previous = next((e for e in config['branches']['validation'] if e['name'] == name), None)
    position = config['branches']['validation'].index(previous) if previous else len(entries)
    entries.insert(position, {'name': name, 'gate': gate, 'kinds': list(kinds)})
    result['branches']['validation'] = entries
    return result


def with_production(config, name, review):
    result = copy.deepcopy(config)
    entries = result['branches']['production']
    for entry in entries:
        if entry['name'] == name:
            entry['review'] = review
            return result
    entries.append({'name': name, 'review': review})
    return result


def without(config, name):
    """The removed branch's routed kinds move to the default branch, so every kind stays routed."""
    require(name not in (config.get('config_branch'), config.get('default_branch')),
            f'{name} is the config or default branch and cannot be removed')
    result = copy.deepcopy(config)
    branches = result['branches']
    gone = next((e for e in branches['validation'] if e['name'] == name), None)
    branches['validation'] = [e for e in branches['validation'] if e['name'] != name]
    branches['production'] = [e for e in branches['production'] if e['name'] != name]
    if gone:
        for entry in branches['validation']:
            if entry['name'] == config['default_branch']:
                entry['kinds'] = entry['kinds'] + [k for k in gone['kinds'] if k not in entry['kinds']]
    return result


def with_config_branch(config, name):
    result = copy.deepcopy(config)
    result['config_branch'] = name
    return result


def render_branches(data):
    """Mirrors config.json's own layout, one line per branch entry, so an edit changes only the lines it must."""
    lines = ['{', f'    "schema_version": {json.dumps(data["schema_version"])},']
    for level in ('validation', 'production'):
        entries = [json.dumps(e, ensure_ascii=False) for e in data[level]]
        lines += [f'    "{level}": [', *[f'      {e},' for e in entries[:-1]], f'      {entries[-1]}',
                  '    ],' if level == 'validation' else '    ]']
    return '\n'.join(lines + ['  }'])


def _span(text, key):
    """Start and end of a top-level key's value; the two-space indent in the marker tells it from a nested key."""
    marker = f'\n  "{key}": '
    require(text.count(marker) == 1, f'factory/config.json needs exactly one top-level {key}')
    start = text.index(marker) + len(marker)
    _, end = json.JSONDecoder().raw_decode(text, start)
    return start, end


def edited(text, change):
    """`change` is one of the edit helpers above. Only the branches and config_branch spans of the text change, so
    the rest of config.json keeps its exact text; results that break the branch model are refused."""
    try:
        config = json.loads(text)
    except ValueError:
        raise Blocked('factory/config.json is not valid JSON') from None
    result = change(config)
    found = problems(result)
    require(not found, 'the change would break the branch model: ' + '; '.join(found))
    rest = lambda value: {k: v for k, v in value.items() if k not in ('branches', 'config_branch')}
    require(rest(result) == rest(config), 'branch edits may change only branches and config_branch')
    for key, value in (('branches', render_branches(result['branches'])),
                       ('config_branch', json.dumps(result['config_branch']))):
        start, end = _span(text, key)
        text = text[:start] + value + text[end:]
    require(json.loads(text) == result, 'branch configuration rendering changed its content')
    return text

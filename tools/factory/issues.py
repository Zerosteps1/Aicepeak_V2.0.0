"""Work orders as GitHub issues (ADR-0009). No provider calls.

A configured maintainer opens the issue; its number is the work-order ID (`#57`). It is an approved work order only
while it is open and the SHA-256 of its title and description equals the newest authentic approval record that the
publisher App posted after `/accept` (tools/factory/issue_review.py), so any later edit withdraws the approval until
it is accepted again. work_order() is the only reader, also for the device smoke's file in docs/work/, so every
consumer applies the same rules.
"""
import hashlib
import json
import re

import branches
from contracts import FILE_TASK, ISSUE_TASK, KINDS, TASK_BLOCK, Blocked, maintainer, require, safe_path, task_spec, validate

PRODUCT_BLOCKED = 'product work orders stay blocked until the north star and product checks are ready (factory/config.json)'
COMMAND = re.compile(r'/(review|accept|accept-force)(?=\s|$)')
# `/accept-force` accepts the newest proposal for an issue edited after it once no `/review` is left
# (limits.max_issue_reviews); an approval may name comments of either word.
ACCEPTS = ('accept', 'accept-force')

# Publisher-App records: the marker line, then one JSON line inside an HTML comment, then text for humans.
REVIEW = '<!-- factory-issue-review:v1 -->'
FINDINGS = '<!-- factory-issue-findings:v1 -->'
APPROVAL = '<!-- factory-workorder-approval:v1 -->'

_ID = {'type': 'integer', 'minimum': 1, 'maximum': 10 ** 15}
_SHA = {'type': 'string', 'pattern': '[0-9a-f]{64}'}
_KIND = {'type': 'string', 'enum': list(KINDS)}
_PATHS = {'type': 'array', 'minItems': 1, 'maxItems': 100, 'items': {'type': 'string', 'minLength': 1, 'maxLength': 300}}
SCHEMAS = {
    REVIEW: {'type': 'object', 'additionalProperties': False,
             'required': ['issue', 'text_sha256', 'kind', 'allowed_paths', 'command', 'run_id'],
             'properties': {'issue': _ID, 'text_sha256': _SHA, 'kind': _KIND, 'allowed_paths': _PATHS,
                            'command': _ID, 'run_id': _ID}},
    FINDINGS: {'type': 'object', 'additionalProperties': False, 'required': ['issue', 'text_sha256', 'command', 'run_id'],
               'properties': {'issue': _ID, 'text_sha256': _SHA, 'command': _ID, 'run_id': _ID}},
    APPROVAL: {'type': 'object', 'additionalProperties': False,
               'required': ['issue', 'text_sha256', 'reviewed_sha256', 'review', 'kind', 'allowed_paths', 'accepted_by', 'run_id'],
               'properties': {'issue': _ID, 'text_sha256': _SHA, 'reviewed_sha256': _SHA, 'review': _ID, 'kind': _KIND,
                              'allowed_paths': _PATHS, 'run_id': _ID,
                              'accepted_by': {'type': 'array', 'minItems': 1, 'maxItems': 20, 'items': {
                                  'type': 'object', 'additionalProperties': False, 'required': ['login', 'id', 'comment'],
                                  'properties': {'login': {'type': 'string', 'minLength': 1, 'maxLength': 100},
                                                 'id': _ID, 'comment': _ID}}}}},
}


def task_of(number):
    return f'#{number}'


def number_of(task):
    match = ISSUE_TASK.fullmatch(task) if isinstance(task, str) else None
    return int(match[1]) if match else None


def product_allowed(config):
    """Product work needs the approved north star and implemented product checks; only explicit `true` counts."""
    return (isinstance(config.get('northstar_path'), str) and bool(config['northstar_path'])
            and config.get('northstar_approved') is True and config.get('product_checks_ready') is True)


def issue_url(config, number):
    return f"https://api.github.com/repos/{config['repository']}/issues/{number}"


def text_sha256(issue):
    """Title and description exactly as GitHub returns them: both are the work order."""
    text = (issue.get('title') or '') + '\n' + (issue.get('body') or '')
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def document(issue):
    """The work-order text that prompts and review material carry."""
    return f"# #{issue['number']} – {issue.get('title') or ''}\n\n{issue.get('body') or ''}"


def identity(issue, config, number):
    require(isinstance(issue, dict) and issue.get('number') == number, f'issue #{number} not found')
    require('pull_request' not in issue, f'#{number} is a pull request, not a work-order issue')
    # A transferred issue redirects to its new repository.
    require(issue.get('repository_url') == f"https://api.github.com/repos/{config['repository']}",
            f'issue #{number} belongs to another repository')
    require(maintainer(issue.get('user'), config), f'issue #{number} was not opened by a configured maintainer')
    return issue


def read_issue(gh, config, number):
    """An open work-order issue; closing it withdraws the work order, reopening an unchanged one restores it."""
    issue = identity(gh.request('GET', f"/repos/{config['repository']}/issues/{number}"), config, number)
    require(issue.get('state') == 'open', f'issue #{number} is closed; reopen it to use it as a work order')
    return issue


def draft_spec(text):
    """The factory-task block of an issue under the gate's rules, with any status and possibly no paths yet."""
    blocks = TASK_BLOCK.findall(text or '')
    require(len(blocks) == 1, 'the description needs exactly one factory-task block')
    try:
        spec = json.loads(blocks[0])
    except ValueError:
        raise Blocked('the factory-task block is not valid JSON') from None
    require(isinstance(spec, dict) and set(spec) == {'status', 'kind', 'allowed_paths'},
            'the factory-task block needs exactly the keys status, kind and allowed_paths')
    require(isinstance(spec['status'], str) and spec['status'], 'status must be a non-empty string')
    require(spec['kind'] in KINDS, 'kind must be one of ' + ', '.join(KINDS))
    require(isinstance(spec['allowed_paths'], list) and all(isinstance(p, str) for p in spec['allowed_paths']),
            'allowed_paths must be a list of paths')
    for path in spec['allowed_paths']:
        safe_path(path.rstrip('/'))
    return spec


def with_block(text, spec):
    require(len(TASK_BLOCK.findall(text or '')) == 1, 'the description needs exactly one factory-task block')
    return TASK_BLOCK.sub(lambda _: '```factory-task\n' + json.dumps(spec, separators=(',', ':')) + '\n```', text, count=1)


def without_block(text):
    """Lets /accept prove that its write changed nothing in the description but the factory-task block."""
    return TASK_BLOCK.sub('```factory-task\n```', (text or '').replace('\r\n', '\n'), count=1)


def record_body(marker, data, text):
    validate(data, SCHEMAS[marker], 'record')
    # Escaped so that no value can close the HTML comment.
    line = json.dumps(data, separators=(',', ':'), sort_keys=True)
    line = line.replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    return f'{marker}\n<!-- {line} -->\n{text}'


def record(comment, config, number, marker):
    """{'id', 'data'} of an authentic, unedited publisher-App record of this issue, else None.

    Maintainers can edit any comment, so an edited record never counts."""
    if (comment.get('performed_via_github_app') or {}).get('id') != config['publisher_app_id']:
        return None
    if (comment.get('user') or {}).get('type') != 'Bot' or comment.get('issue_url') != issue_url(config, number):
        return None
    if not comment.get('created_at') or comment.get('created_at') != comment.get('updated_at'):
        return None
    lines = (comment.get('body') or '').split('\n', 2)
    if len(lines) < 2 or lines[0] != marker or not (lines[1].startswith('<!-- ') and lines[1].endswith(' -->')):
        return None
    try:
        data = json.loads(lines[1][5:-4])
        validate(data, SCHEMAS[marker], 'record')
    except (ValueError, Blocked):
        return None
    return {'id': comment['id'], 'data': data} if data['issue'] == number else None


def records(comments, config, number, marker):
    """Authentic records in posting order (comment IDs only grow)."""
    return sorted((r for r in (record(c, config, number, marker) for c in comments) if r), key=lambda r: r['id'])


def command(comment, config, number, word=None):
    """The command word for a configured maintainer's unedited command comment on this issue, else None."""
    if not maintainer(comment.get('user'), config) or comment.get('issue_url') != issue_url(config, number):
        return None
    if not comment.get('created_at') or comment.get('created_at') != comment.get('updated_at'):
        return None
    match = COMMAND.match(comment.get('body') or '')
    return match[1] if match and word in (None, match[1]) else None


def approved(gh, config, number):
    """The approved work-order issue #number, or Blocked with the reason and the way out."""
    repo = config['repository']
    issue = read_issue(gh, config, number)
    approvals = records(gh.pages(f'/repos/{repo}/issues/{number}/comments'), config, number, APPROVAL)
    require(approvals, f'issue #{number} is not an approved work order: comment /review, then /accept on the '
            'factory proposal')
    newest = approvals[-1]
    data = newest['data']
    sha = text_sha256(issue)
    require(data['text_sha256'] == sha, f'work order #{number} was edited after its approval; comment /review and '
            '/accept again')
    spec = task_spec(issue.get('body') or '')
    require(spec['kind'] == data['kind'] and spec['allowed_paths'] == data['allowed_paths'],
            f'the approval record of #{number} does not match its factory-task block')
    accepted = set()
    for entry in data['accepted_by']:
        try:
            comment = gh.request('GET', f"/repos/{repo}/issues/comments/{entry['comment']}")
        except Blocked:
            comment = {}
        user = comment.get('user') or {}
        require(command(comment, config, number) in ACCEPTS
                and (user.get('id'), user.get('login')) == (entry['id'], entry['login']),
                f'an /accept of work order #{number} was edited or deleted, or its author is no maintainer any more; '
                'comment /accept again')
        accepted.add(entry['id'])
    require(len(accepted) >= branches.work_order_approvals(config),
            f'work order #{number} has fewer /accept than work_order_approvals requires; comment /accept again')
    return {'number': number, 'task': task_of(number), 'title': issue.get('title') or '', 'text': document(issue),
            'sha256': sha, 'spec': spec, 'record': newest['id']}


def pin_of(order):
    return {'issue': order['number'], 'sha256': order['sha256'], 'record': order['record']}


def pinned(gh, config, pin):
    """The approved issue exactly as a snapshot bound it; any edit or new approval since makes the snapshot stale."""
    order = approved(gh, config, pin['issue'])
    require(pin_of(order) == pin, f"work order #{pin['issue']} changed since this run; a fresh run is needed")
    return order


def work_order(gh, config, task, policy, read_file=None):
    """(text, spec, pin) of an approved work order: an issue `#N` (the pin binds its approved text and record) or a
    docs/work file at the config tip `policy` (pin None). read_file(path) reads that file from a trusted local
    checkout of the tip; without it the GitHub API reads it."""
    number = number_of(task)
    if number is not None:
        order = approved(gh, config, number)
        text, spec, pin = order['text'], order['spec'], pin_of(order)
    else:
        require(isinstance(task, str) and FILE_TASK.fullmatch(task) is not None, 'invalid work-order reference')
        text = read_file(task) if read_file else gh.text(config['repository'], task, policy)
        spec, pin = task_spec(text), None
    require(spec['kind'] != 'product' or product_allowed(config), PRODUCT_BLOCKED)
    return text, spec, pin


def text_for(gh, config, repo, task, policy, pin):
    """The work-order text a snapshot of `repo` was bound to."""
    return pinned(gh, config, pin)['text'] if pin else gh.text(repo, task, policy)


def config_problems(config):
    found = []
    model = config.get('issue_review_model')
    if not isinstance(model, str) or re.fullmatch(r'claude-[a-z0-9.-]{1,60}', model) is None:
        found.append('issue_review_model must name a Claude model')
    limits = config.get('limits') or {}
    for key, low, high in (('max_issue_reviews', 1, 20), ('issue_review_output_tokens', 1000, 32000)):
        if type(limits.get(key)) is not int or not low <= limits[key] <= high:
            found.append(f'limits.{key} must be a whole number from {low} to {high}')
    return found

"""Maintainer commands on PRs (`/review`, `/bypass <reason>`), bypass receipts and the kind of a production PR.

Shared by the trusted pipeline (engine.py) and the production check (promotion.py). A command counts only from a
configured maintainer's unedited comment, for the head the dispatcher saw; a bypass receipt is re-read on every use.
Standard library only.
"""
from datetime import datetime
import json
import re
import sys
sys.dont_write_bytecode = True  # Keep trusted control checkouts clean during CLI use.
from urllib.parse import quote

import branches
from contracts import Blocked, maintainer, require, safe_path


def reason(text):
    """A bypass reason as the check shows it: one line of 1 to 500 characters; control characters could forge lines
    in the check output."""
    value = ' '.join((text or '').split())
    require(0 < len(value) <= 500 and not any(ord(c) < 32 or ord(c) == 127 for c in value),
            'a bypass needs a comment `/bypass <reason>` with a reason of at most 500 characters')
    return value


def bypass_reason(body):
    match = re.match(r'/bypass\s(.*)', body or '', re.S)
    return reason(match[1] if match else '')


def unedited(comment):
    """A command counts only as posted: anyone with write access may edit another account's comment."""
    require(bool(comment.get('created_at')) and comment.get('created_at') == comment.get('updated_at'),
            'the command comment was edited; post a new comment')


def commanded_head(head, current, word):
    """`head` is the one the dispatcher saw when the command was posted: a maintainer vouches for that head, not for
    commits pushed after the command."""
    require(isinstance(head, str) and re.fullmatch('[0-9a-f]{40}', head) is not None and head == current,
            f'the PR head changed after the command; post a new `{word}`')


def moment(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        raise Blocked('invalid GitHub timestamp') from None
    require(parsed.tzinfo is not None, 'invalid GitHub timestamp')
    return parsed


def bypass_origin(gh, repo, head, comment, run_id):
    """A /bypass covers only a head committed before it, in a run the dispatcher or the comment's author started."""
    commit = (gh.request('GET', f'/repos/{repo}/commits/{head}') or {}).get('commit') or {}
    require(moment((commit.get('committer') or {}).get('date')) <= moment(comment.get('created_at')),
            'the head is newer than the `/bypass` comment; post a new `/bypass`')
    run = gh.request('GET', f'/repos/{repo}/actions/runs/{run_id}')
    actor, author = run.get('triggering_actor', run.get('actor')) or {}, comment.get('user') or {}
    require((actor.get('type'), actor.get('login')) == ('Bot', 'github-actions[bot]')
            or (actor.get('type') == 'User' and actor.get('id') == author.get('id') and actor.get('login') == author.get('login')),
            'a `/bypass` run must be started by the dispatcher or by the author of the comment')


def read_bypass(gh, config, snap, comment_id):
    """(receipt, comment) of a maintainer's never-edited /bypass comment on this PR."""
    repo = snap['repository']
    comment = gh.request('GET', f'/repos/{repo}/issues/comments/{comment_id}')
    who = maintainer(comment.get('user'), config)
    require(who is not None, 'the comment is not by a configured maintainer')
    require(comment.get('issue_url') == f"https://api.github.com/repos/{repo}/issues/{snap['pr']}", 'the comment belongs to another PR')
    unedited(comment)
    return {'login': who['login'], 'id': who['id'], 'comment_id': comment_id, 'reason': bypass_reason(comment.get('body'))}, comment


def commanded_bypass(gh, config, snap, comment_id, head):
    """Receipt of a fresh /bypass dispatched for exactly the current head."""
    receipt, comment = read_bypass(gh, config, snap, comment_id)
    commanded_head(head, snap['head_sha'], '/bypass')
    bypass_origin(gh, snap['repository'], snap['head_sha'], comment, snap['run_id'])
    return receipt


def head_runs(gh, config, snap, name):
    """Every publisher-App run of check `name` on the head, whichever PR it is bound to."""
    repo, app = snap['repository'], config['publisher_app_id']
    found = gh.pages(f"/repos/{repo}/commits/{snap['head_sha']}/check-runs?check_name={quote(name, safe='')}"
                     f"&filter=all&app_id={app}", 'check_runs')
    return [c for c in found if (c.get('app') or {}).get('id') == app and c.get('name') == name and c.get('head_sha') == snap['head_sha']]


def bound_runs(gh, config, snap, name, any_policy=False):
    """Publisher-App runs of check `name` on the head, bound to this PR, target and config tip; newest first.
    any_policy also accepts other config tips, only to explain why a bypass given for one of them does not hold."""
    expected = [snap['repository'], str(snap['pr']), snap['head_sha'], snap['policy_sha'], snap['base_ref']]
    def bound(fields):
        return len(fields) == 7 and fields[:3] == expected[:3] and fields[4] == expected[4] and (any_policy or fields[3] == expected[3])
    return sorted((c for c in head_runs(gh, config, snap, name) if bound((c.get('external_id') or '').split(':'))),
                  key=lambda c: c.get('id', 0), reverse=True)


def comment_of(check):
    if (check.get('status'), check.get('conclusion')) != ('completed', 'success'):
        return None
    try:
        comment = json.loads(check['output']['text'])['bypass']['comment_id']
    except (KeyError, TypeError, ValueError):
        return None
    return comment if isinstance(comment, int) and not isinstance(comment, bool) and comment > 0 else None


def earlier_bypass(gh, config, snap, name, any_policy=False):
    """The newest bypass check run already published for this head, PR, target and config tip, so that a re-run for
    the same head (title edit, review) keeps it; None when there is none."""
    return next((c for c in bound_runs(gh, config, snap, name, any_policy) if comment_of(c)), None)


def kept_run(gh, config, snap, name, any_policy=False):
    """(bypass check run, receipt) of the bypass of `name` that still holds for this head, PR, target and config tip,
    or (None, None)."""
    check = earlier_bypass(gh, config, snap, name, any_policy)
    if check:
        try:
            return check, read_bypass(gh, config, snap, comment_of(check))[0]
        except Blocked:
            pass  # A deleted or edited bypass comment no longer bypasses.
    return None, None


def kept_bypass(gh, config, snap, name, any_policy=False):
    return kept_run(gh, config, snap, name, any_policy)[1]


def record(receipt):
    """Check-run output of a bypass; its receipt is re-read on every later use."""
    return {'title': f"Bypassed by {receipt['login']}", 'summary': f"Reason: {receipt['reason']}", 'text': json.dumps({'bypass': receipt})}


def rerun_state(gh, config, snap, stale):
    """(kept, earlier, hidden) for a same-head re-run whose factory/deterministic did not pass: kept is the receipt of the
    bypass that still holds; earlier one voided only by a newer config tip (a maintainer posts a new `/bypass`, not the
    author); hidden says a newer run on the commit hides the kept bypass, so it is published again."""
    name = branches.DETERMINISTIC
    try:
        check, kept = kept_run(gh, config, snap, name)
        earlier = None if kept else kept_bypass(gh, config, snap, name, any_policy=True)
    except Blocked:
        return None, None, False
    if not kept or stale:
        return kept, earlier, False
    try:
        # GitHub's required check reads the newest run on the commit: a failure published after the bypass (another PR on
        # this head, a lookup error) would win.
        return kept, None, max(head_runs(gh, config, snap, name), key=lambda c: c.get('id', 0), default=check)['id'] != check['id']
    except Blocked:
        return kept, None, True  # Publishing an authentic bypass of this head again is always safe.


def pr_files(gh, repo, pr):
    """The complete file list of a PR; every path and rename source is safe."""
    files = gh.pages(f"/repos/{repo}/pulls/{pr['number']}/files")
    require(len(files) == pr['changed_files'], 'incomplete PR file list')
    for file in files:
        safe_path(file['filename'])
        if file.get('previous_filename'):
            safe_path(file['previous_filename'])
    return files


def production_kind(model, repo, pr, files):
    """'promotion', 'work-order' (a config PR) or 'other' for a PR into a production branch. The pipeline and the
    production check both classify with it, so they never disagree. `files` is a callable so that a promotion, which
    may carry a whole validation branch, never reads its file list."""
    if model.level(pr['head']['ref']) == 'validation' and (pr['head'].get('repo') or {}).get('full_name') == repo:
        return 'promotion'
    paths = [p for f in files() for p in (f['filename'], f.get('previous_filename')) if p]
    return 'work-order' if branches.config_change(paths) else 'other'

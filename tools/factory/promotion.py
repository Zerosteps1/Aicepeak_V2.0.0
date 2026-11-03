"""Production check: judge a PR into a production branch and publish factory/production/<branch>.

Runs only from factory-promotion.yml on the config branch tip, with the publisher App. bypass.production_kind
classifies the PR, as the pipeline does:
(a) promotion: the head is a validation branch of this repository;
(b) work-order/config PR: only docs/work/*.md and factory/config.json, approved by two maintainer
    accounts at the current head;
(c) anything else fails.
A promotion into a branch with review maintainer-manual also needs a passed AI review (`/review`) of this PR's head.
Only (a) accepts a maintainer's `/bypass <reason>`, and only for the head it was given for.
Stale data (head, target tip or config tip moved during the run) publishes nothing.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys
sys.dont_write_bytecode = True  # Keep trusted control checkouts clean during CLI use.
import branches
from bypass import (bound_runs, bypass_reason, commanded_bypass, earlier_bypass, kept_bypass,  # noqa: F401
                    maintainer, pr_files, production_kind, read_bypass)
from contracts import Blocked, binding, require
from github_api import installation, tip

ROOT = Path(__file__).resolve().parents[2]
REFUSED = 'only promotions and work-order/config PRs may target a production branch'


def load_config():
    return json.loads((ROOT / 'factory/config.json').read_text())


def review_problem(gh, config, snap):
    """None when the newest AI review bound to this PR, head, target and config tip passed; otherwise why not.
    GitHub matches checks by commit, so a review published for another PR on the same commit never counts."""
    runs = bound_runs(gh, config, snap, branches.SENIOR)
    if not runs:
        rerun = f"gh workflow run factory-promotion.yml --repo {snap['repository']} --ref {config['config_branch']} -f pr={snap['pr']}"
        return f'the AI review of this head is missing: a maintainer comments `/review` (a review that passed since needs only a re-run of this check: `{rerun}`)'
    if runs[0].get('status') != 'completed':
        return 'awaiting the local AI review'
    return None if runs[0].get('conclusion') == 'success' else 'the AI review did not pass'


def contains(gh, repo, base, head):
    """True when head already includes base (ancestry, not pr.base.sha)."""
    compare = gh.request('GET', f'/repos/{repo}/compare/{base}...{head}?per_page=1')
    return compare.get('status') in ('ahead', 'identical') and compare.get('behind_by') == 0


def promotion_problems(gh, m, snap, pr):
    repo, source, target = snap['repository'], pr['head']['ref'], snap['base_ref']
    problems = []
    if not m.gated(source):
        problems.append(f'{source} has gate none; only gated validation branches are promoted')
    if tip(gh, repo, source) != snap['head_sha']:
        problems.append(f'the head is not the current tip of {source}')
    if not contains(gh, repo, snap['base_sha'], snap['head_sha']):
        choice = '' if len(m.production) == 1 else f' --to {target}'
        problems.append(f'{target} is not contained in the head; run `factory promote {source}{choice}`')
    others = sorted(p['number'] for p in gh.pages(f'/repos/{repo}/pulls?state=open&base={target}')
                    if p['number'] != snap['pr'] and m.level(p['head']['ref']) == 'validation'
                    and (p['head'].get('repo') or {}).get('full_name') == repo)
    if others:
        problems.append(f'another promotion into {target} is open: ' + ', '.join(f'#{n}' for n in others))
    return problems


def approvals(gh, config, snap):
    """Maintainer accounts whose latest review decision approves the current head."""
    latest = {}
    for review in sorted(gh.pages(f"/repos/{snap['repository']}/pulls/{snap['pr']}/reviews"), key=lambda r: r['id']):
        # Comments do not change a decision on GitHub; a later approval, change request or dismissal does.
        if review.get('state') in ('APPROVED', 'CHANGES_REQUESTED', 'DISMISSED'):
            latest[(review.get('user') or {}).get('id')] = review
    found = {}
    for review in latest.values():
        who = maintainer(review.get('user'), config)
        if who and review['state'] == 'APPROVED' and review.get('commit_id') == snap['head_sha']:
            found[who['id']] = who['login']
    return sorted(found.values())


def judge(gh, config, m, snap, pr, bypass_id, head=''):
    """(conclusion, output) of the production check for the PR's current head."""
    repo, source, name = snap['repository'], pr['head']['ref'], branches.production_check(snap['base_ref'])
    if pr['draft']:
        return 'failure', {'title': 'Draft PR', 'summary': 'Mark the PR ready for review; the production check then runs again.',
                           'text': json.dumps({'production': {'kind': 'draft'}})}
    kind = production_kind(m, repo, pr, lambda: pr_files(gh, repo, pr))
    if kind == 'promotion':
        problems = promotion_problems(gh, m, snap, pr)
        reviewed = m.review_required(snap['base_ref'])
        if not problems and reviewed:
            problems = [p for p in [review_problem(gh, config, snap)] if p]
        if not problems:
            return 'success', {'title': f'Promotion of {source}',
                               'summary': f"{source} at {snap['head_sha'][:12]} is its current tip, contains {snap['base_ref']} and is the only open promotion"
                                          + ('; its AI review passed.' if reviewed else '.'),
                               'text': json.dumps({'production': {'kind': 'promotion', 'problems': []}})}
        receipt = None
        if bypass_id:
            try:
                receipt = commanded_bypass(gh, config, snap, bypass_id, head)
            except Blocked as exc:
                problems.append(f'bypass refused: {exc}')
        receipt = receipt or kept_bypass(gh, config, snap, name)
        if receipt:
            return 'success', {'title': f"Bypassed by {receipt['login']}", 'summary': receipt['reason'],
                               'text': json.dumps({'bypass': receipt})}
        return 'failure', {'title': f'Promotion of {source} refused', 'summary': '; '.join(problems)[:6000],
                           'text': json.dumps({'production': {'kind': 'promotion', 'problems': problems}})}
    note = ' `/bypass` does not apply.' if bypass_id else ''
    if kind == 'work-order':
        approved = approvals(gh, config, snap)
        ok = len(approved) >= 2
        summary = (f"Approved at {snap['head_sha'][:12]} by {', '.join(approved)}." if ok else
                   f"Needs approving reviews by two maintainer accounts at {snap['head_sha'][:12]}; approved by: {', '.join(approved) or 'nobody'}.")
        return 'success' if ok else 'failure', {'title': 'Work-order/config PR', 'summary': summary + note,
                                                'text': json.dumps({'production': {'kind': 'work-order', 'approvals': approved}})}
    return 'failure', {'title': 'Refused', 'summary': REFUSED + '.' + note, 'text': json.dumps({'production': {'kind': 'other'}})}


def unchanged(gh, m, snap):
    """The PR, its target tip and the config tip are still those the check judged."""
    repo = snap['repository']
    pr = gh.request('GET', f"/repos/{repo}/pulls/{snap['pr']}")
    require(pr['state'] == 'open' and pr['draft'] == snap['draft'], 'PR closed or its draft state changed')
    require(pr['head']['sha'] == snap['head_sha'], 'stale head')
    require(pr['base']['ref'] == snap['base_ref'], 'PR target branch changed')
    require(pr['base']['sha'] == snap['base_sha'] == tip(gh, repo, snap['base_ref']), 'stale base')
    require(tip(gh, repo, m.config_branch) == snap['policy_sha'], 'stale policy')


def run(args, config, env):
    m = branches.parse(config)
    require(env.get('GITHUB_REF') == 'refs/heads/' + m.config_branch, 'factory jobs must run on the config branch')
    require(args.pr > 0 and args.bypass_comment >= 0, 'invalid PR or comment identifier')
    require(not args.bypass_comment or env.get('GITHUB_RUN_ATTEMPT') == '1', 'dispatch a fresh /bypass; job reruns cannot reuse it')
    policy = env.get('GITHUB_SHA', '')
    require(re.fullmatch('[0-9a-f]{40}', policy) is not None, 'invalid config branch revision')
    gh = installation(config, 'publisher')
    repo = config['repository']
    pr = gh.request('GET', f'/repos/{repo}/pulls/{args.pr}')
    require(pr['state'] == 'open', 'PR closed')
    require(m.level(pr['base']['ref']) == 'production', 'the production check judges only PRs into production branches')
    snap = {'repository': repo, 'pr': args.pr, 'head_sha': pr['head']['sha'], 'base_sha': pr['base']['sha'],
            'base_ref': pr['base']['ref'], 'policy_sha': policy, 'run_id': int(env['GITHUB_RUN_ID']),
            'run_attempt': int(env['GITHUB_RUN_ATTEMPT']), 'draft': pr['draft']}
    conclusion, output = judge(gh, config, m, snap, pr, args.bypass_comment, args.head)
    try:
        unchanged(gh, m, snap)
    except Blocked as exc:
        raise Blocked(f'{exc}; nothing published, the newer state gets its own run') from None
    name = branches.production_check(snap['base_ref'])
    gh.request('POST', f'/repos/{repo}/check-runs', {
        'name': name, 'head_sha': snap['head_sha'], 'status': 'completed', 'conclusion': conclusion,
        'external_id': binding(snap), 'details_url': f"https://github.com/{repo}/actions/runs/{snap['run_id']}",
        'output': output})
    return {'pr': args.pr, 'check': name, 'head_sha': snap['head_sha'], 'conclusion': conclusion, 'title': output['title']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--pr', type=int, required=True)
    parser.add_argument('--bypass-comment', type=int, default=0)
    parser.add_argument('--head', default='', help='the PR head the dispatcher saw when the /bypass was posted')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run(args, load_config(), os.environ)))
    except (Blocked, KeyError, ValueError) as exc:
        print('BLOCKED: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

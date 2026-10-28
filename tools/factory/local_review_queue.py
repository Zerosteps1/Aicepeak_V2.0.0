"""Shared local-review ownership and publication, executed only by factory.yml.

The main-only workflow's PR concurrency group serializes this module with snapshots,
retries and corrections. A local process may POST result evidence, never PATCH the gate.
Claims have no lease: a fresh maintainer retry creates a newer ledger gate and invalidates
all results for the old one. Every granted claim consumes a review slot, even on a crash.
"""
import argparse
import json
import os
import re
import sys
sys.dont_write_bytecode = True  # Keep trusted control checkouts clean during CLI use.

import engine
from contracts import Blocked, digest, gates, require, validate_review
from github_api import installation, verify_run

CODEX_VERSION = 'codex-cli 0.164.0'
REVIEWER_IDENTITY = {'host': 'maintainer-local', 'client': CODEX_VERSION, 'model': 'gpt-6-astra',
                     'effort': 'high', 'auth': 'chatgpt-workspace-access-token'}
RESULT_NAME = 'factory/local-review-result'
JOB_NAME = 'Review coordination'
MAX_RECEIPT_BYTES = 60000


def encoded(record):
    text = json.dumps(record)
    require(len(text.encode()) < MAX_RECEIPT_BYTES, 'review publication too large')
    return text


def verified_gate(gh, pr, check_id, config):
    """Re-read the latest PR-ledger gate; a fresh retry supersedes earlier owners."""
    repo = config['repository']
    checks = [c for c in engine.pr_checks(gh, {'repository': repo, 'pr': pr}, config)
              if c['name'] == 'factory/senior-review']
    require(checks, 'no senior review awaiting; wait for the pipeline run')
    check = max(checks, key=lambda item: item['id'])
    require(check['id'] == check_id, 'review superseded by a newer pipeline snapshot; use its pending check')
    record = engine.receipt(check)
    snapshot = record.get('snapshot')
    require(isinstance(snapshot, dict) and snapshot.get('repository') == repo and snapshot.get('pr') == pr
            and snapshot.get('check_id') == check_id, 'pending receipt does not match its check')
    require(check['app']['id'] == config['publisher_app_id'] and check['external_id'] == engine.bind(snapshot)
            and check['head_sha'] == snapshot['head_sha']
            and check['details_url'] == f"https://github.com/{repo}/actions/runs/{snapshot['run_id']}",
            'unauthenticated pending review')
    require(record.get('key') == snapshot['reservation']['key'], 'review reservation mismatch')
    return check, record


def require_review_budget(gh, pr, config):
    """Charge on claim, including failed, dry-run and abandoned invocations."""
    checks = engine.pr_checks(gh, {'repository': config['repository'], 'pr': pr}, config)
    records = [engine.receipt(c) for c in checks if c['name'] == 'factory/senior-review']
    require(sum(bool(r.get('claim') or r.get('reviewer')) for r in records) < config['limits']['max_reviews_per_pr'],
            'review limit for this PR reached; split the PR or raise limits.max_reviews_per_pr in a reviewed change')


def workflow_run(gh, config, snapshot, run_id, jobs):
    run = verify_run(gh, snapshot, config, jobs, run_id=run_id)
    actor = run.get('triggering_actor', run.get('actor', {}))
    require(actor.get('type') == 'User'
            and any(actor.get('id') == m['id'] and actor.get('login') == m['login'] for m in config['maintainers']),
            'review coordination requires a verified human maintainer')
    return {'id': actor['id'], 'login': actor['login']}


def require_tests(gh, record, config):
    snapshot, tests = record['snapshot'], record.get('tests', {})
    require(tests.get('ok') is True and tests.get('exit_code') == 0
            and all(tests.get(key) == snapshot[key] for key in ('repository', 'head_sha', 'policy_sha', 'run_id')),
            'deterministic checks did not pass with this binding')
    verify_run(gh, snapshot, config, {'Snapshot': ['success'], config['test_job']: ['success'], 'Publish gates': ['success']})


def claim_review(gh, config, check, record, claim_id, run_id, actor):
    snapshot = record['snapshot']
    require_tests(gh, record, config)
    engine.unchanged(gh, snapshot, config)
    require(check['status'] != 'completed', 'review already completed; dispatch a fresh maintainer retry')
    old = record.get('claim')
    if old:
        require(record.get('phase') == 'review_claimed' and old.get('id') == claim_id and old.get('actor') == actor,
                'review owned by another invocation; do not steal it; dispatch a fresh maintainer retry after failure')
        return old  # A repeated dispatch acknowledges the same grant; no extra seat reservation.
    require(record.get('phase') == 'awaiting_review', 'review is not awaiting a claim')
    require_review_budget(gh, snapshot['pr'], config)
    claim = {'id': claim_id, 'run_id': run_id, 'run_attempt': 1, 'actor': actor}
    saved = {**record, 'phase': 'review_claimed', 'claim': claim}
    gh.request('PATCH', f"/repos/{snapshot['repository']}/check-runs/{check['id']}", {
        'status': 'in_progress', 'output': {'title': 'Senior review claimed',
        'summary': f"Local review owned by {actor['login']} (claim {claim_id}). A fresh maintainer retry is required after failure; claims never expire.",
        'text': encoded(saved)}})
    return claim


def result_binding(snapshot, claim):
    return engine.bind(snapshot) + ':review-result:' + claim['id']


def validate_reviewer(reviewer):
    require(isinstance(reviewer, dict) and all(reviewer.get(key) == value for key, value in REVIEWER_IDENTITY.items()),
            'wrong local reviewer identity')
    require(set(reviewer) == set(REVIEWER_IDENTITY) | {'thread_id', 'turns', 'usage'}, 'unexpected reviewer metadata')
    require(isinstance(reviewer['thread_id'], str) and 0 < len(reviewer['thread_id']) <= 200,
            'reviewer thread missing')
    require(type(reviewer['turns']) is int and reviewer['turns'] > 0, 'reviewer completed no turn')
    require(isinstance(reviewer['usage'], dict) and len(reviewer['usage']) <= 20
            and all(isinstance(k, str) and len(k) <= 80 and type(v) is int and v >= 0
                    for k, v in reviewer['usage'].items()), 'invalid reviewer usage')


def verified_result(gh, config, check, record, claim_id, result_id):
    snapshot, claim = record['snapshot'], record.get('claim', {})
    require(claim.get('id') == claim_id, 'result does not own the review claim')
    require(claim.get('run_attempt') == 1, 'invalid claim run attempt')
    owner = workflow_run(gh, config, snapshot, claim['run_id'], {JOB_NAME: ['success']})
    require(claim.get('actor') == owner, 'claim run owner mismatch')
    result = gh.request('GET', f"/repos/{snapshot['repository']}/check-runs/{result_id}")
    require(result['app']['id'] == config['publisher_app_id'] and result['name'] == RESULT_NAME
            and result['head_sha'] == snapshot['head_sha'] and result['status'] == 'completed'
            and result['conclusion'] == 'neutral' and result['external_id'] == result_binding(snapshot, claim)
            and result['details_url'] == f"https://github.com/{snapshot['repository']}/actions/runs/{claim['run_id']}",
            'unauthenticated local review result')
    value = engine.receipt(result)
    encoded(value)
    fields = {'version', 'check_id', 'snapshot_digest', 'claim', 'review', 'reviewer', 'error', 'dry_run', 'dispatch_correction'}
    require(set(value) == fields and value['version'] == 1 and value['check_id'] == check['id']
            and value['snapshot_digest'] == digest(snapshot) and value['claim'] == claim, 'result receipt binding mismatch')
    require(type(value['dry_run']) is bool and type(value['dispatch_correction']) is bool
            and isinstance(value['error'], str) and len(value['error']) <= 1000, 'invalid local result mode')
    if value['error']:
        require(value['review'] is None and value['reviewer'] == {} and not value['dry_run'], 'invalid failed result')
        outcome = 'blocked'
    elif value['dry_run']:
        validate_reviewer(value['reviewer'])
        require(value['review'] is None, 'dry-run review content must stay local')
        outcome = 'blocked'
    else:
        validate_reviewer(value['reviewer'])
        schema = json.loads((engine.ROOT / 'factory/review.schema.json').read_text())
        outcome = validate_review(value['review'], schema, snapshot)
    return value, outcome


def finalize_review(gh, config, check, record, claim_id, result_id):
    snapshot = record['snapshot']
    value, outcome = verified_result(gh, config, check, record, claim_id, result_id)
    engine.unchanged(gh, snapshot, config)
    if check['status'] == 'completed':
        require(record.get('phase') == 'completed' and record.get('result_id') == result_id
                and record.get('result_digest') == digest(value), 'another result already completed this check')
        previous = record['review']['outcome'] if record.get('review') else 'blocked'
        notify_review(gh, config, snapshot, value, previous, record.get('reason', ''), result_id)
        return previous
    require(record.get('phase') == 'review_claimed', 'result has no active claim')
    require_tests(gh, record, config)
    # Only a matching, fresh owner can publish. A stale result does not PATCH even its old gate.
    engine.unchanged(gh, snapshot, config)
    reason = value['error'] or ('Dry run consumed this claim; no review approval published.' if value['dry_run'] else '')
    saved = {**record, 'phase': 'completed', 'review': None if reason else value['review'],
             'reviewer': value['reviewer'], 'reason': reason, 'result_id': result_id, 'result_digest': digest(value),
             'tests': {k: v for k, v in record['tests'].items() if k != 'summary'}}
    conclusion = gates(outcome, True, True, snapshot['draft'])['factory/senior-review']
    text = encoded(saved)
    engine.unchanged(gh, snapshot, config)
    gh.request('PATCH', f"/repos/{snapshot['repository']}/check-runs/{check['id']}", {
        'status': 'completed', 'conclusion': conclusion,
        'output': {'title': outcome, 'summary': (reason or value['review']['summary'])[:6000], 'text': text}})
    notify_review(gh, config, snapshot, value, outcome, reason, result_id)
    return outcome


def notify_review(gh, config, snapshot, value, outcome, reason, result_id):
    """Retry post-gate notifications without duplicating authenticated PR comments."""
    comments = gh.pages(f"/repos/{snapshot['repository']}/issues/{snapshot['pr']}/comments")
    bodies = [c.get('body', '') for c in comments
              if (c.get('performed_via_github_app') or {}).get('id') == config['publisher_app_id']]
    marker = f'<!-- factory-review-result:{result_id} -->'
    advisory = '' if 'factory/senior-review' in config['required_checks'] else ' · advisory (shadow phase)'
    body = f"Factory · Head `{snapshot['head_sha'][:12]}` · Astra/high `{outcome}` (maintainer-local reviewer){advisory}\n\n{reason or value['review']['summary']}"
    if not any(b.startswith(marker + '\n') for b in bodies):
        gh.request('POST', f"/repos/{snapshot['repository']}/issues/{snapshot['pr']}/comments", {'body': marker + '\n' + body})
    engine.remove_label(gh, snapshot, engine.AWAITING_REVIEW)
    automatic = (outcome == 'changes_requested' and not snapshot['control_changed']
                 and config.get('automatic_correction') is True and value['dispatch_correction'])
    if outcome != 'pass' and not automatic:
        handoff_marker = f'<!-- factory-review-handoff:{result_id} -->'
        if not any(b.startswith('needs-author-action: ') and handoff_marker in b for b in bodies):
            engine.needs_author(gh, snapshot, (reason or 'Senior review ' + outcome + '; address the findings in your working session.') + '\n' + handoff_marker)
    elif outcome == 'pass':
        engine.remove_label(gh, snapshot, 'needs-author-action')


def coordinate(gh, config, pr, check_id, claim_id, result_id=0):
    """Called by the sole PR-serialized publisher; never from the local CLI."""
    require(type(pr) is int and pr > 0 and type(check_id) is int and check_id > 0
            and type(result_id) is int and result_id >= 0 and re.fullmatch('[0-9a-f]{32}', claim_id or ''),
            'invalid review coordination request')
    check, record = verified_gate(gh, pr, check_id, config)
    snapshot = record['snapshot']
    require(os.environ.get('GITHUB_SHA') == snapshot['policy_sha'], 'review coordination must run the snapshot policy revision')
    run_id = int(os.environ.get('GITHUB_RUN_ID') or 0)
    require(run_id > 0 and run_id != snapshot['run_id'], 'review coordination needs its own workflow run')
    actor = workflow_run(gh, config, snapshot, run_id, {})
    if result_id:
        return finalize_review(gh, config, check, record, claim_id, result_id)
    return claim_review(gh, config, check, record, claim_id, run_id, actor)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--pr', type=int, required=True)
    parser.add_argument('--check-id', type=int, required=True)
    parser.add_argument('--claim-id', required=True)
    parser.add_argument('--result-id', type=int, default=0)
    args = parser.parse_args()
    try:
        config = engine.load_config()
        outcome = coordinate(installation(config, 'publisher'), config, args.pr, args.check_id, args.claim_id, args.result_id)
        print(json.dumps({'coordination': outcome}))
    except (Blocked, KeyError, ValueError, OSError) as exc:
        print('BLOCKED: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

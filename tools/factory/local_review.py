#!/usr/bin/env python3
"""Senior review on the maintainer's trusted machine under a ChatGPT Business access token (ADR-0005).

The pipeline leaves factory/senior-review in progress with an authenticated receipt.
This script reviews that exact snapshot in a fresh, tool-less `codex exec` session and
publishes the verdict through the publisher App. Never run it on GitHub-hosted runners.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import engine
from contracts import Blocked, gates, require, validate_review
from github_api import installation

ROOT = Path(__file__).resolve().parents[2]
CODEX_VERSION = 'codex-cli 0.164.0'
# Credentials come from the environment or the maintainer's login keychain, never from files.
KEYCHAIN = {'CODEX_ACCESS_TOKEN': 'aicepeak-factory-codex-access-token',
            'FACTORY_PUBLISHER_APP_PRIVATE_KEY': 'aicepeak-factory-publisher-key'}
# Codex 0.164.0 features that add tools or load state. Flags alone do not remove the shell:
# the generated model catalog disables it (shell_type) and apply_patch for the reviewer model.
TOOL_FEATURES = ('shell_tool', 'unified_exec', 'apps', 'plugins', 'remote_plugin', 'multi_agent', 'image_generation',
                 'view_image', 'browser_use', 'browser_use_external', 'in_app_browser', 'computer_use', 'hooks', 'goals',
                 'sleep_tool', 'skill_search', 'tool_suggest', 'workspace_dependencies', 'memories', 'code_mode_host')
# What remains: the JavaScript isolate (no file system, no network; its host is disabled, so it
# fails closed) and MCP resource helpers without any configured MCP server.
ALLOWED_TOOLS = {'exec', 'wait', 'request_user_input'}
ALLOWED_NESTED_TOOLS = {'list_mcp_resource_templates', 'list_mcp_resources', 'read_mcp_resource'}
# Event items that carry no tool use. Anything else, including unknown types, discards the review.
ALLOWED_ITEMS = {'agent_message', 'reasoning', 'todo_list', 'error'}


def secret(name):
    """Environment first, then the macOS login keychain. Values are never printed."""
    value = os.environ.get(name, '')
    if not value and sys.platform == 'darwin':
        found = subprocess.run(['security', 'find-generic-password', '-s', KEYCHAIN[name], '-w'],
                               capture_output=True, text=True, timeout=15)
        value = found.stdout.strip() if found.returncode == 0 else ''
        if value and name.endswith('_PRIVATE_KEY') and not value.startswith('-----BEGIN'):
            # Multi-line PEM is stored base64-encoded: `security` prints hex for newlines.
            value = base64.b64decode(value, validate=True).decode()
    require(value, f'{name} missing: export it or store it in the keychain item {KEYCHAIN[name]}')
    return value


def require_trusted_checkout(policy_sha):
    """Instructions and schema must come from the exact, unmodified policy revision."""
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull}
    git = ['git', '-C', str(ROOT), '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false']
    head = subprocess.run([*git, 'rev-parse', 'HEAD'], env=env, capture_output=True, text=True, timeout=15)
    status = subprocess.run([*git, 'status', '--porcelain'], env=env, capture_output=True, text=True, timeout=15)
    clean = head.returncode == status.returncode == 0 and not status.stdout.strip()
    require(clean and head.stdout.strip() == policy_sha,
            f'checkout must be the clean policy revision {policy_sha[:12]}: git switch --detach {policy_sha[:12]} (or pull main)')


def child_env(tmp, token):
    """Fresh, disposable homes: no personal config, instructions, memories or sessions."""
    for name in ('home', 'codex', 'work'):
        (tmp / name).mkdir(mode=0o700, exist_ok=True)
    return {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(tmp / 'home'), 'CODEX_HOME': str(tmp / 'codex'),
            'TMPDIR': str(tmp), 'CODEX_ACCESS_TOKEN': token}


def reviewer_catalog(catalog):
    """Only the reviewer model, without shell or patch tools."""
    models = [m for m in catalog.get('models', []) if m.get('slug') == 'gpt-6-astra']
    require(len(models) == 1, 'Codex model catalog has no gpt-6-astra entry')
    return {'models': [{**models[0], 'shell_type': 'disabled', 'apply_patch_tool_type': None, 'experimental_supported_tools': []}]}


def session_overrides(catalog_path, instructions):
    overrides = ['model="gpt-6-astra"', 'model_reasoning_effort="high"', 'sandbox_mode="read-only"', 'approval_policy="never"',
                 'web_search="disabled"', 'project_doc_max_bytes=0', 'history.persistence="none"', 'analytics.enabled=false',
                 'feedback.enabled=false', 'check_for_update_on_startup=false', 'cli_auth_credentials_store="ephemeral"',
                 'agents.enabled=false', f'model_catalog_json={json.dumps(str(catalog_path))}']
    if instructions is not None:
        overrides.append('developer_instructions=' + json.dumps(instructions, ensure_ascii=False))
    return overrides + [f'features.{feature}=false' for feature in TOOL_FEATURES]


def codex_arguments(schema_path, output_path, workdir, catalog_path, instructions):
    args = ['codex', 'exec', '--ephemeral', '--ignore-user-config', '--ignore-rules', '--strict-config', '--skip-git-repo-check',
            '--json', '--sandbox', 'read-only', '--cd', str(workdir), '--model', 'gpt-6-astra',
            '--output-schema', str(schema_path), '--output-last-message', str(output_path)]
    for override in session_overrides(catalog_path, instructions):
        args += ['-c', override]
    return args + ['-']


def check_tool_surface(items):
    """Fail closed unless the model-visible tools are exactly the inert set verified for 0.164.0.

    Nested tools are read from the exec description, which may omit deferred ones; the
    disabled code-mode host is what makes every exec call fail (regression-tested).
    """
    announced = [item for item in items if item.get('type') == 'additional_tools']
    require(len(announced) == 1, 'reviewer tool surface: expected exactly one tool announcement')
    for item in announced:
        for group in item.get('tools', []):
            require(group.get('type') == 'namespace' and group.get('name') == 'functions', 'reviewer tool surface: unexpected tool group')
            for tool in group.get('tools', []):
                require(tool.get('name') in ALLOWED_TOOLS, f"reviewer tool surface: unexpected tool {tool.get('name')}")
                nested = set(re.findall(r'declare const tools: \{ (\w+)\(', tool.get('description') or ''))
                require(nested <= ALLOWED_NESTED_TOOLS, 'reviewer tool surface: unexpected nested tool ' + ', '.join(sorted(nested - ALLOWED_NESTED_TOOLS)))


def parse_events(stdout):
    """Count turns and usage; any tool item means the tool-less contract was broken."""
    thread, turns, usage = None, 0, {}
    for line in stdout.decode(errors='replace').splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get('type')
        if kind == 'thread.started':
            thread = event.get('thread_id')
        elif kind in ('item.started', 'item.updated', 'item.completed'):
            item_type = (event.get('item') or {}).get('type')
            require(item_type in ALLOWED_ITEMS, f'reviewer used a tool ({item_type}); review discarded')
        elif kind == 'turn.completed':
            turns += 1
            for key, value in (event.get('usage') or {}).items():
                if isinstance(value, int) and not isinstance(value, bool):
                    usage[key] = usage.get(key, 0) + value
        elif kind == 'turn.failed':
            raise Blocked('reviewer turn failed: ' + str((event.get('error') or {}).get('message', ''))[:300])
    return {'thread_id': thread, 'turns': turns, 'usage': usage}


def run_codex(instructions, material, schema_path, config):
    token = secret('CODEX_ACCESS_TOKEN')
    with tempfile.TemporaryDirectory(prefix='factory-review-') as directory:
        tmp = Path(directory)
        env = child_env(tmp, token)
        version = subprocess.run(['codex', '--version'], env=env, capture_output=True, text=True, timeout=30)
        require(version.stdout.strip() == CODEX_VERSION, f'reviewer requires {CODEX_VERSION}')
        models = subprocess.run(['codex', 'debug', 'models'], env=env, cwd=tmp / 'work', capture_output=True, timeout=60)
        require(models.returncode == 0, 'could not read the Codex model catalog')
        catalog = tmp / 'catalog.json'
        catalog.write_text(json.dumps(reviewer_catalog(json.loads(models.stdout))))
        probe = ['codex', 'debug', 'prompt-input']
        for override in session_overrides(catalog, None):
            probe += ['-c', override]
        surface = subprocess.run(probe, env=env, cwd=tmp / 'work', capture_output=True, timeout=60)
        require(surface.returncode == 0, 'could not inspect the reviewer tool surface')
        check_tool_surface(json.loads(surface.stdout))
        output = tmp / 'review.json'
        result = subprocess.run(codex_arguments(schema_path, output, tmp / 'work', catalog, instructions), input=material.encode(),
                                env=env, cwd=tmp / 'work', capture_output=True, timeout=config['limits']['timeout_seconds'])
        events = parse_events(result.stdout)
        detail = result.stderr.decode(errors='replace').replace(token, '[token]')[-500:]
        require(result.returncode == 0, f'codex exec failed (exit {result.returncode}); check access token and seat limits: {detail}')
        raw = output.read_text() if output.is_file() else ''
    try:
        return json.loads(raw), events
    except ValueError:
        raise Blocked('reviewer returned no JSON review') from None


def pending_review(gh, pr, config):
    """Latest authenticated senior-review check the pipeline left awaiting review for the PR head."""
    repo = config['repository']
    head = gh.request('GET', f'/repos/{repo}/pulls/{pr}')['head']['sha']
    pending = [c for c in engine.pr_checks(gh, {'repository': repo, 'pr': pr}, config)
               if c['name'] == 'factory/senior-review' and c['head_sha'] == head and c['status'] != 'completed']
    require(pending, f'no senior review awaiting for the current head of PR #{pr}; wait for the pipeline run')
    check = max(pending, key=lambda c: c['id'])
    record = engine.receipt(check)
    snapshot = record.get('snapshot')
    require(record.get('phase') == 'awaiting_review' and isinstance(snapshot, dict) and snapshot.get('check_id') == check['id'],
            'pending receipt does not match its check')
    require(check['app']['id'] == config['publisher_app_id'] and check['external_id'] == engine.bind(snapshot)
            and snapshot['pr'] == pr and snapshot['head_sha'] == head, 'unauthenticated pending review')
    return check, record


def require_review_budget(gh, pr, config):
    """Reviews consume the maintainer's Codex seat window; cap them per PR."""
    done = [engine.receipt(c) for c in engine.pr_checks(gh, {'repository': config['repository'], 'pr': pr}, config)
            if c['name'] == 'factory/senior-review' and c['status'] == 'completed']
    require(sum(1 for r in done if r.get('reviewer')) < config['limits']['max_reviews_per_pr'],
            'review limit for this PR reached; split the PR or raise limits.max_reviews_per_pr in a reviewed change')


def dispatch_correction(config, pr, check_id):
    """The maintainer's own GitHub CLI starts the correction run on the protected default branch."""
    subprocess.run(['gh', 'workflow', 'run', Path(config['workflow']).name, '--repo', config['repository'],
                    '--ref', config['default_branch'], '-f', f'pr={pr}', '-f', f'correction={check_id}'],
                   check=True, capture_output=True, timeout=60)


def publish_review(gh, config, check, record, review, reviewer, dispatch):
    snapshot = record['snapshot']
    repo, pr = snapshot['repository'], snapshot['pr']
    outcome = validate_review(review, json.loads((ROOT / 'factory/review.schema.json').read_text()), snapshot)
    saved = {'key': record['key'], 'reserved_usd': record.get('reserved_usd', 0), 'phase': 'completed', 'review': review,
             'reviewer': reviewer, 'feedback_digest': snapshot['feedback_digest'], 'reason': '', 'snapshot': snapshot,
             'tests': {k: v for k, v in record.get('tests', {}).items() if k != 'summary'}}
    path = f"/repos/{repo}/check-runs/{check['id']}"
    try:
        engine.unchanged(gh, snapshot, config)
    except Blocked as exc:
        # A stale run only gets failure for its old SHA; the next pipeline run asks again.
        stale = {**saved, 'review': None, 'reason': 'stale: ' + str(exc)}
        gh.request('PATCH', path, {'status': 'completed', 'conclusion': 'failure',
                                   'output': {'title': 'blocked', 'summary': stale['reason'][:6000], 'text': json.dumps(stale)}})
        raise Blocked('stale snapshot: ' + str(exc)) from None
    require(gh.request('GET', path)['status'] != 'completed', 'another reviewer already completed this check')
    require(len(json.dumps(saved).encode()) < 60000, 'review publication too large')
    conclusion = gates(outcome, record.get('tests', {}).get('ok') is True, True, snapshot['draft'])['factory/senior-review']
    gh.request('PATCH', path, {'status': 'completed', 'conclusion': conclusion,
                               'output': {'title': outcome, 'summary': review['summary'][:6000], 'text': json.dumps(saved)}})
    advisory = '' if 'factory/senior-review' in config['required_checks'] else ' · advisory (shadow phase)'
    body = f"Factory · Head `{snapshot['head_sha'][:12]}` · Astra/high `{outcome}` (maintainer-local reviewer){advisory}\n\n{review['summary']}"
    gh.request('POST', f'/repos/{repo}/issues/{pr}/comments', {'body': body})
    automatic = outcome == 'changes_requested' and not snapshot['control_changed'] and config.get('automatic_correction') is True
    if automatic and dispatch:
        dispatch_correction(config, pr, check['id'])
    elif outcome != 'pass':
        engine.needs_author(gh, snapshot, 'Senior review ' + outcome + '; address the findings in your working session.')
    elif any(label['name'] == 'needs-author-action' for label in gh.pages(f'/repos/{repo}/issues/{pr}/labels')):
        gh.request('DELETE', f'/repos/{repo}/issues/{pr}/labels/needs-author-action')
    return outcome


def review_pr(gh, pr, config, dispatch, dry_run):
    check, record = pending_review(gh, pr, config)
    snapshot = record['snapshot']
    require_trusted_checkout(snapshot['policy_sha'])
    require(record.get('tests', {}).get('ok') is True, 'deterministic checks did not pass; no review requested')
    require_review_budget(gh, pr, config)
    engine.unchanged(gh, snapshot, config)
    instructions = engine.review_prompt()
    material = engine.review_material(gh, snapshot, config, record['tests'])
    require(len((instructions + material).encode()) <= config['limits']['review_input_bytes'], 'complete prompt over budget')
    review, events = run_codex(instructions, material, ROOT / 'factory/review.schema.json', config)
    reviewer = {'host': 'maintainer-local', 'client': CODEX_VERSION, 'model': 'gpt-6-astra', 'effort': 'high',
                'auth': 'chatgpt-workspace-access-token', **events}
    if dry_run:
        print(json.dumps({'review': review, 'reviewer': reviewer}, indent=2, ensure_ascii=False))
        return review.get('outcome')
    return publish_review(gh, config, check, record, review, reviewer, dispatch)


def smoke(config):
    """One tiny schema-bound turn: proves the access token, model and tool-less session."""
    with tempfile.TemporaryDirectory(prefix='factory-review-smoke-') as directory:
        schema = Path(directory) / 'schema.json'
        schema.write_text(json.dumps({'type': 'object', 'properties': {'status': {'type': 'string', 'enum': ['OK']}},
                                      'required': ['status'], 'additionalProperties': False}))
        result, events = run_codex('Return only the schema.', 'Return status OK.', schema, config)
    require(result == {'status': 'OK'}, 'smoke output unexpected')
    return {'status': 'passed', 'model': 'gpt-6-astra', 'effort': 'high', 'auth': 'CODEX_ACCESS_TOKEN', **events}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--pr', type=int, help='review the pending factory/senior-review check of this PR')
    target.add_argument('--smoke', action='store_true', help='verify access token and model with one tiny turn')
    parser.add_argument('--dry-run', action='store_true', help='print the review instead of publishing it')
    parser.add_argument('--no-dispatch', action='store_true', help='never start an automatic correction run')
    args = parser.parse_args()
    config = engine.load_config()
    try:
        if args.smoke:
            print(json.dumps(smoke(config)))
            return 0
        # Kept in this process only; the Codex child receives an explicit, minimal environment.
        os.environ['FACTORY_PUBLISHER_APP_PRIVATE_KEY'] = secret('FACTORY_PUBLISHER_APP_PRIVATE_KEY')
        outcome = review_pr(installation(config, 'publisher'), args.pr, config, not args.no_dispatch, args.dry_run)
        print(json.dumps({'pr': args.pr, 'outcome': outcome, 'published': not args.dry_run}))
    except (Blocked, KeyError, ValueError, subprocess.SubprocessError, OSError) as exc:
        print('BLOCKED: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

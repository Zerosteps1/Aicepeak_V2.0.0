#!/usr/bin/env python3
"""Senior review on the maintainer's trusted machine under a ChatGPT Business access token (ADR-0005).

The pipeline leaves factory/senior-review in progress with an authenticated receipt.
This script reviews that exact snapshot in a fresh, tool-less `codex exec` session and
submits result evidence through the publisher App. The serialized main workflow alone
claims and completes the senior gate. Never run this script on GitHub-hosted runners.
"""
import argparse
import base64
from concurrent.futures import Future, TimeoutError as FutureTimeout
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
sys.dont_write_bytecode = True  # Keep trusted control checkouts clean during CLI use.
import tempfile
import threading
import time
import uuid

import engine
import local_review_queue as queue
from contracts import Blocked, digest, require, validate_review
from github_api import installation

ROOT = Path(__file__).resolve().parents[2]
CODEX_VERSION = queue.CODEX_VERSION
REVIEW_POLL_SECONDS = 15
REVIEW_TERMINATE_SECONDS = 2
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


def check_freshness(freshness, deadline):
    """API checks stay in the trusted parent; a stalled check cannot extend model billing."""
    remaining = deadline - time.monotonic()
    require(remaining > 0, 'reviewer deadline exceeded')
    result = Future()

    def check():
        try:
            result.set_result(freshness())
        except BaseException as exc:
            result.set_exception(exc)

    # At most one check is outstanding: timeout aborts the model instead of launching another.
    # A daemon permits bounded exit even if an upstream socket ignores its own timeout.
    threading.Thread(target=check, daemon=True).start()
    try:
        result.result(timeout=min(REVIEW_POLL_SECONDS, remaining))
    except FutureTimeout:
        raise Blocked('reviewer freshness check timed out; model cancelled') from None
    require(time.monotonic() < deadline, 'reviewer deadline exceeded')


def stop_review_process(process):
    """Stop the complete dedicated process group, including children ignoring SIGTERM."""
    try:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.communicate(timeout=REVIEW_TERMINATE_SECONDS)
            except subprocess.TimeoutExpired:
                pass
    finally:
        # A child may keep running even if the group leader exited and closed its pipes.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.communicate(timeout=REVIEW_TERMINATE_SECONDS)
    except subprocess.TimeoutExpired:
        raise Blocked('reviewer process group did not stop after SIGKILL') from None


def run_review_process(args, material, *, env, cwd, timeout, freshness):
    deadline = time.monotonic() + timeout
    check_freshness(freshness, deadline)
    process = None
    old_handler = None

    def cancelled(signum, frame):
        raise Blocked('reviewer cancelled by its controller')

    if threading.current_thread() is threading.main_thread():
        old_handler = signal.signal(signal.SIGTERM, cancelled)
    try:
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=env, cwd=cwd, start_new_session=True)
        pending_input = material
        while True:
            remaining = deadline - time.monotonic()
            require(remaining > 0, 'reviewer deadline exceeded')
            try:
                stdout, stderr = process.communicate(input=pending_input, timeout=min(REVIEW_POLL_SECONDS, remaining))
            except subprocess.TimeoutExpired:
                pending_input = None  # communicate resumes its previous write; never resend the prompt.
                check_freshness(freshness, deadline)
            else:
                if process.returncode:
                    stop_review_process(process)
                check_freshness(freshness, deadline)
                return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
    except BaseException:
        if process is not None:
            stop_review_process(process)
        raise
    finally:
        if old_handler is not None:
            signal.signal(signal.SIGTERM, old_handler)
        if process is not None:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()


def run_codex(instructions, material, schema_path, config, freshness=None):
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
        args = codex_arguments(schema_path, output, tmp / 'work', catalog, instructions)
        if freshness is None:
            result = subprocess.run(args, input=material.encode(), env=env, cwd=tmp / 'work',
                                    capture_output=True, timeout=config['limits']['timeout_seconds'])
        else:
            result = run_review_process(args, material.encode(), env=env, cwd=tmp / 'work',
                                        timeout=config['limits']['timeout_seconds'], freshness=freshness)
        events = parse_events(result.stdout)
        detail = result.stderr.decode(errors='replace').replace(token, '[token]')[-500:]
        require(result.returncode == 0, f'codex exec failed (exit {result.returncode}); check access token and seat limits: {detail}')
        raw = output.read_text() if output.is_file() else ''
    try:
        return json.loads(raw), events
    except ValueError:
        raise Blocked('reviewer returned no JSON review') from None


def pending_review(gh, pr, config):
    """Only the latest authenticated gate can be claimed; never fall back to older work."""
    checks = [c for c in engine.pr_checks(gh, {'repository': config['repository'], 'pr': pr}, config)
              if c['name'] == 'factory/senior-review']
    require(checks, f'no senior review awaiting for PR #{pr}; wait for the pipeline run')
    check, record = queue.verified_gate(gh, pr, max(c['id'] for c in checks), config)
    require(check['status'] != 'completed', 'no senior review awaiting; dispatch a fresh maintainer retry')
    require(not record.get('claim'), 'review owned by another invocation; wait for it or dispatch a fresh maintainer retry after failure')
    require(record.get('phase') == 'awaiting_review', 'pending receipt does not match its check')
    return check, record


def require_review_budget(gh, pr, config):
    queue.require_review_budget(gh, pr, config)


def dispatch_correction(config, pr, check_id):
    """The maintainer's own GitHub CLI starts the correction run on the protected default branch."""
    subprocess.run(['gh', 'workflow', 'run', Path(config['workflow']).name, '--repo', config['repository'],
                    '--ref', config['default_branch'], '-f', f'pr={pr}', '-f', f'correction={check_id}'],
                   check=True, capture_output=True, timeout=60)


def dispatch_review(config, pr, check_id, claim_id, result_id=0):
    """Use the maintainer's existing Actions dispatch authority; no new App permission."""
    args = ['gh', 'workflow', 'run', Path(config['workflow']).name, '--repo', config['repository'],
            '--ref', config['default_branch'], '-f', f'pr={pr}', '-f', f'review_check={check_id}',
            '-f', f'review_claim={claim_id}']
    if result_id:
        args += ['-f', f'review_result={result_id}']
    subprocess.run(args, check=True, capture_output=True, timeout=60)


def wait_for_coordination(gh, config, pr, check_id, claim_id, result_id=0):
    deadline = time.monotonic() + config['limits']['timeout_seconds']
    while True:
        check, record = queue.verified_gate(gh, pr, check_id, config)
        engine.unchanged(gh, record['snapshot'], config)
        claim = record.get('claim')
        if claim:
            require(claim.get('id') == claim_id, 'review owned by another device; no model call authorized')
            if not result_id:
                require(check['status'] != 'completed' and record.get('phase') == 'review_claimed',
                        'claim already completed; dispatch a fresh maintainer retry')
                return check, record
        if check['status'] == 'completed':
            require(result_id and record.get('result_id') == result_id and record.get('phase') == 'completed',
                    'review completed without this result; inspect the trusted workflow')
            return check, record
        require(time.monotonic() < deadline,
                'review coordination timed out; no claim is stolen. Inspect factory.yml runs and dispatch a fresh maintainer retry if needed')
        time.sleep(5)


def submit_result(gh, config, check, record, review, reviewer, dispatch, error='', dry_run=False):
    """POST neutral evidence only. No local path can PATCH a senior gate, even on error."""
    snapshot, claim = record['snapshot'], record.get('claim')
    require(claim and record.get('phase') == 'review_claimed', 'result requires an owned review claim')
    if not error:
        validate_review(review, json.loads((ROOT / 'factory/review.schema.json').read_text()), snapshot)
        queue.validate_reviewer(reviewer)
    value = {'version': 1, 'check_id': check['id'], 'snapshot_digest': digest(snapshot), 'claim': claim,
             'review': None if dry_run else review, 'reviewer': reviewer, 'error': error, 'dry_run': dry_run,
             'dispatch_correction': dispatch}
    text = queue.encoded(value)
    result = gh.request('POST', f"/repos/{snapshot['repository']}/check-runs", {
        'name': queue.RESULT_NAME, 'head_sha': snapshot['head_sha'], 'status': 'completed', 'conclusion': 'neutral',
        'external_id': queue.result_binding(snapshot, claim),
        'details_url': f"https://github.com/{snapshot['repository']}/actions/runs/{claim['run_id']}",
        'output': {'title': 'Local review evidence; not a gate',
                   'summary': 'Awaiting serialized validation by the trusted factory workflow.', 'text': text}})
    return result['id']


def publish_review(gh, config, check, record, review, reviewer, dispatch, error='', dry_run=False):
    snapshot = record['snapshot']
    result_id = submit_result(gh, config, check, record, review, reviewer, dispatch, error, dry_run)
    claim_id = record['claim']['id']
    try:
        dispatch_review(config, snapshot['pr'], check['id'], claim_id, result_id)
    except (OSError, subprocess.SubprocessError):
        raise Blocked(f"Result {result_id} saved without completing the gate. Redispatch factory.yml on main with "
                      f"pr={snapshot['pr']}, review_check={check['id']}, review_claim={claim_id}, review_result={result_id}; "
                      'this reuses the evidence without another model call.') from None
    _, completed = wait_for_coordination(gh, config, snapshot['pr'], check['id'], claim_id, result_id)
    outcome = completed['review']['outcome'] if completed.get('review') else 'blocked'
    automatic = outcome == 'changes_requested' and not snapshot['control_changed'] and config.get('automatic_correction') is True
    if automatic and dispatch:
        dispatch_correction(config, snapshot['pr'], check['id'])
    return outcome


def require_active_claim(gh, config, snapshot, claim):
    check, record = queue.verified_gate(gh, snapshot['pr'], snapshot['check_id'], config)
    require(check['status'] != 'completed' and record.get('phase') == 'review_claimed'
            and record.get('snapshot') == snapshot and record.get('claim') == claim,
            'review claim changed; cancel this invocation')
    engine.unchanged(gh, snapshot, config)


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
    claim_id = uuid.uuid4().hex
    dispatch_review(config, pr, check['id'], claim_id)
    check, record = wait_for_coordination(gh, config, pr, check['id'], claim_id)
    try:
        review, events = run_codex(instructions, material, ROOT / 'factory/review.schema.json', config,
                                   freshness=lambda: require_active_claim(gh, config, snapshot, record['claim']))
        reviewer = {**queue.REVIEWER_IDENTITY, **events}
        validate_review(review, json.loads((ROOT / 'factory/review.schema.json').read_text()), snapshot)
        queue.validate_reviewer(reviewer)
    except (Blocked, ValueError, OSError, subprocess.SubprocessError):
        # Fixed text only; CLI/provider diagnostics may contain private material.
        publish_review(gh, config, check, record, None, {}, dispatch=False,
                       error='Local reviewer failed; inspect the local error and dispatch a fresh maintainer retry.')
        raise
    if dry_run:
        print(json.dumps({'review': review, 'reviewer': reviewer}, indent=2, ensure_ascii=False))
    return publish_review(gh, config, check, record, review, reviewer, dispatch, dry_run=dry_run)


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
    parser.add_argument('--dry-run', action='store_true', help='print the review; consumes a review claim and completes the gate as blocked')
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

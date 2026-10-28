"""Main-only WIF diagnostic. No PR execution, App keys, review gate or author runner."""
import base64
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

AUDIENCE = 'https://api.anthropic.com'
REPOSITORY = 'Zerosteps1/Aicepeak_V2.0.0'
WORKFLOW_REF = REPOSITORY + '/.github/workflows/factory.yml@refs/heads/main'


class SmokeFailure(Exception):
    """Only fixed, secret-free diagnostic messages may cross this boundary."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, 'redirect refused', headers, fp)


def request_json(stage, url, headers, data=None):
    request = urllib.request.Request(
        url, data=None if data is None else json.dumps(data).encode(), headers=headers)
    # No ambient proxy or redirect may receive credentials.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=45) as response:
            raw = response.read(131073)
        if len(raw) > 131072:
            raise SmokeFailure(stage + ': response exceeds diagnostic limit')
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise SmokeFailure(stage + ': expected JSON object')
        return result
    except urllib.error.HTTPError as exc:
        # Do not include response bodies, URLs, headers or provider error text.
        code = exc.code
        exc.close()
        raise SmokeFailure(f'{stage}: HTTP {code}; inspect Console authentication history for exchange errors') from None
    except (OSError, urllib.error.URLError, ValueError):
        raise SmokeFailure(stage + ': network timeout, connection failure or invalid JSON') from None


def smoke(config, env):
    expected_env = {
        'GITHUB_ACTIONS': 'true', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
        'GITHUB_REPOSITORY': REPOSITORY, 'GITHUB_REF': 'refs/heads/main',
        'GITHUB_WORKFLOW_REF': WORKFLOW_REF,
    }
    if any(env.get(key) != value for key, value in expected_env.items()):
        raise SmokeFailure('context: requires factory.yml dispatched on the target repository main')
    if (config.get('repository') != REPOSITORY or config.get('default_branch') != 'main'
            or config.get('environment') != 'factory-control'
            or config.get('workflow') != '.github/workflows/factory.yml'):
        raise SmokeFailure('configuration: trusted repository/workflow/environment mismatch')
    fields = ('organization_id', 'service_account_id', 'federation_rule_id', 'workspace_id')
    federation = config.get('anthropic_federation', {})
    if not isinstance(federation, dict) or any(
            not isinstance(federation.get(key), str) or not federation[key].strip() for key in fields):
        raise SmokeFailure('configuration: all four anthropic_federation IDs are required')
    model = config.get('author_models', {}).get('claude')
    if not isinstance(model, str) or not model.strip():
        raise SmokeFailure('configuration: Claude author model is required; no fallback')
    url = env.get('ACTIONS_ID_TOKEN_REQUEST_URL', '')
    request_token = env.get('ACTIONS_ID_TOKEN_REQUEST_TOKEN', '')
    try:
        parsed = urllib.parse.urlsplit(url)
        safe_endpoint = (parsed.scheme == 'https' and parsed.hostname is not None
                         and parsed.hostname.endswith('.actions.githubusercontent.com')
                         and parsed.port in (None, 443) and not parsed.username
                         and not parsed.password and not parsed.fragment)
    except ValueError:
        safe_endpoint = False
    if not safe_endpoint or not request_token:
        raise SmokeFailure('github_oidc: missing credential or unsupported GitHub token endpoint')
    query = [(key, value) for key, value in urllib.parse.parse_qsl(parsed.query) if key != 'audience']
    query.append(('audience', AUDIENCE))
    url = urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(query)))
    oidc = request_json('github_oidc', url, {'Authorization': 'Bearer ' + request_token})
    assertion = oidc.get('value')
    try:
        if not isinstance(assertion, str) or len(assertion) > 16384:
            raise ValueError()
        parts = assertion.split('.')
        if len(parts) != 3:
            raise ValueError()
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + '=' * (-len(parts[1]) % 4)))
        if not isinstance(claims, dict):
            raise ValueError()
    except (ValueError, TypeError):
        raise SmokeFailure('github_oidc: malformed assertion') from None
    # Diagnostic comparison only. Anthropic verifies the JWT signature and rule.
    expected_claims = {
        'iss': 'https://token.actions.githubusercontent.com', 'aud': AUDIENCE,
        'repository': REPOSITORY, 'ref': 'refs/heads/main',
        'repository_id': env.get('GITHUB_REPOSITORY_ID'),
        'repository_owner_id': env.get('GITHUB_REPOSITORY_OWNER_ID'),
        'workflow_ref': WORKFLOW_REF, 'environment': 'factory-control',
        'event_name': 'workflow_dispatch',
    }
    for key, value in expected_claims.items():
        if not value or claims.get(key) != value:
            raise SmokeFailure('github_oidc: claim mismatch: ' + key)
    token = request_json('token_exchange', AUDIENCE + '/v1/oauth/token',
                         {'Content-Type': 'application/json'}, {
                             'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                             'assertion': assertion, **{key: federation[key] for key in fields}})
    access_token = token.get('access_token')
    if (not isinstance(access_token, str) or not access_token.strip()
            or token.get('token_type') != 'Bearer'
            or type(token.get('expires_in')) is not int or token['expires_in'] <= 0
            or token.get('scope') not in ('workspace:inference', 'workspace:developer')):
        raise SmokeFailure('token_exchange: invalid token response or inappropriate scope')
    message = request_json('claude_message', AUDIENCE + '/v1/messages', {
        'Authorization': 'Bearer ' + access_token, 'Content-Type': 'application/json',
        'anthropic-version': '2023-06-01'}, {
            'model': model, 'max_tokens': 16,
            'messages': [{'role': 'user', 'content': 'Reply with exactly OK.'}]})
    content = message.get('content')
    if (message.get('type') != 'message' or message.get('role') != 'assistant'
            or message.get('stop_reason') != 'end_turn' or not isinstance(content, list)
            or not any(isinstance(block, dict) and block.get('type') == 'text'
                       and isinstance(block.get('text'), str) and block['text'].strip()
                       for block in content)):
        raise SmokeFailure('claude_message: missing, failed or truncated inference result; exchange succeeded')
    usage = message.get('usage', {})
    if not isinstance(usage, dict) or any(
            type(usage.get(key)) is not int or usage[key] < 0 for key in ('input_tokens', 'output_tokens')):
        raise SmokeFailure('claude_message: missing usage evidence; exchange succeeded')
    return {'status': 'passed', 'stages': ['github_oidc', 'token_exchange', 'claude_message'],
            'requested_model': model, 'scope': token['scope'], 'expires_in': token['expires_in'],
            'usage': {key: usage[key] for key in ('input_tokens', 'output_tokens')}}


def main():
    try:
        config = json.loads((Path(__file__).resolve().parents[2] / 'factory/config.json').read_text())
        result = smoke(config, os.environ)
    except SmokeFailure as exc:
        result = {'status': 'blocked', 'reason': str(exc)}
    except (OSError, ValueError, TypeError, KeyError):
        result = {'status': 'blocked', 'reason': 'configuration or response could not be validated'}
    print(json.dumps(result))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())

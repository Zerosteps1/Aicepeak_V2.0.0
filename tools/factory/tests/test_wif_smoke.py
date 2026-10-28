"""Exercise the real smoke sequence; replace only the external HTTP transport."""
import base64
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse

ROOT = Path(os.environ.get('FACTORY_CANDIDATE', Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(ROOT / 'tools/factory'))
import wif_smoke


class WIFSmokeTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'factory/config.json').read_text())
        self.config['anthropic_federation'] = {
            'organization_id': '00000000-0000-4000-8000-000000000001',
            'service_account_id': 'svac_fixture', 'federation_rule_id': 'fdrl_fixture',
            'workspace_id': 'wrkspc_fixture',
        }
        self.env = {
            'GITHUB_ACTIONS': 'true', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
            'GITHUB_REPOSITORY': 'Zerosteps1/Aicepeak_V2.0.0',
            'GITHUB_REF': 'refs/heads/main', 'GITHUB_REPOSITORY_ID': '1436114884',
            'GITHUB_REPOSITORY_OWNER_ID': '115100163',
            'GITHUB_WORKFLOW_REF': 'Zerosteps1/Aicepeak_V2.0.0/.github/workflows/factory.yml@refs/heads/main',
            'ACTIONS_ID_TOKEN_REQUEST_URL': 'https://example.actions.githubusercontent.com/oidc?api-version=2.0',
            'ACTIONS_ID_TOKEN_REQUEST_TOKEN': 'fixture-request-credential',
        }
        self.claims = {
            'iss': 'https://token.actions.githubusercontent.com',
            'aud': 'https://api.anthropic.com',
            'repository': self.env['GITHUB_REPOSITORY'], 'repository_id': '1436114884',
            'repository_owner_id': '115100163', 'ref': 'refs/heads/main',
            'workflow_ref': self.env['GITHUB_WORKFLOW_REF'],
            'event_name': 'workflow_dispatch', 'environment': 'factory-control',
        }
        self.token_response = {'access_token': 'fixture-federated-credential',
                               'token_type': 'Bearer', 'expires_in': 600,
                               'scope': 'workspace:inference'}
        self.message = {'type': 'message', 'role': 'assistant', 'id': 'msg_fixture',
                        'model': self.config['author_models']['claude'],
                        'stop_reason': 'end_turn', 'stop_sequence': None,
                        'content': [{'type': 'text', 'text': 'OK'}],
                        'usage': {'input_tokens': 12, 'output_tokens': 1}}
        self.requests = []

    def transport(self, req, timeout):
        self.requests.append(req)
        self.assertGreater(timeout, 0)
        index = len(self.requests)
        if index == 1:
            self.assertEqual(req.get_method(), 'GET')
            self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query)['audience'],
                             ['https://api.anthropic.com'])
            encoded = base64.urlsafe_b64encode(json.dumps(self.claims).encode()).decode().rstrip('=')
            data = {'value': 'header.' + encoded + '.signature'}
        elif index == 2:
            self.assertEqual(req.full_url, 'https://api.anthropic.com/v1/oauth/token')
            body = json.loads(req.data)
            self.assertEqual(body['grant_type'], 'urn:ietf:params:oauth:grant-type:jwt-bearer')
            for key, value in self.config['anthropic_federation'].items():
                self.assertEqual(body[key], value)
            self.assertTrue(body['assertion'].startswith('header.'))
            data = self.token_response
        elif index == 3:
            self.assertEqual(req.full_url, 'https://api.anthropic.com/v1/messages')
            self.assertEqual(req.get_header('Authorization'), 'Bearer fixture-federated-credential')
            body = json.loads(req.data)
            self.assertEqual(body['model'], self.config['author_models']['claude'])
            self.assertEqual(body['max_tokens'], 16)
            self.assertEqual(body['messages'], [{'role': 'user', 'content': 'Reply with exactly OK.'}])
            data = self.message
        else:
            self.fail('Unexpected extra call or retry')
        return io.BytesIO(json.dumps(data).encode())

    def run_smoke(self):
        with patch('urllib.request.OpenerDirector.open', side_effect=self.transport):
            return wif_smoke.smoke(self.config, self.env)

    def test_real_sequence_exchanges_token_and_confirms_inference_without_exposing_credentials(self):
        result = self.run_smoke()
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['stages'], ['github_oidc', 'token_exchange', 'claude_message'])
        self.assertEqual(result['usage'], {'input_tokens': 12, 'output_tokens': 1})
        self.assertEqual(len(self.requests), 3)
        self.assertNotIn('credential', json.dumps(result))

    def test_non_main_or_non_actions_context_never_requests_credentials(self):
        for key, value in [('GITHUB_ACTIONS', 'false'), ('GITHUB_EVENT_NAME', 'pull_request'),
                           ('GITHUB_REF', 'refs/heads/topic'), ('GITHUB_REPOSITORY', 'other/repo')]:
            with self.subTest(key=key):
                env = {**self.env, key: value}
                with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network forbidden')):
                    with self.assertRaises(wif_smoke.SmokeFailure):
                        wif_smoke.smoke(self.config, env)

    def test_wrong_claim_blocks_exchange_not_just_inference(self):
        for key in ('environment', 'repository_id', 'ref', 'workflow_ref', 'aud'):
            with self.subTest(key=key):
                previous = self.claims[key]
                self.claims[key] = 'unexpected'
                self.requests.clear()
                with self.assertRaisesRegex(wif_smoke.SmokeFailure, key):
                    self.run_smoke()
                self.assertEqual(len(self.requests), 1)
                self.claims[key] = previous

    def test_missing_oidc_credential_and_external_endpoint_block_before_network(self):
        for update in ({'ACTIONS_ID_TOKEN_REQUEST_TOKEN': ''},
                       {'ACTIONS_ID_TOKEN_REQUEST_URL': 'https://attacker.invalid/oidc'},
                       {'ACTIONS_ID_TOKEN_REQUEST_URL': 'https://user@example.actions.githubusercontent.com/oidc'}):
            with self.subTest(update=update):
                with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network forbidden')):
                    with self.assertRaises(wif_smoke.SmokeFailure):
                        wif_smoke.smoke(self.config, {**self.env, **update})

    def test_http_200_error_or_incomplete_token_is_not_success(self):
        good = copy.deepcopy(self.token_response)
        for bad in ({'error': 'access_denied'}, {**good, 'access_token': ''},
                    {**good, 'expires_in': 0}, {**good, 'scope': 'org:admin'}):
            with self.subTest(bad=bad):
                self.requests.clear()
                self.token_response = bad
                with self.assertRaisesRegex(wif_smoke.SmokeFailure, 'token_exchange'):
                    self.run_smoke()
                self.assertEqual(len(self.requests), 2)

    def test_failed_or_truncated_message_does_not_pass_authentication_as_full_success(self):
        for field, value in [('type', 'error'), ('stop_reason', 'max_tokens'), ('content', [])]:
            with self.subTest(field=field):
                good = copy.deepcopy(self.message)
                self.message[field] = value
                self.requests.clear()
                with self.assertRaisesRegex(wif_smoke.SmokeFailure, 'claude_message'):
                    self.run_smoke()
                self.message = good

    def test_cli_http_error_is_nonzero_and_never_prints_raw_provider_body(self):
        sensitive = 'fixture-credential-in-error-body'
        error = urllib.error.HTTPError('https://api.anthropic.com/v1/oauth/token', 401,
                                       sensitive, {}, io.BytesIO(sensitive.encode()))
        calls = 0

        def failing_exchange(req, timeout):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise error
            return self.transport(req, timeout)

        output = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(os.environ, self.env, clear=True), \
                patch('urllib.request.OpenerDirector.open', side_effect=failing_exchange), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(stderr):
            status = wif_smoke.main()
        self.assertEqual(status, 1)
        self.assertTrue(error.closed)
        self.assertNotIn(sensitive, output.getvalue() + stderr.getvalue())
        failure = json.loads(output.getvalue())
        self.assertEqual(failure['status'], 'blocked')
        self.assertIn('HTTP 401', failure['reason'])

    def test_redirect_cannot_forward_bearer_token(self):
        handler = wif_smoke.NoRedirect()
        req = urllib.request.Request('https://api.anthropic.com/v1/oauth/token',
                                     headers={'Authorization': 'Bearer fixture-credential'})
        with self.assertRaises(urllib.error.HTTPError) as failure:
            handler.redirect_request(req, None, 307, 'redirect', {}, 'https://attacker.invalid/')
        failure.exception.close()

    def test_timeout_and_malformed_json_fail_without_retry_or_credential_output(self):
        for failure in (TimeoutError('fixture-credential'),
                        urllib.error.URLError('fixture-credential')):
            with self.subTest(error=type(failure).__name__):
                with patch('urllib.request.OpenerDirector.open', side_effect=failure) as network:
                    with self.assertRaises(wif_smoke.SmokeFailure) as caught:
                        wif_smoke.smoke(self.config, self.env)
                    self.assertEqual(network.call_count, 1)
                    self.assertNotIn('fixture-credential', str(caught.exception))
        with patch('urllib.request.OpenerDirector.open', return_value=io.BytesIO(b'not JSON')):
            with self.assertRaises(wif_smoke.SmokeFailure):
                wif_smoke.smoke(self.config, self.env)


if __name__ == '__main__':
    unittest.main()

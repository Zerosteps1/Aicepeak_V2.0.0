#!/usr/bin/env python3
"""Stand-in for gh in the installer tests: `gh api <endpoint>` prints the canned response for that endpoint from the
JSON file named by FAKE_GH_RESPONSES and fails like gh (HTTP 404) for any other; `gh auth status` succeeds."""
import json
import os
import sys

args = sys.argv[1:]
if args[:2] == ['auth', 'status']:
    sys.exit(0)
endpoint = next((arg for arg in args[1:] if not arg.startswith('-')), '') if args[:1] == ['api'] else ''
path = os.environ.get('FAKE_GH_RESPONSES')
responses = json.loads(open(path).read()) if path else {}
if endpoint not in responses:
    print(f'gh: Not Found (HTTP 404): {endpoint}', file=sys.stderr)
    sys.exit(1)
print(json.dumps(responses[endpoint]))

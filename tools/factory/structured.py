"""Messages API structured outputs for the factory's direct Claude calls (issue_review.py, wif_smoke.py).

The answer comes back as one JSON text block that the API constrains to a JSON Schema (`output_config.format`).
Forced tool use is not an option: Claude Sonnet 5.5, Opus 5.5 and Fable 5.x reject `tool_choice` "tool" and "any"
with HTTP 400. The API accepts only a subset of JSON Schema, so the schema that is sent leaves out the keywords it
rejects (https://platform.claude.com/docs/en/build-with-claude/structured-outputs), and the caller's full schema is
validated locally after the call. No provider text ever appears in an error raised here.
"""
import json

from contracts import Blocked, require, validate

# Keywords the API's structured outputs reject: string lengths, numeric bounds, array bounds other than minItems 0/1.
API_UNSUPPORTED = frozenset({'$schema', 'minLength', 'maxLength', 'maxItems', 'minimum', 'maximum'})
# Limited thinking: the model thinks adaptively at low effort. Thinking counts toward max_tokens.
EFFORT = 'low'


def api_problems(schema, location='schema'):
    """The keywords of schema the API would reject, with their location; empty for an API-safe schema."""
    found = [f'{location}: {key}' for key in sorted(API_UNSUPPORTED & set(schema))]
    if schema.get('minItems', 0) not in (0, 1):
        found.append(f'{location}: minItems {schema["minItems"]}')
    if schema.get('type') == 'object' and schema.get('additionalProperties') is not False:
        found.append(f'{location}: additionalProperties must be false')
    for name, sub in (schema.get('properties') or {}).items():
        found += api_problems(sub, f'{location}.{name}')
    if isinstance(schema.get('items'), dict):
        found += api_problems(schema['items'], location + '[]')
    return found


def api_schema(schema):
    """A copy of schema without the keywords the API rejects; a minItems above 1 becomes 1."""
    sent = {}
    for key, value in schema.items():
        if key in API_UNSUPPORTED:
            continue
        if key == 'minItems':
            value = min(value, 1)
        elif key == 'properties':
            value = {name: api_schema(sub) for name, sub in value.items()}
        elif key == 'items':
            value = api_schema(value)
        elif isinstance(value, list):
            value = list(value)
        sent[key] = value
    require(not api_problems(sent), 'the schema cannot be sent as a structured output')
    return sent


def messages_body(model, max_tokens, system, content, schema):
    """One user turn whose answer must be a JSON object matching schema; no tools, no forced tool choice."""
    body = {'model': model, 'max_tokens': max_tokens, 'messages': [{'role': 'user', 'content': content}],
            'output_config': {'effort': EFFORT, 'format': {'type': 'json_schema', 'schema': api_schema(schema)}}}
    if system:
        body['system'] = system
    return body


def answer(message, schema, what='answer'):
    """(result, usage) of a Messages API response: its single JSON text block, validated against the full schema.

    Thinking blocks are ignored. Stop reasons other than end_turn, several or no text blocks, text that is not JSON
    and a missing usage block raise Blocked with a fixed message."""
    require(isinstance(message, dict) and message.get('type') == 'message' and message.get('role') == 'assistant',
            'model response invalid')
    stop = message.get('stop_reason')
    require(stop != 'refusal', f'the model refused the {what}')
    require(stop == 'end_turn', f'the model did not complete the {what} (stop reason {str(stop)[:40]})')
    texts = [block.get('text') for block in message.get('content') or []
             if isinstance(block, dict) and block.get('type') == 'text']
    require(len(texts) == 1 and isinstance(texts[0], str) and texts[0].strip(), f'the model returned no single {what}')
    try:
        result = json.loads(texts[0])
    except ValueError:
        raise Blocked(f'the model {what} is not JSON') from None
    validate(result, schema, what)
    usage = message.get('usage') or {}
    require(isinstance(usage, dict) and all(type(usage.get(key)) is int and usage[key] >= 0
                                            for key in ('input_tokens', 'output_tokens')),
            'the model returned no usage')
    return result, {key: usage[key] for key in ('input_tokens', 'output_tokens')}

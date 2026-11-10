"""Structured outputs for direct Messages API calls: the schema subset sent, the request shape, the answer checks."""
import json
import unittest

import factory_testlib  # noqa: F401  (puts the candidate first on sys.path)
import structured
from contracts import Blocked

SCHEMA = {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'type': 'object', 'additionalProperties': False,
          'required': ['name', 'items'],
          'properties': {'name': {'type': 'string', 'minLength': 1, 'maxLength': 5, 'pattern': '^[a-z]+$'},
                         'count': {'type': 'integer', 'minimum': 0, 'maximum': 3},
                         'items': {'type': 'array', 'minItems': 2, 'maxItems': 4, 'items': {
                             'type': 'object', 'additionalProperties': False, 'required': ['kind'],
                             'properties': {'kind': {'type': 'string', 'enum': ['a', 'b']}}}}}}


def message(texts, stop='end_turn', usage=None):
    return {'type': 'message', 'role': 'assistant', 'stop_reason': stop,
            'content': [{'type': 'redacted_thinking', 'data': 'x'}] + [{'type': 'text', 'text': t} for t in texts],
            'usage': {'input_tokens': 5, 'output_tokens': 7} if usage is None else usage}


class SchemaSubset(unittest.TestCase):
    def test_unsupported_keywords_are_left_out_and_reported(self):
        self.assertEqual(structured.api_problems(SCHEMA), [
            'schema: $schema', 'schema.name: maxLength', 'schema.name: minLength', 'schema.count: maximum',
            'schema.count: minimum', 'schema.items: maxItems', 'schema.items: minItems 2'])
        sent = structured.api_schema(SCHEMA)
        self.assertEqual(structured.api_problems(sent), [])
        self.assertEqual(sent['properties']['name'], {'type': 'string', 'pattern': '^[a-z]+$'})
        self.assertEqual(sent['properties']['count'], {'type': 'integer'})
        # A required non-empty array stays non-empty; the API accepts minItems 0 and 1 only.
        self.assertEqual(sent['properties']['items']['minItems'], 1)
        self.assertNotIn('maxItems', sent['properties']['items'])
        self.assertEqual(sent['properties']['items']['items']['properties']['kind']['enum'], ['a', 'b'])
        self.assertIn('maxLength', SCHEMA['properties']['name'], 'the caller keeps its full schema')

    def test_objects_must_forbid_additional_properties(self):
        loose = {'type': 'object', 'properties': {'a': {'type': 'string'}}}
        self.assertEqual(structured.api_problems(loose), ['schema: additionalProperties must be false'])
        with self.assertRaisesRegex(Blocked, 'cannot be sent'):
            structured.api_schema(loose)

    def test_request_has_a_structured_output_and_no_tools(self):
        body = structured.messages_body('claude-sonnet-5-5', 8000, 'SYSTEM', 'CONTENT', SCHEMA)
        self.assertEqual(body, {'model': 'claude-sonnet-5-5', 'max_tokens': 8000, 'system': 'SYSTEM',
                                'messages': [{'role': 'user', 'content': 'CONTENT'}],
                                'output_config': {'effort': 'low', 'format': {
                                    'type': 'json_schema', 'schema': structured.api_schema(SCHEMA)}}})
        self.assertNotIn('system', structured.messages_body('m', 16, None, 'x', SCHEMA))


class Answer(unittest.TestCase):
    GOOD = {'name': 'abc', 'items': [{'kind': 'a'}, {'kind': 'b'}]}

    def test_the_single_text_block_is_validated_against_the_full_schema(self):
        result, usage = structured.answer(message([json.dumps(self.GOOD)]), SCHEMA, 'review')
        self.assertEqual((result, usage), (self.GOOD, {'input_tokens': 5, 'output_tokens': 7}))
        for bad, reason in (({**self.GOOD, 'name': 'abcdef'}, 'string length'),
                            ({**self.GOOD, 'items': [{'kind': 'a'}]}, 'array length'),
                            ({**self.GOOD, 'count': 4}, 'numeric bounds'), ({**self.GOOD, 'x': 1}, 'extra keys')):
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(Blocked, f'^review.*{reason}'):
                    structured.answer(message([json.dumps(bad)]), SCHEMA, 'review')

    def test_failures_use_fixed_messages_without_provider_text(self):
        good = json.dumps(self.GOOD)
        cases = [(message([good], stop='max_tokens'), 'did not complete the review'),
                 (message([good], stop='refusal'), 'refused the review'),
                 (message([good], stop='SECRET' * 20), r'stop reason SECRETSECRET'),
                 (message([]), 'no single review'), (message([good, good]), 'no single review'),
                 (message([' ']), 'no single review'), (message(['SECRET']), 'review is not JSON'),
                 (message([good], usage={'input_tokens': 1}), 'no usage'),
                 ({'type': 'error', 'error': {'message': 'SECRET'}}, 'model response invalid')]
        for value, reason in cases:
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(Blocked, reason) as caught:
                    structured.answer(value, SCHEMA, 'review')
                self.assertLessEqual(str(caught.exception).count('SECRET'), 6)
        with self.assertRaises(Blocked) as caught:
            structured.answer(message(['SECRET']), SCHEMA, 'review')
        self.assertNotIn('SECRET', str(caught.exception))


if __name__ == '__main__':
    unittest.main()

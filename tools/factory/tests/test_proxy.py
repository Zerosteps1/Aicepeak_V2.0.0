"""Broker accounting through the real HTTP handler, with no sockets or credentials."""
import importlib.util
import http.client
import io
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

REPO = Path(os.environ.get("FACTORY_CANDIDATE", Path(__file__).resolve().parents[3])).resolve()
spec = importlib.util.spec_from_file_location("_factory_proxy_candidate", REPO / "tools/factory/proxy.py")
proxy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = proxy
spec.loader.exec_module(proxy)


def event(kind, **fields):
    return (f"event: {kind}\ndata: " + json.dumps({"type": kind, **fields}) + "\n\n").encode()


START = event("message_start", message={
    "id": "msg_fixture", "type": "message", "role": "assistant", "content": [],
    "model": "claude-sonnet-5-5", "stop_reason": None, "stop_sequence": None,
    "usage": {"input_tokens": 100, "cache_creation_input_tokens": 200,
              "cache_read_input_tokens": 300, "output_tokens": 1},
})
CONTENT = (event("content_block_start", index=0, content_block={"type": "text", "text": ""})
           + event("content_block_delta", index=0, delta={"type": "text_delta", "text": "generated content"})
           + event("content_block_stop", index=0))
FINAL = event("message_delta", delta={"stop_reason": "end_turn", "stop_sequence": None},
              usage={"output_tokens": 42})
STOP = event("message_stop")


class MemoryConnection:
    """Only the socket transport is replaced; HTTP parsing and handling stay real."""
    def __init__(self, request):
        self.reader = io.BytesIO(request)
        self.output = bytearray()

    def makefile(self, *args):
        return self.reader

    def sendall(self, data):
        self.output.extend(data)

    def settimeout(self, timeout):
        pass


class Upstream:
    status = 200
    headers = {"Content-Type": "text/event-stream"}

    def __init__(self, chunks):
        self.chunks = iter(chunks)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read1(self, limit):
        chunk = next(self.chunks, b"")
        if isinstance(chunk, Exception):
            raise chunk
        return chunk() if callable(chunk) else chunk


class HandlerAccountingTests(unittest.TestCase):
    def setUp(self):
        self.policy = proxy.BrokerPolicy({
            "runner": "claude", "model": "claude-sonnet-5-5", "timeout": 900,
            "input_price": 2, "cache_write_price": 2.5, "cache_read_price": 0.2,
            "output_price": 10, "max_cost": 12, "max_output": 200000,
            "request_output": 32000, "max_requests": 200,
        })
        self.requests = []

    def request(self, chunks, **overrides):
        body = json.dumps({"model": "claude-sonnet-5-5", "messages": [], "max_tokens": 128000,
                           "stream": True, **overrides}).encode()
        request = (b"POST /anthropic/v1/messages HTTP/1.1\r\nHost: credential-proxy\r\n"
                   b"Authorization: Bearer job-fixture\r\nConnection: close\r\nContent-Length: "
                   + str(len(body)).encode() + b"\r\n\r\n" + body)
        connection = MemoryConnection(request)

        def open_upstream(request, timeout):
            self.requests.append(request)
            if isinstance(chunks, Exception):
                raise chunks
            return Upstream(chunks)

        with mock.patch.object(proxy.urllib.request, "build_opener", return_value=types.SimpleNamespace(open=open_upstream)):
            proxy.make_handler(self.policy, {"job": "job-fixture", "claude": "provider-fixture"})(
                connection, ("127.0.0.1", 12345), object())
        return bytes(connection.output)

    def assert_reservation_held(self):
        self.assertEqual(self.policy.reserved_output, 32000)
        self.assertGreater(self.policy.reserved_cost, 0.32)

    def test_complete_stream_settles_final_cumulative_usage(self):
        raw = START + CONTENT + event("message_delta", usage={"output_tokens": 20}, delta={}) + FINAL + STOP
        response = self.request([raw[i:i + 7] for i in range(0, len(raw), 7)])
        self.assertTrue(response.startswith(b"HTTP/1.1 200"))
        self.assertEqual(response.split(b"\r\n\r\n", 1)[1], raw)
        self.assertEqual(self.policy.reserved_output, 42)
        self.assertAlmostEqual(self.policy.reserved_cost, 0.00118)

    def test_completed_long_output_is_forwarded_and_accounted(self):
        final = event("message_delta", delta={"stop_reason": "max_tokens", "stop_sequence": None},
                      usage={"output_tokens": 10000})
        self.request([START + CONTENT + final + STOP])
        self.assertEqual(json.loads(self.requests[0].data)["max_tokens"], 32000)
        self.assertEqual(self.policy.reserved_output, 10000)
        self.assertAlmostEqual(self.policy.reserved_cost, 0.10076)

    def test_clean_eof_without_terminal_usage_keeps_reservation(self):
        for tail in (b"", STOP, FINAL, event("message_delta", delta={}, usage={"output_tokens": 20}) + STOP):
            with self.subTest(tail=tail):
                self.setUp()
                self.request([START + CONTENT + tail])
                self.assert_reservation_held()

    def test_stream_error_keeps_reservation_even_if_followed_by_terminal_events(self):
        self.request([START + CONTENT + event("error", error={"type": "overloaded_error", "message": "Overloaded"}), FINAL + STOP])
        self.assert_reservation_held()

    def test_malformed_usage_keeps_reservation(self):
        for usage in ({}, {"output_tokens": -1}, {"output_tokens": True}, {"output_tokens": "42"}):
            with self.subTest(usage=usage):
                self.setUp()
                self.request([START + CONTENT + event("message_delta", delta={"stop_reason": "end_turn"}, usage=usage) + STOP])
                self.assert_reservation_held()

    def test_missing_input_usage_keeps_reservation(self):
        start = event("message_start", message={"usage": {"output_tokens": 1}})
        self.request([start + CONTENT + FINAL + STOP])
        self.assert_reservation_held()

    def test_malformed_sse_before_terminal_events_keeps_reservation(self):
        self.request([START + CONTENT + b"event: message_delta\ndata: invalid-json\n\n" + FINAL + STOP])
        self.assert_reservation_held()

    def test_transport_error_keeps_reservation(self):
        for error in (OSError("connection lost"), TimeoutError("timed out"),
                      http.client.IncompleteRead(b"partial", 10), ValueError("malformed response")):
            with self.subTest(error=type(error).__name__):
                self.setUp()
                response = self.request([START + CONTENT, error])
                self.assert_reservation_held()
                self.assertEqual(response.count(b"HTTP/1.1"), 1)

    def test_http_error_after_stream_started_keeps_reservation(self):
        error = proxy.urllib.error.HTTPError("https://api.anthropic.com/v1/messages", 503, "unavailable", {}, None)
        self.addCleanup(error.close)
        response = self.request([START + CONTENT, error])
        self.assert_reservation_held()
        self.assertEqual(response.count(b"HTTP/1.1"), 1)

    def test_http_rejection_before_response_returns_reservation(self):
        error = proxy.urllib.error.HTTPError("https://api.anthropic.com/v1/messages", 429, "rejected", {}, None)
        self.addCleanup(error.close)
        response = self.request(error)
        self.assertTrue(response.startswith(b"HTTP/1.1 502"))
        self.assertEqual((self.policy.reserved_cost, self.policy.reserved_output), (0, 0))

    def test_partial_sse_event_after_completion_keeps_reservation(self):
        self.request([START + CONTENT + FINAL + STOP + b"event: error\n"])
        self.assert_reservation_held()

    def test_decreasing_cumulative_output_keeps_reservation(self):
        intermediate = event("message_delta", delta={}, usage={"output_tokens": 100})
        self.request([START + CONTENT + intermediate + FINAL + STOP])
        self.assert_reservation_held()

    def test_token_dense_input_cannot_use_an_average_bytes_per_token_estimate(self):
        self.policy.policy["max_cost"] = 0.12
        body = json.dumps({"model": "claude-sonnet-5-5", "max_tokens": 1,
                           "messages": [{"role": "user", "content": "界" * 20000}]}, ensure_ascii=False).encode()
        # Even the 60,000 content bytes alone cost $0.15 at the permitted cache
        # write rate under a one-token-per-byte reservation, before overhead.
        with self.assertRaisesRegex(proxy.Denied, "cost budget"):
            self.policy.prepare("/anthropic/v1/messages", body)
        self.assertEqual((self.policy.requests, self.policy.reserved_cost), (0, 0))

    def test_local_deadline_cutoff_after_terminal_event_keeps_reservation(self):
        def expire():
            self.policy.started -= 901
            return b"event: ping\ndata: {\"type\":\"ping\"}\n\n"
        self.request([START + CONTENT + FINAL + STOP, expire])
        self.assert_reservation_held()

    def test_interrupted_stream_does_not_reopen_output_budget(self):
        self.policy.policy["max_output"] = 32000
        self.request([START + CONTENT])
        response = self.request([START + CONTENT + FINAL + STOP])
        self.assertTrue(response.startswith(b"HTTP/1.1 403"))
        self.assertEqual(len(self.requests), 1)
        self.assert_reservation_held()

    def test_plain_complete_message_settles_usage(self):
        raw = json.dumps({"type": "message", "stop_reason": "end_turn", "usage": {
            "input_tokens": 100, "output_tokens": 42, "cache_creation_input_tokens": 200,
            "cache_read_input_tokens": 300}}).encode()
        self.request([raw], stream=False)
        self.assertEqual(self.policy.reserved_output, 42)
        self.assertAlmostEqual(self.policy.reserved_cost, 0.00118)

    def test_plain_incomplete_usage_keeps_reservation(self):
        for message in (
            {"type": "message", "stop_reason": "end_turn", "usage": {"output_tokens": 42}},
            {"type": "message", "stop_reason": True, "usage": {"input_tokens": 100, "output_tokens": 42}},
        ):
            with self.subTest(message=message):
                self.setUp()
                self.request([json.dumps(message).encode()], stream=False)
                self.assert_reservation_held()

    def test_one_hour_cache_is_rejected_before_upstream_or_reservation(self):
        block = {"type": "text", "text": "cache this", "cache_control": {"type": "ephemeral", "ttl": "1h"}}
        for fields in (
            {"system": [block]},
            {"messages": [{"role": "user", "content": [block]}]},
            {"tools": [{"name": "local_tool", "input_schema": {"type": "object"}, "cache_control": block["cache_control"]}]},
            {"system": [{"type": "text", "text": "five minutes", "cache_control": {"type": "ephemeral", "ttl": "5m"}}, block]},
        ):
            with self.subTest(fields=fields):
                self.setUp()
                response = self.request([START + FINAL + STOP], **fields)
                self.assertTrue(response.startswith(b"HTTP/1.1 403"))
                self.assertIn(b"cache", response)
                self.assertEqual(self.requests, [])
                self.assertEqual((self.policy.requests, self.policy.reserved_cost, self.policy.reserved_output), (0, 0, 0))

    def test_default_and_explicit_five_minute_cache_remain_supported(self):
        for cache_control in ({"type": "ephemeral"}, {"type": "ephemeral", "ttl": "5m"}):
            with self.subTest(cache_control=cache_control):
                self.setUp()
                system = [{"type": "text", "text": "cache this", "cache_control": cache_control}]
                response = self.request([START + FINAL + STOP], system=system)
                self.assertTrue(response.startswith(b"HTTP/1.1 200"))
                self.assertEqual(json.loads(self.requests[0].data)["system"], system)
                self.assertAlmostEqual(self.policy.reserved_cost, 0.00118)

    def test_repeated_one_hour_cache_denials_leave_tight_budget_for_supported_request(self):
        self.policy.policy["max_cost"] = 0.36
        for _ in range(3):
            response = self.request([START + FINAL + STOP], system=[{
                "type": "text", "text": "cache this", "cache_control": {"type": "ephemeral", "ttl": "1h"}}])
            self.assertTrue(response.startswith(b"HTTP/1.1 403"))
        self.assertEqual(self.requests, [])
        response = self.request([START + FINAL + STOP])
        self.assertTrue(response.startswith(b"HTTP/1.1 200"))
        self.assertEqual(self.policy.requests, 1)
        self.assertAlmostEqual(self.policy.reserved_cost, 0.00118)


if __name__ == "__main__":
    unittest.main()

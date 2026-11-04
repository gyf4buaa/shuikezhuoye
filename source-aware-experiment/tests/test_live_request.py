"""Outgoing request-shape tests for the OpenAI-compatible live transport.

These tests never touch the network.  They pin the URL, model, decoding
parameters and Authorization header shape, which is what we can verify locally
for the OpenCode endpoint without a credential.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from srcaware.live import LiveConfig, LiveError, chat, estimate_messages_tokens


class RequestShapeTests(unittest.TestCase):
    def test_utf8_preflight_counts_bytes_and_message_overhead(self) -> None:
        messages = [{"role": "user", "content": "你好"}]
        self.assertGreaterEqual(estimate_messages_tokens(messages), len("user你好".encode("utf-8")) + 48)

    def test_opencode_request_shape(self) -> None:
        captured = {}

        def transport(url, headers, payload, timeout):
            captured.update(url=url, headers=headers, payload=payload, timeout=timeout)
            return {
                "id": "resp-shape",
                "choices": [{"message": {"content": '{"translation": "x"}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }

        config = LiveConfig(
            base_url="https://opencode.ai/inference/openai/v1/",
            api_key="test-key-not-a-real-credential",
            model="deepseek-v4.1-flash",
            temperature=0.0,
            max_output_tokens=64,
        )
        result = chat(
            [{"role": "system", "content": "system"}, {"role": "user", "content": "source"}],
            config,
            transport=transport,
        )
        self.assertEqual(captured["url"], "https://opencode.ai/inference/openai/v1/chat/completions")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-key-not-a-real-credential")
        self.assertEqual(captured["headers"]["User-Agent"], "opencode/1.0")
        self.assertEqual(captured["payload"]["model"], "deepseek-v4.1-flash")
        self.assertEqual(captured["payload"]["temperature"], 0.0)
        self.assertEqual(captured["payload"]["max_tokens"], 64)
        self.assertEqual(captured["payload"]["messages"][1]["role"], "user")
        self.assertEqual(result.total_tokens, 2)

    def test_provider_model_is_recorded(self) -> None:
        config = LiveConfig("https://example.invalid/v1", "key", "requested")
        result = chat([], config, transport=lambda *args: {
            "model": "provider-resolved-model",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        })
        self.assertEqual(result.model, "provider-resolved-model")

    def test_transport_exception_does_not_echo_api_key_and_has_latency(self) -> None:
        key = "key-that-must-not-leak"
        config = LiveConfig("https://example.invalid/v1", key, "m")

        def broken(*args):
            raise RuntimeError("request failed for " + key)

        with self.assertRaises(LiveError) as caught:
            chat([], config, transport=broken)
        self.assertNotIn(key, str(caught.exception))
        self.assertIsNotNone(caught.exception.latency_ms)

    def test_malformed_provider_response_keeps_safe_metadata(self) -> None:
        key = "secret-key"
        config = LiveConfig("https://example.invalid/v1", key, "requested")
        with self.assertRaises(LiveError) as caught:
            chat([], config, transport=lambda *args: {
                "model": "resolved", "usage": {"prompt_tokens": 2},
                "choices": [], "debug": key,
            })
        self.assertEqual(caught.exception.model, "resolved")
        self.assertEqual(caught.exception.usage, {"prompt_tokens": 2})
        self.assertNotIn(key, caught.exception.raw_response or "")
        self.assertIsNotNone(caught.exception.latency_ms)

    def test_config_repr_hides_key(self) -> None:
        config = LiveConfig(
            base_url="https://example.invalid/v1",
            api_key="secret-value",
            model="m",
        )
        self.assertNotIn("secret-value", repr(config))


if __name__ == "__main__":
    unittest.main()

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

from srcaware.live import LiveConfig, chat


class RequestShapeTests(unittest.TestCase):
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
        self.assertEqual(captured["payload"]["model"], "deepseek-v4.1-flash")
        self.assertEqual(captured["payload"]["temperature"], 0.0)
        self.assertEqual(captured["payload"]["max_tokens"], 64)
        self.assertEqual(captured["payload"]["messages"][1]["role"], "user")
        self.assertEqual(result.total_tokens, 2)

    def test_config_repr_hides_key(self) -> None:
        config = LiveConfig(
            base_url="https://example.invalid/v1",
            api_key="secret-value",
            model="m",
        )
        self.assertNotIn("secret-value", repr(config))


if __name__ == "__main__":
    unittest.main()

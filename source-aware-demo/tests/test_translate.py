"""Translation comparison tests: disabled mode, prompts, caps, redaction."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sourceaware.catalog import Catalog  # noqa: E402
from sourceaware.config import LLMConfig  # noqa: E402
from sourceaware.retrieval import search  # noqa: E402
from sourceaware.translate import (  # noqa: E402
    TranslationError,
    Translator,
    build_evidence_context,
)

PROJECT = ROOT / "demo_project"
SECRET = "sk-test-secret"


def make_config(**overrides: Any) -> LLMConfig:
    values: Dict[str, Any] = {
        "base_url": "https://api.example.test/v1",
        "api_key": SECRET,
        "model": "test-model",
        "timeout": 5.0,
        "max_output_tokens": 128,
        "max_context_chars": 2000,
    }
    values.update(overrides)
    return LLMConfig(**values)


class FakeTransport:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        self.calls.append(payload)
        content = {
            "translation": "译文%d" % len(self.calls),
            "rationale": "基于第 %d 次调用" % len(self.calls),
        }
        return {
            "choices": [{"message": {"content": "```json\n%s\n```" % json.dumps(content, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }


class TranslationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = Catalog(PROJECT)
        self.record = self.catalog.get("ui.leaderboard.rank_column")
        self.payload = search(self.catalog, self.record.key)
        self.evidence = self.payload["evidence"]

    def test_disabled_mode_never_calls_transport_or_returns_a_translation(self) -> None:
        transport = FakeTransport()
        translator = Translator(make_config(api_key=""), transport=transport)
        result = translator.compare(self.record, self.evidence, "pt-BR")
        self.assertEqual(result["status"], "disabled")
        self.assertFalse(result["live"])
        self.assertIsNone(result["baseline"])
        self.assertIsNone(result["contextual"])
        self.assertIn("未调用模型", result["message"])
        self.assertEqual(transport.calls, [])

    def test_two_calls_share_model_and_parameters_but_not_evidence(self) -> None:
        transport = FakeTransport()
        translator = Translator(make_config(), transport=transport)
        result = translator.compare(self.record, self.evidence, "pt-BR")

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["live"])
        self.assertEqual(result["model"], "test-model")
        self.assertEqual(len(transport.calls), 2)
        baseline_payload, contextual_payload = transport.calls
        for payload in transport.calls:
            self.assertEqual(payload["model"], "test-model")
            self.assertEqual(payload["temperature"], 0)
            self.assertEqual(payload["max_tokens"], 128)
            self.assertFalse(payload["stream"])
        self.assertEqual(
            baseline_payload["messages"][0]["content"],
            contextual_payload["messages"][0]["content"],
        )
        baseline_user = baseline_payload["messages"][1]["content"]
        contextual_user = contextual_payload["messages"][1]["content"]
        self.assertIn('"Rank"', baseline_user)
        self.assertNotIn(self.record.key, baseline_user)
        self.assertNotIn("Assets/Scripts", baseline_user)
        self.assertNotIn("EVIDENCE", baseline_user)
        self.assertIn(self.record.key, contextual_user)
        self.assertIn("Assets/Scripts/UI/LeaderboardPanel.cs", contextual_user)
        self.assertIn("<<<EVIDENCE", contextual_user)
        self.assertIn("EVIDENCE>>>", contextual_user)

    def test_result_parses_json_and_keeps_usage(self) -> None:
        translator = Translator(make_config(), transport=FakeTransport())
        result = translator.compare(self.record, self.evidence, "pt-BR")
        self.assertEqual(result["baseline"]["translation"], "译文1")
        self.assertEqual(result["contextual"]["translation"], "译文2")
        self.assertTrue(result["baseline"]["parsed_json"])
        self.assertEqual(result["baseline"]["usage"]["total_tokens"], 15)
        self.assertEqual(result["parameters"]["temperature"], 0)
        self.assertTrue(result["evidence_used"])
        self.assertLessEqual(len(result["evidence_used"]), result["evidence_total"])

    def test_plain_text_response_is_kept_but_flagged(self) -> None:
        def transport(payload, timeout):
            return {"choices": [{"message": {"content": "直接译文"}}]}

        translator = Translator(make_config(), transport=transport)
        result = translator.compare(self.record, self.evidence, "ja-JP")
        self.assertEqual(result["baseline"]["translation"], "直接译文")
        self.assertFalse(result["baseline"]["parsed_json"])
        self.assertIsNone(result["baseline"]["usage"])

    def test_malformed_response_raises_and_does_not_invent_text(self) -> None:
        def transport(payload, timeout):
            return {"choices": []}

        translator = Translator(make_config(), transport=transport)
        with self.assertRaises(TranslationError) as caught:
            translator.compare(self.record, self.evidence, "pt-BR")
        self.assertIn("choices", str(caught.exception))

    def test_transport_error_is_redacted_and_fails_fast(self) -> None:
        calls = []

        def transport(payload, timeout):
            calls.append(payload)
            raise RuntimeError("boom " + SECRET)

        translator = Translator(make_config(), transport=transport)
        with self.assertRaises(TranslationError) as caught:
            translator.compare(self.record, self.evidence, "pt-BR")
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertIn("[redacted]", str(caught.exception))
        self.assertEqual(len(calls), 1)

    def test_timeout_error_is_reported_safely(self) -> None:
        def transport(payload, timeout):
            raise TimeoutError("timed out")

        translator = Translator(make_config(), transport=transport)
        with self.assertRaises(TranslationError) as caught:
            translator.compare(self.record, self.evidence, "pt-BR")
        self.assertIn("timed out", str(caught.exception))

    def test_context_is_truncated_at_character_cap(self) -> None:
        translator = Translator(make_config(max_context_chars=300), transport=FakeTransport())
        result = translator.compare(self.record, self.evidence, "pt-BR")
        self.assertTrue(result["context_truncated"])
        self.assertLessEqual(result["context_chars"], 300)
        self.assertEqual(len(result["evidence_used"]), 1)

    def test_evidence_context_contains_real_paths_lines_and_inference(self) -> None:
        text, used, truncated = build_evidence_context(self.evidence, 4000)
        self.assertIn("Assets/Scripts/UI/LeaderboardPanel.cs:17", text)
        self.assertIn("heuristic inference", text)
        self.assertIn("rankColumnHeader", text)
        self.assertFalse(truncated)
        self.assertEqual(used[0], "ev-01")

    def test_invalid_locale_is_rejected_before_any_call(self) -> None:
        transport = FakeTransport()
        translator = Translator(make_config(), transport=transport)
        with self.assertRaises(TranslationError):
            translator.compare(self.record, self.evidence, "xx-XX")
        self.assertEqual(transport.calls, [])

    def test_public_config_does_not_leak_key(self) -> None:
        public = make_config().public()
        self.assertTrue(public["api_key_present"])
        self.assertNotIn(SECRET, json.dumps(public))
        self.assertNotIn("api_key", public)

    def test_disabled_config_requires_no_key_but_keeps_model_name(self) -> None:
        config = make_config(api_key="")
        self.assertFalse(config.enabled)
        self.assertEqual(config.public()["model"], "test-model")
        self.assertFalse(config.public()["configured"])


if __name__ == "__main__":
    unittest.main()

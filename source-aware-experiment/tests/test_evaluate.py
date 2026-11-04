"""Dry-run and live-path tests; no real network is ever used."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate  # noqa: E402
from srcaware.corpus import CorpusSpec, OpenTTDCorpus  # noqa: E402
from srcaware.dataset import build_records, load_dataset, parse_cases  # noqa: E402
from srcaware.live import (  # noqa: E402
    Budget,
    LiveConfig,
    LiveError,
    MissingApiKey,
    parse_translation,
)
from srcaware.openttd import OpenTTDLocator  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "tiny_openttd"
CASES = ROOT / "tests" / "fixtures" / "cases_tiny.json"


class FakeTransport:
    def __init__(self, content: str = '{"translation": "阿尔法"}', usage=None, fail=False):
        self.content = content
        self.usage = (
            usage
            if usage is not None
            else {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        )
        self.fail = fail
        self.calls = 0
        self.payloads = []

    def __call__(self, url, headers, payload, timeout):
        self.calls += 1
        self.payloads.append(payload)
        if self.fail:
            raise LiveError("HTTP 500: simulated")
        return {
            "id": "resp-test",
            "choices": [{"message": {"content": self.content}, "finish_reason": "stop"}],
            "usage": self.usage,
        }


def make_records():
    corpus = OpenTTDCorpus(
        FIXTURE,
        CorpusSpec("OpenTTD", "fixture", "0" * 40, "GPL-2.0", "https://example.invalid"),
    )
    locator = OpenTTDLocator(corpus)
    data = load_dataset(CASES)
    records = build_records(corpus, locator, parse_cases(data), "zh-CN")
    return corpus, records


class DryRunTests(unittest.TestCase):
    def test_dry_run_writes_prompts_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network used")):
                code = evaluate.main(
                    [
                        "--corpus",
                        str(FIXTURE),
                        "--cases",
                        str(CASES),
                        "--out",
                        str(out),
                        "--dry-run",
                    ]
                )
            self.assertEqual(code, 0)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["live_executed"])
            self.assertIsNone(manifest["model"])
            self.assertEqual(manifest["totals"]["live_calls"], 0)
            self.assertEqual(manifest["leakage_checks"]["evidence_paths_allowlisted"], True)
            prompts = [json.loads(line) for line in (out / "prompts.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(prompts), 9)
            results = [json.loads(line) for line in (out / "results.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertTrue(all(row["status"] == "not_called" for row in results))
            review = (out / "review_template.csv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(review), 10)

    def test_case_selection_reduces_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            code = evaluate.main(
                [
                    "--corpus", str(FIXTURE),
                    "--cases", str(CASES),
                    "--out", str(out),
                    "--case-ids", "tiny.alpha,tiny.missing",
                    "--dry-run",
                ]
            )
            self.assertEqual(code, 0)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["dataset"]["cases"], 2)
            self.assertEqual(manifest["dataset"]["selected_case_ids"], ["tiny.alpha", "tiny.missing"])
            self.assertEqual(manifest["totals"]["prompts_built"], 6)

    def test_live_without_key_does_not_create_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            with mock.patch.dict(os.environ, {"SOURCEAWARE_API_KEY": ""}):
                code = evaluate.main(
                    [
                        "--corpus",
                        str(FIXTURE),
                        "--cases",
                        str(CASES),
                        "--out",
                        str(out),
                        "--live",
                        "--max-total-tokens",
                        "1000",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertFalse(out.exists())


class LiveTests(unittest.TestCase):
    def test_live_budget_stops_and_never_records_key(self) -> None:
        corpus, records = make_records()
        transport = FakeTransport()
        config = LiveConfig(
            base_url="https://example.invalid/v1",
            api_key="SECRET-KEY-123",
            model="fake-model",
            max_output_tokens=32,
        )
        budget = Budget(max_total_tokens=2000, max_calls=9)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            manifest = evaluate.run_live(
                corpus,
                json.loads((ROOT / "audit" / "corpus.json").read_text(encoding="utf-8")),
                CASES,
                out,
                records,
                "deadbeef",
                "zh-CN",
                {"keys": 47},
                False,
                config,
                budget,
                transport=transport,
            )
            self.assertTrue(manifest["live_executed"])
            self.assertGreaterEqual(manifest["totals"]["responses_recorded"], 1)
            self.assertLess(manifest["totals"]["responses_recorded"], 9)
            self.assertTrue(manifest["aborted"])
            text = "\n".join(path.read_text(encoding="utf-8") for path in out.iterdir() if path.is_file())
            self.assertNotIn("SECRET-KEY-123", text)
            self.assertNotIn("SECRET-KEY-123", json.dumps(manifest))

    def test_parse_error_is_recorded_not_repaired(self) -> None:
        corpus, records = make_records()
        transport = FakeTransport(content="not json")
        config = LiveConfig(
            base_url="https://example.invalid/v1",
            api_key="k",
            model="fake-model",
            max_output_tokens=32,
            input_price_per_1k=0.001,
            output_price_per_1k=0.002,
        )
        budget = Budget(max_total_tokens=2000, max_calls=1, input_price_per_1k=0.001, output_price_per_1k=0.002)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            manifest = evaluate.run_live(
                corpus,
                json.loads((ROOT / "audit" / "corpus.json").read_text(encoding="utf-8")),
                CASES,
                out,
                records,
                "deadbeef",
                "zh-CN",
                {"keys": 47},
                False,
                config,
                budget,
                transport=transport,
            )
            self.assertEqual(manifest["totals"]["parse_errors"], 1)
            self.assertTrue(manifest["aborted"])

    def test_transport_error_is_recorded(self) -> None:
        corpus, records = make_records()
        transport = FakeTransport(fail=True)
        config = LiveConfig(
            base_url="https://example.invalid/v1",
            api_key="k",
            model="fake-model",
            max_output_tokens=32,
            input_price_per_1k=0.001,
            output_price_per_1k=0.002,
        )
        budget = Budget(max_total_tokens=2000, max_calls=1, input_price_per_1k=0.001, output_price_per_1k=0.002)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = evaluate.run_live(
                corpus,
                json.loads((ROOT / "audit" / "corpus.json").read_text(encoding="utf-8")),
                CASES,
                Path(tmp) / "run",
                records,
                "deadbeef",
                "zh-CN",
                {"keys": 47},
                False,
                config,
                budget,
                transport=transport,
            )
            self.assertEqual(manifest["totals"]["transport_errors"], 1)
            self.assertTrue(manifest["aborted"])
            self.assertEqual(manifest["budget"]["calls"], 1)
            self.assertIsNone(manifest["budget"]["cost_usd"])
            self.assertEqual(manifest["budget"]["unknown_usage_calls"], 1)
            self.assertEqual(transport.calls, 1)

    def test_cost_is_computed_when_prices_are_supplied(self) -> None:
        corpus, records = make_records()
        transport = FakeTransport()
        config = LiveConfig(
            base_url="https://example.invalid/v1",
            api_key="k",
            model="fake-model",
            max_output_tokens=32,
            input_price_per_1k=0.001,
            output_price_per_1k=0.002,
        )
        budget = Budget(
            max_total_tokens=2000,
            max_calls=1,
            input_price_per_1k=0.001,
            output_price_per_1k=0.002,
        )
        with tempfile.TemporaryDirectory() as tmp:
            manifest = evaluate.run_live(
                corpus,
                json.loads((ROOT / "audit" / "corpus.json").read_text(encoding="utf-8")),
                CASES,
                Path(tmp) / "run",
                records,
                "deadbeef",
                "zh-CN",
                {"keys": 47},
                False,
                config,
                budget,
                transport=transport,
            )
            first = json.loads((Path(tmp) / "run" / "results.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertAlmostEqual(first["cost_usd"], 0.00002)

    def test_unknown_usage_is_charged_at_estimate(self) -> None:
        corpus, records = make_records()
        transport = FakeTransport(usage={})
        config = LiveConfig(
            base_url="https://example.invalid/v1",
            api_key="k",
            model="fake-model",
            max_output_tokens=32,
        )
        budget = Budget(max_total_tokens=2000, max_calls=9)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = evaluate.run_live(
                corpus,
                json.loads((ROOT / "audit" / "corpus.json").read_text(encoding="utf-8")),
                CASES,
                Path(tmp) / "run",
                records,
                "deadbeef",
                "zh-CN",
                {"keys": 47},
                False,
                config,
                budget,
                transport=transport,
            )
            self.assertGreater(manifest["budget"]["unknown_usage_calls"], 0)
            self.assertGreater(manifest["budget"]["unknown_estimated_tokens"], 0)
            self.assertIsNone(manifest["budget"]["cost_usd"])
            self.assertTrue(manifest["aborted"])
            row = json.loads((Path(tmp) / "run" / "results.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["status"], "usage_missing")
            self.assertEqual(row["raw_response"], '{"translation": "阿尔法"}')
            self.assertEqual(row["usage"], {})

    def test_truncated_response_is_not_success(self) -> None:
        corpus, records = make_records()
        transport = FakeTransport()
        def truncated(url, headers, payload, timeout):
            data = transport(url, headers, payload, timeout)
            data["model"] = "resolved-model"
            data["choices"][0]["finish_reason"] = "length"
            return data
        config = LiveConfig("https://example.invalid/v1", "k", "fake-model")
        with tempfile.TemporaryDirectory() as tmp:
            manifest = evaluate.run_live(
                corpus, json.loads((ROOT / "audit" / "corpus.json").read_text(encoding="utf-8")),
                CASES, Path(tmp) / "run", records, "deadbeef", "zh-CN", {"keys": 47},
                False, config, Budget(max_total_tokens=2000, max_calls=1), transport=truncated,
            )
            row = json.loads((Path(tmp) / "run" / "results.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["status"], "truncated")
            self.assertEqual(row["model"], "resolved-model")
            self.assertTrue(manifest["aborted"])
            self.assertEqual(manifest["totals"]["ok"], 0)
            self.assertEqual(manifest["totals"]["truncated"], 1)

    def test_missing_key_config_is_rejected(self) -> None:
        with self.assertRaises(MissingApiKey):
            LiveConfig(base_url="https://example.invalid/v1", api_key="", model="m")

    def test_parse_translation(self) -> None:
        self.assertEqual(parse_translation('{"translation": "你好"}')[0], "你好")
        self.assertIsNotNone(parse_translation("not json")[1])
        self.assertIsNotNone(parse_translation('{"foo": 1}')[1])
        self.assertIsNotNone(parse_translation('{"translation": ""}')[1])
        self.assertEqual(parse_translation('```json\n{"translation": "ok"}\n```')[0], "ok")


if __name__ == "__main__":
    unittest.main()

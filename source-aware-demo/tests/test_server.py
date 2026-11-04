"""HTTP API and static-serving tests, including disabled-mode honesty."""

from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sourceaware.config import LLMConfig  # noqa: E402
from sourceaware.server import App, Server  # noqa: E402
from sourceaware.translate import TranslationError, Translator  # noqa: E402

SECRET = "sk-server-secret"


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
    def __init__(self, fail: bool = False) -> None:
        self.calls = []
        self.fail = fail

    def __call__(self, payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        self.calls.append(payload)
        if self.fail:
            raise TranslationError("upstream exploded", stage="transport")
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"translation": "Tradução %d" % len(self.calls), "rationale": "测试"},
                            ensure_ascii=False,
                        )
                    }
                }
            ],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
        }


class ServerTests(unittest.TestCase):
    def start_server(
        self,
        config: Optional[LLMConfig] = None,
        transport: Optional[Any] = None,
    ) -> Tuple[str, App]:
        effective = config or make_config(api_key="")
        translator = Translator(effective, transport=transport or FakeTransport())
        app = App(config=effective, translator=translator)
        server = Server(("127.0.0.1", 0), app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop() -> None:
            server.shutdown()
            thread.join(2)
            server.server_close()

        self.addCleanup(stop)
        base = "http://127.0.0.1:%d" % server.server_address[1]
        return base, app

    def request(
        self,
        base: str,
        method: str,
        path: str,
        body: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, Dict[str, str], bytes]:
        request = urllib.request.Request(
            base + path,
            data=body,
            headers=headers or {},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def json_request(self, base: str, method: str, path: str, payload: Any = None):
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        status, response_headers, raw = self.request(base, method, path, body, headers)
        data = json.loads(raw.decode("utf-8")) if raw else None
        return status, response_headers, data

    def test_health_is_retrieval_only_without_key(self) -> None:
        base, _ = self.start_server()
        status, headers, data = self.json_request(base, "GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(data["mode"], "retrieval-only")
        self.assertTrue(data["synthetic"])
        self.assertTrue(data["read_only"])
        self.assertFalse(data["model"]["configured"])
        self.assertIn("未调用模型", data["message"])
        self.assertEqual(len(data["target_locales"]), 5)
        self.assertNotIn(SECRET, json.dumps(data))
        self.assertIn("Content-Security-Policy", headers)

    def test_strings_lists_real_table_entries_and_shared_text(self) -> None:
        base, _ = self.start_server()
        status, _, data = self.json_request(base, "GET", "/api/strings")
        self.assertEqual(status, 200)
        self.assertTrue(data["synthetic"])
        self.assertEqual(len(data["strings"]), 10)
        rank = next(item for item in data["strings"] if item["key"] == "ui.leaderboard.rank_column")
        self.assertEqual(rank["shared_with"], ["ui.military.rank_badge"])

    def test_evidence_returns_files_lines_and_snippets(self) -> None:
        base, _ = self.start_server()
        status, _, data = self.json_request(
            base, "GET", "/api/evidence?key=ui.leaderboard.rank_column"
        )
        self.assertEqual(status, 200)
        self.assertTrue(data["found"])
        self.assertEqual(data["counts"]["code_key"], 1)
        first = data["evidence"][0]
        self.assertIn("path", first)
        self.assertIn("line", first)
        self.assertTrue(first["snippet"])

    def test_evidence_unknown_key_and_missing_parameter(self) -> None:
        base, _ = self.start_server()
        status, _, data = self.json_request(base, "GET", "/api/evidence?key=nope")
        self.assertEqual(status, 404)
        self.assertIn("error", data)
        status, _, data = self.json_request(base, "GET", "/api/evidence")
        self.assertEqual(status, 400)

    def test_compare_without_key_returns_disabled_and_no_translation(self) -> None:
        transport = FakeTransport()
        base, _ = self.start_server(transport=transport)
        status, _, data = self.json_request(
            base,
            "POST",
            "/api/compare",
            {"key": "ui.leaderboard.rank_column", "target_locale": "pt-BR"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "disabled")
        self.assertFalse(data["live"])
        self.assertIsNone(data["baseline"])
        self.assertIsNone(data["contextual"])
        self.assertIn("未调用模型", data["message"])
        self.assertEqual(transport.calls, [])
        self.assertNotIn(SECRET, json.dumps(data))

    def test_compare_with_key_reports_live_results(self) -> None:
        transport = FakeTransport()
        base, _ = self.start_server(config=make_config(), transport=transport)
        status, _, health = self.json_request(base, "GET", "/api/health")
        self.assertEqual(health["mode"], "live-capable")
        self.assertTrue(health["model"]["api_key_present"])
        self.assertNotIn(SECRET, json.dumps(health))

        status, _, data = self.json_request(
            base,
            "POST",
            "/api/compare",
            {"key": "ui.leaderboard.rank_column", "target_locale": "pt-BR"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["live"])
        self.assertEqual(data["model"], "test-model")
        self.assertEqual(data["baseline"]["translation"], "Tradução 1")
        self.assertEqual(data["contextual"]["translation"], "Tradução 2")
        self.assertEqual(len(transport.calls), 2)
        self.assertNotIn(SECRET, json.dumps(data))

    def test_compare_upstream_failure_returns_502_without_fake_result(self) -> None:
        base, _ = self.start_server(config=make_config(), transport=FakeTransport(fail=True))
        status, _, data = self.json_request(
            base,
            "POST",
            "/api/compare",
            {"key": "ui.reward.claim", "target_locale": "pt-BR"},
        )
        self.assertEqual(status, 502)
        self.assertEqual(data["status"], "error")
        self.assertIn("未生成译文", data["message"])
        self.assertNotIn("baseline", data)

    def test_compare_validation(self) -> None:
        base, _ = self.start_server()
        status, _, _ = self.json_request(
            base, "POST", "/api/compare", {"key": "ui.reward.claim", "target_locale": "xx-XX"}
        )
        self.assertEqual(status, 400)
        status, _, _ = self.json_request(
            base, "POST", "/api/compare", {"key": "", "target_locale": "pt-BR"}
        )
        self.assertEqual(status, 400)
        status, _, _ = self.json_request(
            base, "POST", "/api/compare", {"key": "unknown.key", "target_locale": "pt-BR"}
        )
        self.assertEqual(status, 404)

    def test_invalid_and_oversized_bodies_are_rejected(self) -> None:
        base, _ = self.start_server()
        status, _, _ = self.request(
            base,
            "POST",
            "/api/compare",
            b"not json",
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 400)
        status, _, _ = self.request(
            base,
            "POST",
            "/api/compare",
            b"x" * 9000,
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 400)

    def test_static_files_and_path_traversal(self) -> None:
        base, _ = self.start_server()
        status, headers, body = self.request(base, "GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("源码感知翻译", body.decode("utf-8"))
        self.assertIn("Content-Security-Policy", headers)
        status, _, body = self.request(base, "GET", "/app.js")
        self.assertEqual(status, 200)
        self.assertIn(b"runCompare", body)
        for path in (
            "/../sourceaware/config.py",
            "/..%2f..%2fsourceaware%2fconfig.py",
            "/sourceaware/config.py",
        ):
            status, _, _ = self.request(base, "GET", path)
            self.assertEqual(status, 404, path)

    def test_unknown_post_route(self) -> None:
        base, _ = self.start_server()
        status, _, _ = self.json_request(base, "POST", "/api/nope", {})
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()

"""Security-focused tests: path boundaries, suffix limits, key handling."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sourceaware.catalog import Catalog, UnknownStringKey  # noqa: E402
from sourceaware.config import LLMConfig  # noqa: E402
from sourceaware.retrieval import search  # noqa: E402
from sourceaware.server import WEB_DIR, _safe_join  # noqa: E402

PROJECT = ROOT / "demo_project"
SECRET = "sk-security-secret"


class SecurityTests(unittest.TestCase):
    def test_static_join_stays_inside_web_root(self) -> None:
        self.assertIsNotNone(_safe_join(WEB_DIR, "app.js"))
        self.assertIsNotNone(_safe_join(WEB_DIR, "/styles.css"))
        self.assertIsNone(_safe_join(WEB_DIR, "../sourceaware/config.py"))
        self.assertIsNone(_safe_join(WEB_DIR, "..%2fsourceaware%2fconfig.py"))
        self.assertIsNone(_safe_join(WEB_DIR, "sourceaware/config.py"))
        self.assertIsNone(_safe_join(WEB_DIR, "missing.js"))
        self.assertIsNone(_safe_join(WEB_DIR, "not-a-static.py"))

    def test_symlink_out_of_web_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            web = Path(temporary) / "web"
            web.mkdir()
            outside = Path(temporary) / "outside.js"
            outside.write_text("window.secret = 1;", encoding="utf-8")
            (web / "leak.js").symlink_to(outside)
            self.assertIsNone(_safe_join(web, "leak.js"))

    def test_key_parameter_is_not_a_file_path(self) -> None:
        with self.assertRaises(UnknownStringKey):
            search(Catalog(PROJECT), "../../etc/passwd")
        with self.assertRaises(UnknownStringKey):
            search(Catalog(PROJECT), "/etc/passwd")

    def test_only_code_and_table_suffixes_are_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            shutil.copytree(PROJECT, root)
            (root / "Assets" / "Localization" / "secret.txt").write_text(
                'ui.leaderboard.rank_column = "Rank"\n', encoding="utf-8"
            )
            result = search(Catalog(root), "ui.leaderboard.rank_column")
            self.assertEqual(result["scope"]["files_scanned"], 7)
            self.assertNotIn(
                "Assets/Localization/secret.txt",
                {item["path"] for item in result["evidence"]},
            )

    def test_config_from_env_bounds_and_hides_key(self) -> None:
        env = {
            "SOURCEAWARE_API_KEY": SECRET,
            "SOURCEAWARE_LLM_BASE_URL": "https://api.example.test/v1/",
            "SOURCEAWARE_LLM_MODEL": "demo-model",
            "SOURCEAWARE_TIMEOUT_SECONDS": "9999",
            "SOURCEAWARE_MAX_OUTPUT_TOKENS": "1",
            "SOURCEAWARE_MAX_CONTEXT_CHARS": "999999",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            config = LLMConfig.from_env()
        self.assertEqual(config.base_url, "https://api.example.test/v1")
        self.assertEqual(config.timeout, 120.0)
        self.assertEqual(config.max_output_tokens, 32)
        self.assertEqual(config.max_context_chars, 20000)
        self.assertNotIn(SECRET, repr(config))
        self.assertNotIn(SECRET, json.dumps(config.public()))
        self.assertEqual(config.public()["base_host"], "api.example.test")

    def test_zero_port_and_invalid_env_values_fall_back(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "SOURCEAWARE_TIMEOUT_SECONDS": "nope",
                "SOURCEAWARE_MAX_OUTPUT_TOKENS": "-4",
            },
            clear=False,
        ):
            config = LLMConfig.from_env()
        self.assertEqual(config.timeout, 20.0)
        self.assertEqual(config.max_output_tokens, 32)

    def test_disabled_config_with_invalid_url_is_not_enabled(self) -> None:
        config = LLMConfig(
            base_url="not-a-url",
            api_key=SECRET,
            model="m",
            timeout=5.0,
            max_output_tokens=64,
            max_context_chars=1000,
        )
        self.assertFalse(config.enabled)
        self.assertEqual(config.public()["base_host"], "(invalid)")


if __name__ == "__main__":
    unittest.main()

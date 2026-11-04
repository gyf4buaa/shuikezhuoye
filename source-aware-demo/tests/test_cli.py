"""The reproducible offline CLI must reflect the same files as the web API."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "lookup.py"


class CliTests(unittest.TestCase):
    def run_cli(self, *args: str):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_list_shows_all_keys(self) -> None:
        result = self.run_cli("--list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ui.leaderboard.rank_column", result.stdout)
        self.assertIn("ui.reward.claim", result.stdout)
        self.assertEqual(len([line for line in result.stdout.splitlines() if line.strip()]), 10)

    def test_inspect_shows_real_paths_and_inference(self) -> None:
        result = self.run_cli("ui.leaderboard.rank_column")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Assets/Scripts/UI/LeaderboardPanel.cs:17", result.stdout)
        self.assertIn("Assets/Scripts/UI/MilitaryPanel.cs:22", result.stdout)
        self.assertIn("inference:", result.stdout)
        self.assertIn("direct key refs=1", result.stdout)

    def test_json_output_is_parseable(self) -> None:
        result = self.run_cli("ui.leaderboard.rank_column", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["found"])
        self.assertEqual(payload["counts"]["code_literal"], 2)

    def test_unknown_key_exits_nonzero(self) -> None:
        result = self.run_cli("nope")
        self.assertEqual(result.returncode, 1)
        self.assertIn("未知字符串 Key", result.stderr)


if __name__ == "__main__":
    unittest.main()

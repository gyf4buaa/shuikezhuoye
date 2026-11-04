"""Catalog tests: the PoC reads real files, not a hard-coded key list."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sourceaware.catalog import Catalog, CatalogError, UnknownStringKey  # noqa: E402

PROJECT = ROOT / "demo_project"


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = Catalog(PROJECT)

    def test_synthetic_project_is_marked(self) -> None:
        readme = (PROJECT / "README.md").read_text(encoding="utf-8")
        self.assertIn("SYNTHETIC DEMO PROJECT", readme)
        self.assertIn("合成演示工程", readme)
        for path in PROJECT.rglob("*.cs"):
            first_line = path.read_text(encoding="utf-8").splitlines()[0]
            self.assertIn("SYNTHETIC DEMO PROJECT", first_line, path)
        for path in PROJECT.rglob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "_meta" in data:
                self.assertTrue(data["_meta"]["synthetic"])

    def test_keys_and_sources_come_from_json_table(self) -> None:
        strings = {record.key: record for record in self.catalog.strings()}
        self.assertEqual(len(strings), 10)
        self.assertEqual(strings["ui.reward.claim"].source, "Claim")
        self.assertEqual(strings["ui.leaderboard.rank_column"].source, "Rank")
        self.assertEqual(strings["ui.leaderboard.rank_column"].table, "Assets/Localization/en.json")

    def test_table_line_numbers_point_at_the_key(self) -> None:
        lines = (PROJECT / "Assets/Localization/en.json").read_text(encoding="utf-8").splitlines()
        for record in self.catalog.strings():
            self.assertGreater(record.line, 0)
            line = lines[record.line - 1]
            self.assertIn(json.dumps(record.key), line)
            self.assertIn(json.dumps(record.source), line)

    def test_shared_source_text_is_exposed(self) -> None:
        rank = self.catalog.get("ui.leaderboard.rank_column")
        self.assertEqual(rank.source, "Rank")
        self.assertEqual(rank.shared_with, ("ui.military.rank_badge",))
        claim = self.catalog.get("ui.reward.claim")
        self.assertEqual(claim.shared_with, ("ui.leaderboard.claim",))

    def test_unknown_key_raises(self) -> None:
        with self.assertRaises(UnknownStringKey):
            self.catalog.get("ui.does.not.exist")

    def test_csv_fallback_when_json_table_is_absent(self) -> None:
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            shutil.copytree(PROJECT, root)
            (root / "Assets/Localization/en.json").unlink()
            catalog = Catalog(root)
            strings = {record.key: record for record in catalog.strings()}
            self.assertEqual(len(strings), 10)
            self.assertEqual(strings["ui.leaderboard.rank_column"].source, "Rank")
            self.assertEqual(strings["ui.leaderboard.rank_column"].table, "Assets/Localization/ui_strings.csv")
            self.assertEqual(strings["ui.leaderboard.rank_column"].line, 4)

    def test_missing_project_raises(self) -> None:
        with self.assertRaises(CatalogError):
            Catalog(PROJECT / "not-here")


if __name__ == "__main__":
    unittest.main()

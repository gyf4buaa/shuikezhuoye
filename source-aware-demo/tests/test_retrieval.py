"""Retrieval tests: paths, line numbers, snippets and boundary protection."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sourceaware.catalog import Catalog, UnknownStringKey  # noqa: E402
from sourceaware.retrieval import search  # noqa: E402

PROJECT = ROOT / "demo_project"


def _evidence_at(payload, path: str, line: int):
    for item in payload["evidence"]:
        if item["path"] == path and item["line"] == line:
            return item
    return None


class RetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = Catalog(PROJECT)

    def test_rank_has_key_reference_and_two_real_literal_positions(self) -> None:
        result = search(self.catalog, "ui.leaderboard.rank_column")
        self.assertTrue(result["found"])
        self.assertEqual(result["counts"]["code_key"], 1)
        self.assertEqual(result["counts"]["code_literal"], 2)
        self.assertEqual(result["counts"]["string_table"], 3)
        literal_positions = {
            (item["path"], item["line"])
            for item in result["evidence"]
            if item["kind"] == "code-literal"
        }
        self.assertEqual(
            literal_positions,
            {
                ("Assets/Scripts/UI/LeaderboardPanel.cs", 25),
                ("Assets/Scripts/UI/MilitaryPanel.cs", 22),
            },
        )

    def test_direct_key_reference_points_at_exact_source_line(self) -> None:
        result = search(self.catalog, "ui.leaderboard.rank_column")
        direct = _evidence_at(result, "Assets/Scripts/UI/LeaderboardPanel.cs", 17)
        self.assertIsNotNone(direct)
        self.assertEqual(direct["kind"], "code-key")
        self.assertTrue(direct["direct"])
        self.assertEqual(direct["symbol"], {"class": "LeaderboardPanel", "member": "BuildHeader"})
        self.assertIn('L.Get("ui.leaderboard.rank_column")', direct["matched_text"])
        matched = [line for line in direct["snippet"] if line["match"]]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["line"], 17)

    def test_other_key_with_same_text_is_a_candidate_not_a_direct_reference(self) -> None:
        result = search(self.catalog, "ui.leaderboard.rank_column")
        military = _evidence_at(result, "Assets/Scripts/UI/MilitaryPanel.cs", 22)
        self.assertIsNotNone(military)
        self.assertFalse(military["direct"])
        self.assertEqual(military["inference"]["confidence"], "low")
        self.assertTrue(military["inference"]["needs_human"])
        self.assertIn("同文本候选", military["inference"]["summary"])

    def test_leaderboard_inference_uses_actual_identifiers(self) -> None:
        result = search(self.catalog, "ui.leaderboard.rank_column")
        direct = _evidence_at(result, "Assets/Scripts/UI/LeaderboardPanel.cs", 17)
        inference = direct["inference"]
        self.assertIn("列表/表头语境", inference["categories"])
        self.assertEqual(inference["confidence"], "high")
        self.assertIn("rankColumnHeader", inference["signals"])
        snippet_text = " ".join(line["text"] for line in direct["snippet"])
        for signal in inference["signals"]:
            self.assertIn(signal.lower(), snippet_text.lower())

    def test_table_evidence_is_not_presented_as_ui_semantics(self) -> None:
        result = search(self.catalog, "ui.leaderboard.rank_column")
        table = _evidence_at(result, "Assets/Localization/en.json", 9)
        self.assertIsNotNone(table)
        self.assertEqual(table["inference"]["confidence"], "none")
        self.assertTrue(table["inference"]["needs_human"])
        self.assertIn("不提供界面语境", table["inference"]["summary"])

    def test_claim_key_does_not_match_longer_claim_all_key(self) -> None:
        result = search(self.catalog, "ui.reward.claim")
        self.assertEqual(result["counts"]["code_key"], 1)
        for item in result["evidence"]:
            if item["kind"] == "code-key":
                self.assertNotIn("ui.reward.claim_all", item["matched_text"])
        direct = _evidence_at(result, "Assets/Scripts/UI/RewardPanel.cs", 25)
        self.assertIsNotNone(direct)
        self.assertIn("ui.reward.claim", direct["matched_text"])

    def test_claim_literal_fallback_is_a_candidate(self) -> None:
        result = search(self.catalog, "ui.reward.claim")
        fallback = _evidence_at(result, "Assets/Scripts/UI/RewardPanel.cs", 32)
        self.assertIsNotNone(fallback)
        self.assertFalse(fallback["direct"])
        self.assertEqual(fallback["matched_text"].count('"Claim"'), 1)

    def test_key_without_code_usage_reports_only_string_table(self) -> None:
        result = search(self.catalog, "ui.settings.sound")
        self.assertTrue(result["found"])
        self.assertFalse(result["has_direct_code_reference"])
        self.assertFalse(result["has_code_references"])
        self.assertEqual(result["counts"]["code_key"], 0)
        self.assertEqual(result["counts"]["code_literal"], 0)
        self.assertIn("只找到字符串表定义", result["note"])

    def test_unknown_key_raises(self) -> None:
        with self.assertRaises(UnknownStringKey):
            search(self.catalog, "nope")

    def test_search_is_deterministic_and_reports_scope(self) -> None:
        first = search(self.catalog, "ui.leaderboard.rank_column")
        second = search(self.catalog, "ui.leaderboard.rank_column")
        strip = lambda payload: {key: value for key, value in payload.items() if key != "elapsed_ms"}
        self.assertEqual(strip(first), strip(second))
        self.assertEqual(first["scope"]["files_scanned"], 7)
        self.assertGreater(first["scope"]["lines_scanned"], 0)
        self.assertGreater(first["scope"]["bytes_scanned"], 0)
        self.assertTrue(first["scope"]["read_only"])
        allowed = {"Assets/Scripts", "Assets/Localization"}
        for item in first["evidence"]:
            self.assertTrue(item["path"].startswith(tuple(allowed)), item["path"])

    def test_symlink_escape_is_not_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            shutil.copytree(PROJECT, root)
            outside = Path(temporary) / "outside.cs"
            outside.write_text('class Leak { string s = "Rank"; }\n', encoding="utf-8")
            (root / "Assets/Scripts/UI/OutsideLink.cs").symlink_to(outside)
            result = search(Catalog(root), "ui.leaderboard.rank_column")
            paths = {item["path"] for item in result["evidence"]}
            self.assertNotIn("Assets/Scripts/UI/OutsideLink.cs", paths)
            self.assertFalse(any("outside.cs" in path for path in paths))

    def test_snippets_never_contain_fabricated_context(self) -> None:
        result = search(self.catalog, "ui.leaderboard.rank_column")
        for item in result["evidence"]:
            lines = (PROJECT / item["path"]).read_text(encoding="utf-8").splitlines()
            for snippet in item["snippet"]:
                self.assertLessEqual(snippet["line"], len(lines))
                self.assertEqual(snippet["text"], lines[snippet["line"] - 1][:600])


if __name__ == "__main__":
    unittest.main()

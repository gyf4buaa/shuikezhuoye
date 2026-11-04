"""Locator tests against the miniature fixture corpus."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from srcaware.corpus import CorpusSpec, OpenTTDCorpus
from srcaware.openttd import OpenTTDLocator, data_placeholders, placeholder_tokens

FIXTURE = ROOT / "tests" / "fixtures" / "tiny_openttd"


def locator() -> OpenTTDLocator:
    corpus = OpenTTDCorpus(
        FIXTURE,
        CorpusSpec("OpenTTD", "fixture", "0" * 40, "GPL-2.0", "https://example.invalid"),
    )
    return OpenTTDLocator(corpus)


class LocatorTests(unittest.TestCase):
    def test_direct_reference_has_call_and_arguments(self) -> None:
        bundle = locator().lookup("STR_ALPHA")
        self.assertEqual(bundle.status, "direct")
        self.assertEqual(bundle.confidence, "high")
        ref = bundle.refs[0]
        self.assertEqual((ref.path, ref.line), ("src/demo.cpp", 6))
        self.assertEqual(ref.call, "DrawString")
        self.assertIn("STR_ALPHA", ref.args)

    def test_cargo_macro_resolves_plural_and_singular(self) -> None:
        loc = locator()
        plural = loc.lookup("STR_CARGO_PLURAL_COAL")
        singular = loc.lookup("STR_CARGO_SINGULAR_COAL")
        self.assertEqual(plural.status, "macro")
        self.assertEqual(singular.status, "macro")
        kinds = {ref.kind for ref in plural.refs}
        self.assertEqual(kinds, {"macro_definition", "cargo_table_row"})
        self.assertIn("plural name slot", plural.refs[1].relation or "")

    def test_settings_range_maps_value_to_key(self) -> None:
        bundle = locator().lookup("STR_SETTING_B")
        self.assertEqual(bundle.status, "settings")
        self.assertTrue(any("option 1 of 0..2" in note for note in bundle.notes))
        kinds = {ref.kind for ref in bundle.refs}
        self.assertIn("settings_dropdown_base", kinds)
        self.assertIn("settings_rule", kinds)

    def test_verified_arithmetic_ranges(self) -> None:
        loc = locator()
        colour = loc.lookup("STR_COLOUR_PALE_GREEN")
        self.assertEqual(colour.status, "arithmetic")
        self.assertTrue(any("STR_COLOUR_DARK_BLUE + 1" in note for note in colour.notes))
        goal = loc.lookup("STR_GOAL_QUESTION_BUTTON_OK")
        self.assertEqual(goal.status, "arithmetic")
        self.assertTrue(any("STR_GOAL_QUESTION_BUTTON_CANCEL + 1" in note for note in goal.notes))
        ref = goal.refs[0]
        self.assertEqual((ref.path, ref.line), ("src/demo.cpp", 8))

    def test_baseset_metadata_reference(self) -> None:
        bundle = locator().lookup("STR_BASE_TITLE")
        self.assertEqual(bundle.status, "direct")
        self.assertEqual(bundle.refs[0].path, "media/baseset/demo.obg")

    def test_missing_key_is_explicit(self) -> None:
        bundle = locator().lookup("STR_DEAD")
        self.assertEqual(bundle.status, "missing")
        self.assertEqual(bundle.evidence_ids, [])

    def test_unknown_key_is_not_a_hit(self) -> None:
        bundle = locator().lookup("STR_DOES_NOT_EXIST")
        self.assertEqual(bundle.status, "unknown_key")

    def test_definition_row_is_not_evidence(self) -> None:
        bundle = locator().lookup("STR_BETA")
        self.assertEqual(bundle.evidence_ids, [])
        self.assertNotIn("src/lang/english.txt", [ref.path for ref in bundle.refs])

    def test_placeholder_classification(self) -> None:
        self.assertEqual(data_placeholders("Length: {NUM}"), ["NUM"])
        tokens = placeholder_tokens("{BLACK}{STRING} ({NUM})")
        self.assertEqual(
            [(item["token"], item["kind"]) for item in tokens],
            [("BLACK", "style"), ("STRING", "data"), ("NUM", "data")],
        )

    def test_scope_extraction_is_attached(self) -> None:
        ref = locator().lookup("STR_ALPHA").refs[0]
        self.assertIsNotNone(ref.scope)
        self.assertIn("DrawDemo", ref.scope or "")

    def test_summary_counts_fixture(self) -> None:
        summary = locator().summary()
        self.assertEqual(summary["keys"], 47)
        self.assertGreaterEqual(summary["cargo_keys"], 4)
        self.assertGreaterEqual(summary["settings_keys"], 2)
        self.assertGreaterEqual(summary["family_keys"], 30)


if __name__ == "__main__":
    unittest.main()

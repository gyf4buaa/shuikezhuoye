"""Corpus access and leakage-guard tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from srcaware.corpus import CorpusError, CorpusSpec, LeakageError, OpenTTDCorpus

FIXTURE = ROOT / "tests" / "fixtures" / "tiny_openttd"


def corpus() -> OpenTTDCorpus:
    return OpenTTDCorpus(
        FIXTURE,
        CorpusSpec(
            project="OpenTTD",
            version="fixture",
            commit="0" * 40,
            license="GPL-2.0",
            repo_url="https://example.invalid/openttd",
        ),
    )


class CorpusTests(unittest.TestCase):
    def test_parses_english_table_and_ids(self) -> None:
        table = corpus()
        entries = table.entries
        self.assertEqual(len(entries), 47)
        by_key = table.entry_by_key
        self.assertEqual(by_key["STR_COLOUR_DARK_BLUE"].string_id, 3)
        self.assertEqual(by_key["STR_COLOUR_PALE_GREEN"].string_id, 4)
        self.assertEqual(by_key["STR_COLOUR_WHITE"].string_id, 18)
        self.assertEqual(by_key["STR_GOAL_QUESTION_BUTTON_CANCEL"].string_id, 19)
        self.assertEqual(by_key["STR_GOAL_QUESTION_BUTTON_CLOSE"].string_id, 36)
        self.assertEqual(by_key["STR_ALPHA"].text, "Alpha {NUM}")

    def test_evidence_allowlist_excludes_languages_and_third_party(self) -> None:
        table = corpus()
        files = set(table.evidence_files())
        self.assertIn("src/demo.cpp", files)
        self.assertIn("src/table/cargo_const.h", files)
        self.assertIn("src/table/settings/demo.ini", files)
        self.assertIn("media/baseset/demo.obg", files)
        self.assertNotIn("src/lang/english.txt", files)
        self.assertNotIn("src/lang/german.txt", files)
        self.assertNotIn("src/3rdparty/bundled.cpp", files)
        self.assertNotIn("src/notes.txt", files)

    def test_translated_table_is_refused(self) -> None:
        table = corpus()
        with self.assertRaises(LeakageError):
            table.read_evidence("src/lang/german.txt")
        with self.assertRaises(LeakageError):
            table.read_evidence("src/lang/english.txt")

    def test_denied_and_traversal_paths(self) -> None:
        table = corpus()
        for path in ("../outside.txt", "src/3rdparty/bundled.cpp", "src/notes.txt", "src/lang/german.txt"):
            with self.subTest(path=path):
                with self.assertRaises(LeakageError):
                    table.read_evidence(path)
        with self.assertRaises(LeakageError):
            table.resolve("../outside.txt")
        with self.assertRaises(LeakageError):
            table.resolve("/etc/passwd")
        with self.assertRaises(LeakageError):
            table.read_evidence("src/table/settings/../demo.cpp")

    def test_allowed_metadata_is_readable(self) -> None:
        table = corpus()
        text = table.read_evidence("media/baseset/demo.obg")
        self.assertIn("STR_BASE_TITLE", text)

    def test_verify_spec_checks_license(self) -> None:
        table = corpus()
        table.verify_spec()
        bad = OpenTTDCorpus(
            FIXTURE,
            CorpusSpec(
                project="OpenTTD",
                version="fixture",
                commit="0" * 40,
                license="MIT",
                repo_url="https://example.invalid/openttd",
            ),
        )
        with self.assertRaises(CorpusError):
            bad.verify_spec()

    def test_missing_corpus_is_reported(self) -> None:
        with self.assertRaises(CorpusError):
            OpenTTDCorpus(FIXTURE / "does-not-exist")

    def test_duplicate_keys_are_rejected(self) -> None:
        # A real table parser must not silently accept a duplicate key.
        table = corpus()
        with self.assertRaises(CorpusError):
            # Re-parse a temporary copy with a duplicated row.
            import tempfile, shutil

            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "corpus"
                shutil.copytree(FIXTURE, target)
                english = target / "src" / "lang" / "english.txt"
                text = english.read_text(encoding="utf-8")
                english.write_text(text + "STR_ALPHA :Duplicate\n", encoding="utf-8")
                OpenTTDCorpus(
                    target,
                    CorpusSpec("OpenTTD", "fixture", "0" * 40, "GPL-2.0", "u"),
                ).read_english_table()


if __name__ == "__main__":
    unittest.main()

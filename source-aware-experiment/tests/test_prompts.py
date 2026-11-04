"""Prompt invariants and dataset leakage tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from srcaware.corpus import CorpusSpec, LeakageError, OpenTTDCorpus
from srcaware.dataset import Case, build_records, load_dataset, parse_cases, validate_case_evidence
from srcaware.openttd import OpenTTDLocator
from srcaware.prompts import (
    CJK_RE,
    Prompt,
    assert_no_target_language,
    build_prompts,
    check_arm_invariants,
    truncate_evidence_for_budget,
)

FIXTURE = ROOT / "tests" / "fixtures" / "tiny_openttd"
CASES = ROOT / "tests" / "fixtures" / "cases_tiny.json"


def corpus() -> OpenTTDCorpus:
    return OpenTTDCorpus(
        FIXTURE,
        CorpusSpec("OpenTTD", "fixture", "0" * 40, "GPL-2.0", "https://example.invalid"),
    )


class PromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.locator = OpenTTDLocator(corpus())

    def test_arms_differ_only_by_key_and_evidence(self) -> None:
        bundle = self.locator.lookup("STR_ALPHA")
        prompts = build_prompts(bundle, "zh-CN")
        check_arm_invariants(prompts)
        self.assertEqual(prompts["A"].system, prompts["B"].system)
        self.assertEqual(prompts["B"].system, prompts["C"].system)
        self.assertIn('"Alpha {NUM}"', prompts["A"].user)
        self.assertNotIn("String key:", prompts["A"].user)
        self.assertIn("STR_ALPHA", prompts["B"].user)
        self.assertNotIn("Retrieved source evidence", prompts["B"].user)
        self.assertIn("Retrieved source evidence", prompts["C"].user)
        self.assertIn("src/demo.cpp:6", prompts["C"].user)
        self.assertTrue(prompts["C"].evidence_ids)
        self.assertLessEqual(len(prompts["C"].evidence_ids), 4)

    def test_expected_context_is_never_sent_to_the_model(self) -> None:
        bundle = self.locator.lookup("STR_ALPHA")
        prompts = build_prompts(bundle, "zh-CN")
        data = load_dataset(CASES)
        secret = parse_cases(data)[0].expected_context
        for prompt in prompts.values():
            self.assertNotIn(secret, prompt.system + prompt.user)
        self.assertNotIn("Expected context", prompts["C"].user)

    def test_placeholders_survive_prompt_building(self) -> None:
        bundle = self.locator.lookup("STR_ALPHA")
        prompt = build_prompts(bundle, "zh-CN")["C"]
        self.assertIn("{NUM}", prompt.user)
        self.assertIn("must survive translation", prompt.user)

    def test_target_language_leak_guard(self) -> None:
        leaked = Prompt(
            arm="C",
            system="system",
            user="这是泄漏的中文译文",
            evidence_ids=(),
        )
        with self.assertRaises(ValueError):
            assert_no_target_language(leaked)
        self.assertIsNotNone(CJK_RE.search("这是泄漏"))
        good = build_prompts(self.locator.lookup("STR_ALPHA"), "zh-CN")["C"]
        self.assertIsNone(CJK_RE.search(good.system + good.user))

    def test_system_prompt_keeps_braces(self) -> None:
        prompt = build_prompts(self.locator.lookup("STR_ALPHA"), "zh-CN")["A"]
        self.assertIn("{STRING}", prompt.system)
        self.assertIn("Simplified Chinese (China)", prompt.system)

    def test_evidence_truncation_is_deterministic(self) -> None:
        prompt = build_prompts(self.locator.lookup("STR_ALPHA"), "zh-CN")["C"]
        truncated = truncate_evidence_for_budget(prompt, 260)
        self.assertLessEqual(len(truncated.user), 260)
        self.assertIn("[... evidence truncated ...]", truncated.user)
        self.assertEqual(truncated.system, prompt.system)
        self.assertEqual(truncated.evidence_ids, prompt.evidence_ids)
        with self.assertRaises(ValueError):
            truncate_evidence_for_budget(prompt, 100)

    def test_unsupported_locale_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_prompts(self.locator.lookup("STR_ALPHA"), "xx-XX")


class DatasetTests(unittest.TestCase):
    def test_dataset_parses_and_builds(self) -> None:
        table = corpus()
        locator = OpenTTDLocator(table)
        data = load_dataset(CASES)
        cases = parse_cases(data)
        records = build_records(table, locator, cases, "zh-CN")
        self.assertEqual(len(records), 3)
        for record in records:
            check_arm_invariants(record.prompts)
            for prompt in record.prompts.values():
                self.assertIsNone(CJK_RE.search(prompt.user))

    def test_target_language_expected_location_is_rejected(self) -> None:
        table = corpus()
        case = Case(
            id="leak",
            key="STR_ALPHA",
            category="test",
            expected_context="x",
            expected_locations=("src/lang/german.txt:3",),
        )
        with self.assertRaises((LeakageError, ValueError)):
            validate_case_evidence(case, table)

    def test_unknown_key_is_rejected(self) -> None:
        table = corpus()
        locator = OpenTTDLocator(table)
        case = Case(id="bad", key="STR_NOPE", category="test", expected_context="x")
        with self.assertRaises(ValueError):
            build_records(table, locator, [case], "zh-CN")

    def test_duplicate_case_key_is_rejected(self) -> None:
        data = load_dataset(CASES)
        data["cases"].append(dict(data["cases"][0]))
        with self.assertRaises(ValueError):
            parse_cases(data)

    def test_review_template_contains_human_ground_truth(self) -> None:
        # The audit context is for humans only; this asserts where it lives.
        data = load_dataset(CASES)
        self.assertIn("expected_context", data["cases"][0])


if __name__ == "__main__":
    unittest.main()

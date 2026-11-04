import unittest

from localization.ambiguity import detect_register_risks, detect_source_gaps
from localization.models import StringUnit, UiSpec


def unit(source, component=""):
    return StringUnit(id="gap.test", source=source, component=component, ui=UiSpec())


def gap_types(source, component=""):
    _, gaps = detect_source_gaps(unit(source, component), "zh-CN")
    return [gap["type"] for gap in gaps]


class AmbiguityTests(unittest.TestCase):
    def test_subject_omission(self):
        gaps = gap_types("点击确认后，将进入下一关")
        self.assertIn("subject", gaps)

    def test_tense_on_short_status_label(self):
        gaps = gap_types("解锁", component="label")
        self.assertIn("tense", gaps)

    def test_tense_skipped_for_button(self):
        gaps = gap_types("解锁", component="button")
        self.assertNotIn("tense", gaps)

    def test_explicit_aspect_marker_prevents_tense_gap(self):
        gaps = gap_types("已解锁", component="label")
        self.assertNotIn("tense", gaps)

    def test_demonstrative_reference(self):
        gaps = gap_types("这个英雄，血量不高")
        self.assertIn("reference", gaps)

    def test_pronoun_reference_is_warning(self):
        issues, gaps = detect_source_gaps(unit("它已解锁"), "zh-CN")
        reference = next(gap for gap in gaps if gap["type"] == "reference")
        self.assertEqual(reference["severity"], "warning")
        self.assertEqual(reference["code"], "SRC004")

    def test_unknown_placeholder_semantics(self):
        gaps = gap_types("提示 {0}")
        self.assertIn("placeholder_semantics", gaps)
        issues, gaps = detect_source_gaps(unit("提示 {0}"), "zh-CN")
        self.assertEqual(gaps[0]["code"], "SRC005")

    def test_low_confidence_placeholder_semantics(self):
        issues, gaps = detect_source_gaps(unit("前往 {0}"), "zh-CN")
        semantics = [gap for gap in gaps if gap["type"] == "placeholder_semantics"]
        self.assertEqual(len(semantics), 1)
        self.assertEqual(semantics[0]["code"], "SRC006")
        self.assertEqual(semantics[0]["severity"], "info")

    def test_count_semantics_does_not_create_gap(self):
        gaps = gap_types("获得 {0} 金币")
        self.assertNotIn("placeholder_semantics", gaps)

    def test_non_chinese_source_is_skipped(self):
        issues, gaps = detect_source_gaps(unit("Click confirm to continue"), "en-US")
        self.assertEqual(issues, [])
        self.assertEqual(gaps, [])

    def test_register_sarcasm_and_meme(self):
        issues, risks = detect_register_risks(unit("Oh, great."))
        self.assertEqual(len(risks), 1)
        self.assertEqual(risks[0]["type"], "sarcasm")
        self.assertEqual(issues[0].code, "REG001")

        issues, risks = detect_register_risks(unit("这次更新真香"))
        self.assertEqual(risks[0]["type"], "meme")

    def test_register_clean_text(self):
        issues, risks = detect_register_risks(unit("今天天气不错"))
        self.assertEqual(issues, [])
        self.assertEqual(risks, [])

    def test_register_keeps_strategy_and_question(self):
        _, risks = detect_register_risks(unit("氪金"))
        self.assertIn("意译", risks[0]["strategy"])
        self.assertIn("母语译者", risks[0]["question"])


if __name__ == "__main__":
    unittest.main()

import json
import unittest

from localization.dataset import build_dataset, load_demo, parse_text
from localization.engine import analyze
from localization.report import export, to_csv, to_json, to_xliff
from localization.xliff import parse_xliff


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        payload, _ = load_demo("zh_ptbr")
        cls.dataset = build_dataset(payload)
        cls.report = analyze(cls.dataset)

    def test_summary_shape(self):
        summary = self.report.summary
        self.assertEqual(summary["total_units"], 28)
        self.assertEqual(summary["unit_status"]["error"], 9)
        self.assertEqual(summary["overflow"]["overflow_units"], 3)
        self.assertEqual(summary["placeholders"]["units_with_errors"], 5)
        self.assertEqual(summary["context"]["matched_units"], 11)
        self.assertEqual(summary["source_gaps"]["units"], 4)
        self.assertEqual(summary["register"]["units"], 2)
        total_issues = sum(summary["issues"]["by_severity"].values())
        self.assertEqual(total_issues, summary["issues"]["total"])
        self.assertEqual(
            sum(summary["unit_status"][name] for name in ("pass", "info", "warning", "error")),
            summary["total_units"],
        )

    def test_every_issue_has_unit_and_evidence(self):
        for unit in self.report.units:
            for issue in unit.issues:
                self.assertEqual(issue.unit_id, unit.id)
                self.assertIn(issue.severity, ("error", "warning", "info"))
                self.assertTrue(issue.message)
                self.assertIn(issue.code, {"PH001", "PH002", "PH003", "PH004", "PH005", "PH006", "PH007", "PH008", "PH009", "PH010", "PH011", "PH012", "PH013", "OVF000", "OVF001", "OVF002", "OVF003", "OVF004", "OVF005", "CTX001", "CTX002", "CTX003", "SRC001", "SRC002", "SRC003", "SRC004", "SRC005", "SRC006", "REG001"})

    def test_empty_target(self):
        unit = next(unit for unit in self.report.units if unit.id == "empty.target")
        self.assertEqual([issue.code for issue in unit.issues], ["PH013"])

    def test_wrong_sense_is_flagged(self):
        unit = next(unit for unit in self.report.units if unit.id == "lore.world_setting")
        codes = [issue.code for issue in unit.issues]
        self.assertIn("CTX002", codes)

    def test_context_abstains_on_unknown(self):
        payload, _ = load_demo("en_ptbr")
        report = analyze(build_dataset(payload))
        unit = next(unit for unit in report.units if unit.id == "misc.rank_unknown")
        self.assertIsNone(unit.context["selected"])
        self.assertEqual(unit.context["status"], "insufficient")
        self.assertIn("CTX001", [issue.code for issue in unit.issues])

    def test_same_term_different_translations(self):
        payload, _ = load_demo("en_ptbr")
        report = analyze(build_dataset(payload))
        by_id = {unit.id: unit for unit in report.units}
        translations = {
            by_id["leaderboard.rank"].context["selected"]["translation"],
            by_id["hero.rank"].context["selected"]["translation"],
            by_id["inventory.rank"].context["selected"]["translation"],
        }
        self.assertEqual(translations, {"Classificação", "Patente", "Qualidade"})

    def test_deterministic_mode_default(self):
        self.assertEqual(self.report.engine["mode"], "deterministic")
        self.assertFalse(self.report.llm["configured"])
        self.assertFalse(self.report.llm["requested"])

    def test_report_json_serialisable(self):
        text = to_json(self.report)
        data = json.loads(text)
        self.assertEqual(data["summary"]["total_units"], 28)
        self.assertIn("limitations", data["engine"])
        self.assertIn("units", data)

    def test_csv_export(self):
        text = to_csv(self.report)
        lines = text.splitlines()
        self.assertEqual(len(lines), 29)
        self.assertIn("id,key,screen,component,source,target", lines[0])
        self.assertIn("settings.tab.settings", text)

    def test_xliff_roundtrip(self):
        text = to_xliff(self.report)
        handwritten = parse_xliff(text)
        rebuilt = build_dataset(handwritten)
        self.assertEqual(len(rebuilt.units), 28)
        self.assertEqual(rebuilt.units[0].id, "ui.common.confirm")
        self.assertEqual(rebuilt.units[0].source, "确认")
        self.assertEqual(rebuilt.units[0].target, "Confirmar")
        self.assertIn("dsh-issue", text)

    def test_export_dispatches(self):
        for fmt, mime in (
            ("json", "application/json"),
            ("csv", "text/csv"),
            ("xliff", "application/x"),
        ):
            bundle = export(self.report, fmt)
            self.assertIn(mime, bundle["mime"])
            self.assertTrue(bundle["content"])
        with self.assertRaises(ValueError):
            export(self.report, "yaml")

    def test_icu_plural_reports_missing_category_and_measurement_limit(self):
        payload, _ = load_demo("zh_ru")
        report = analyze(build_dataset(payload))
        unit = next(unit for unit in report.units if unit.id == "inventory.items.count")
        codes = [issue.code for issue in unit.issues]
        self.assertIn("PH008", codes)
        self.assertIn("OVF000", codes)

    def test_source_gap_questions_are_human_questions(self):
        unit = next(unit for unit in self.report.units if unit.id == "dialogue.next_level")
        gap = next(gap for gap in unit.source_gaps if gap["type"] == "subject")
        self.assertIn("主语", gap["question"])
        self.assertTrue(unit.needs_human)

    def test_llm_enhance_without_key_is_safe(self):
        report = analyze(self.dataset, llm_enhance=True)
        self.assertEqual(report.llm["calls"], 0)
        self.assertFalse(report.llm["configured"])
        self.assertEqual(report.engine["mode"], "deterministic")

    def test_overrides_from_api_shape(self):
        dataset = parse_text(
            json.dumps({"strings": [{"id": "a", "source": "设置", "target": "Configurações"}]}),
            "json",
            {"target_locale": "pt-BR", "ui_profile": "settings_tab"},
        )
        report = analyze(dataset)
        self.assertEqual(report.dataset.target_locale, "pt-BR")
        self.assertEqual(report.units[0].ui.profile, "settings_tab")


if __name__ == "__main__":
    unittest.main()

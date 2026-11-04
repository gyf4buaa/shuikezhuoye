import json
import unittest
from pathlib import Path

from localization.context import (
    TERMS,
    context_issues,
    match_term,
    normalize,
    resolve,
)
from localization.dataset import build_dataset, load_demo
from localization.models import StringUnit, UiSpec


def unit(source, target="", key="", screen="", component="", neighbors=None):
    return StringUnit(
        id="ctx.test",
        source=source,
        target=target,
        key=key,
        screen=screen,
        component=component,
        neighbors=neighbors or [],
        ui=UiSpec(),
    )


class ContextTests(unittest.TestCase):
    def test_settings_in_two_contexts(self):
        settings = unit(
            "Setting",
            "Configurações",
            key="settings.tab.audio",
            screen="settings",
            component="tab",
            neighbors=["Graphics", "Audio"],
        )
        lore = unit(
            "Setting",
            "Ambientação",
            key="lore.world.codex",
            screen="codex",
            component="entry",
            neighbors=["Lore", "World"],
        )
        r1 = resolve(settings, "pt-BR")
        r2 = resolve(lore, "pt-BR")
        self.assertEqual(r1["selected"]["id"], "settings_menu")
        self.assertEqual(r2["selected"]["id"], "world_setting")
        self.assertEqual(r1["selected"]["translation"], "Configurações")
        self.assertEqual(r2["selected"]["translation"], "Ambientação")
        self.assertEqual(context_issues(settings, r1), [])
        self.assertEqual(context_issues(lore, r2), [])

    def test_rank_has_three_senses(self):
        cases = [
            ("leaderboard.rank", "leaderboard", ["Score", "Season"], "leaderboard"),
            ("hero.military.rank", "character", ["Promote", "Army"], "military_rank"),
            ("inventory.item.rank", "inventory", ["Rare", "Epic"], "item_quality"),
        ]
        for key, screen, neighbors, expected in cases:
            result = resolve(
                unit("Rank", "某译名", key=key, screen=screen, component="row", neighbors=neighbors),
                "pt-BR",
            )
            self.assertEqual(result["status"], "resolved", key)
            self.assertEqual(result["selected"]["id"], expected, key)

    def test_claim_and_march(self):
        claim = resolve(
            unit("Claim", "Resgatar", key="daily.reward.claim", screen="daily", neighbors=["Reward"]),
            "pt-BR",
        )
        self.assertEqual(claim["selected"]["id"], "claim_reward")

        march = resolve(
            unit("March", "Março", key="calendar.event.march", screen="event", neighbors=["January"]),
            "pt-BR",
        )
        self.assertEqual(march["selected"]["id"], "march_month")

    def test_insufficient_evidence_abstains(self):
        result = resolve(unit("Rank", "Classificação"), "pt-BR")
        self.assertEqual(result["status"], "insufficient")
        self.assertIsNone(result["selected"])
        self.assertEqual(len(result["alternatives"]), 3)
        issues = context_issues(unit("Rank", "Classificação"), result)
        self.assertEqual(issues[0].code, "CTX001")
        self.assertIn("请补充", issues[0].suggestion)

    def test_target_uses_wrong_sense(self):
        target = unit(
            "Setting",
            "Configurações",
            key="lore.world.codex",
            screen="codex",
            component="entry",
            neighbors=["Lore", "World"],
        )
        result = resolve(target, "pt-BR")
        self.assertEqual(result["selected"]["id"], "world_setting")
        issues = context_issues(target, result)
        self.assertEqual(issues[0].code, "CTX002")
        self.assertEqual(issues[0].severity, "error")
        self.assertIn("Ambientação", issues[0].message)

    def test_target_missing_expected_translation(self):
        target = unit(
            "Claim",
            "Pegar",
            key="daily.reward.claim",
            screen="daily",
            neighbors=["Reward"],
        )
        result = resolve(target, "pt-BR")
        issues = context_issues(target, result)
        self.assertEqual(issues[0].code, "CTX003")

    def test_chinese_aliases(self):
        result = resolve(
            unit("设置", "Configurações", key="settings.tab.audio", screen="settings", neighbors=["画面"]),
            "pt-BR",
        )
        self.assertEqual(result["selected"]["id"], "settings_menu")
        lore = resolve(
            unit("世界观设定", "Ambientação", key="lore.world", screen="codex", neighbors=["剧情"]),
            "pt-BR",
        )
        self.assertEqual(lore["selected"]["id"], "world_setting")

    def test_alias_without_context_can_be_inferred_but_not_overclaimed(self):
        result = resolve(unit("设置"), "pt-BR")
        self.assertIn(result["status"], ("resolved", "inferred"))
        self.assertEqual(result["selected"]["id"], "settings_menu")
        self.assertIn("evidence", result)

    def test_evidence_and_confidence_are_exposed(self):
        result = resolve(
            unit("Rank", "Classificação", key="leaderboard.rank", screen="leaderboard", neighbors=["Score"]),
            "pt-BR",
        )
        self.assertTrue(result["evidence"])
        self.assertTrue(any(item["type"] == "key" for item in result["evidence"]))
        self.assertGreater(result["confidence"], 0)
        self.assertLessEqual(result["confidence"], 1)

    def test_no_term_returns_none(self):
        self.assertIsNone(resolve(unit("继续"), "pt-BR"))
        self.assertIsNone(match_term("继续"))

    def test_kb_complete_translations(self):
        for term in TERMS:
            for sense in term["senses"]:
                for locale in ("pt-BR", "de-DE", "ru-RU"):
                    self.assertIn(locale, sense["translations"], (term["id"], sense["id"], locale))

    def test_kb_file_is_synthetic_and_disclaims(self):
        path = Path(__file__).resolve().parent.parent / "data" / "polysemy.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("合成", data["_notice"])

    def test_normalize_removes_diacritics(self):
        self.assertEqual(normalize("Configurações"), "configuracoes")
        self.assertEqual(normalize("Настройки"), "настройки")

    def test_demo_counterexamples(self):
        payload, _ = load_demo("en_ptbr")
        dataset = build_dataset(payload)
        results = {unit.id: unit for unit in dataset.units}
        for unit_id, expected in [
            ("leaderboard.rank", "leaderboard"),
            ("hero.rank", "military_rank"),
            ("inventory.rank", "item_quality"),
            ("daily.claim", "claim_reward"),
            ("story.claim", "claim_assert"),
            ("ui.march_army", "march_move"),
            ("calendar.march", "march_month"),
        ]:
            result = resolve(results[unit_id], "pt-BR")
            self.assertEqual(result["selected"]["id"], expected, unit_id)
        unknown = resolve(results["misc.rank_unknown"], "pt-BR")
        self.assertEqual(unknown["status"], "insufficient")


if __name__ == "__main__":
    unittest.main()

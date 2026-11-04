import unittest

from localization.placeholders import (
    PLURAL_CATEGORIES,
    check_placeholders,
    infer_placeholder_semantics,
    tokenize,
)


def codes(issues):
    return [issue.code for issue in issues]


class PlaceholderTests(unittest.TestCase):
    def test_normal_placeholder_retained(self):
        issues, summary = check_placeholders("你好 {name}", "Olá {name}", "pt-BR")
        self.assertEqual(codes(issues), [])
        self.assertEqual(summary["source_keys"], ["name"])
        self.assertEqual(summary["target_keys"], ["name"])

    def test_missing_and_extra_placeholder(self):
        issues, summary = check_placeholders("获得 {0} 金币和 {1} 经验", "Obteve {0} moedas", "pt-BR")
        self.assertIn("PH002", codes(issues))
        self.assertEqual(summary["missing"], ["1"])

        issues, summary = check_placeholders("前往 {0}", "Vá para {0} e {1}", "pt-BR")
        self.assertIn("PH003", codes(issues))
        self.assertEqual(summary["extra"], ["1"])

    def test_unindexed_printf_reorder_is_an_error(self):
        issues, _ = check_placeholders(
            "获得 %s 金币，持续 %d 秒", "Obteve %d moedas por %s segundos", "pt-BR"
        )
        self.assertIn("PH005", codes(issues))

    def test_unindexed_to_indexed_reorder_is_safe(self):
        issues, summary = check_placeholders(
            "Hi %s, you have %d coins", "Olá %2$d moedas, você tem %1$s", "pt-BR"
        )
        self.assertTrue(summary["printf_reorder_safe"])
        self.assertNotIn("PH002", codes(issues))
        self.assertNotIn("PH005", codes(issues))
        self.assertIn("PH011", codes(issues))

    def test_indexed_printf_type_mismatch(self):
        issues, _ = check_placeholders("You have %1$d coins", "Você tem %1$s moedas", "pt-BR")
        self.assertIn("PH004", codes(issues))

    def test_icu_plural_required_categories(self):
        source = "{count} 个新消息"
        incomplete = "{count, plural, one {# nova mensagem}}"
        issues, _ = check_placeholders(source, incomplete, "pt-BR")
        self.assertIn("PH008", codes(issues))
        self.assertNotIn("PH001", codes(issues))

        complete = "{count, plural, one {# nova mensagem} other {# novas mensagens}}"
        issues, _ = check_placeholders(source, complete, "pt-BR")
        self.assertNotIn("PH008", codes(issues))

    def test_russian_plural_needs_four_categories(self):
        source = "{count} 个道具"
        incomplete = "{count, plural, one {# предмет} few {# предмета} many {# предметов}}"
        issues, _ = check_placeholders(source, incomplete, "ru-RU")
        self.assertIn("PH008", codes(issues))
        plural_issue = next(issue for issue in issues if issue.code == "PH008")
        self.assertIn("other", plural_issue.extra["missing_categories"])

    def test_icu_extension_is_info_not_grammar_claim(self):
        issues, _ = check_placeholders("{0} 个道具", "{0, plural, one {# item} other {# items}}", "en-US")
        self.assertIn("PH010", codes(issues))
        ph010 = next(issue for issue in issues if issue.code == "PH010")
        self.assertEqual(ph010.severity, "info")
        self.assertIn("不代表", ph010.suggestion)

    def test_unclosed_icu_branch_is_syntax_error(self):
        issues, _ = check_placeholders("{count} 个消息", "{count, plural, one {# mensagem}", "pt-BR")
        self.assertIn("PH001", codes(issues))

    def test_rich_text_imbalance(self):
        issues, _ = check_placeholders("<b>稀有</b>装备", "<b>Equipamento raro", "pt-BR")
        self.assertIn("PH006", codes(issues))
        self.assertIn("PH007", codes(issues))

    def test_literal_percent_is_not_a_format_error(self):
        issues, _ = check_placeholders("掉落概率 {0}%", "Chance de saque: {0}%", "pt-BR")
        self.assertNotIn("PH001", codes(issues))

    def test_invalid_printf_is_a_format_error(self):
        issues, _ = check_placeholders("进度 %q", "Progresso %q", "pt-BR")
        self.assertIn("PH001", codes(issues))

    def test_escaped_braces(self):
        issues, _ = check_placeholders("字面量 {{name}}", "literal {{name}}", "pt-BR")
        self.assertEqual(codes(issues), [])

    def test_dotnet_custom_format(self):
        issues, _ = check_placeholders("得分 {0:N0}", "Pontos {0:N0}", "pt-BR")
        self.assertEqual(codes(issues), [])
        tokens, problems = tokenize("{0:N0}")
        self.assertEqual(problems, [])
        self.assertEqual(tokens[0].meta["format_kind"], "custom")

    def test_quantity_advisory(self):
        issues, _ = check_placeholders("获得 {0} 金币", "Obteve {0} moedas", "pt-BR")
        self.assertIn("PH012", codes(issues))
        message = next(issue for issue in issues if issue.code == "PH012").message
        self.assertIn("不判断语法正确性", next(issue for issue in issues if issue.code == "PH012").suggestion)

    def test_infer_semantics(self):
        count = infer_placeholder_semantics("获得 {0} 金币")[0]
        self.assertEqual(count["inferred"], "count")
        self.assertEqual(count["confidence"], "high")

        location = infer_placeholder_semantics("前往 {0}")[0]
        self.assertEqual(location["inferred"], "name_or_location")
        self.assertEqual(location["confidence"], "low")

        unknown = infer_placeholder_semantics("提示 {0}")[0]
        self.assertEqual(unknown["inferred"], "unknown")

    def test_plural_categories_cover_demo_locales(self):
        for locale in ("pt-BR", "de-DE", "ru-RU", "es-ES", "fr-FR", "en-US"):
            base = locale.split("-")[0]
            self.assertIn(base, PLURAL_CATEGORIES)
            self.assertIn("other", PLURAL_CATEGORIES[base])


if __name__ == "__main__":
    unittest.main()

import unittest

from localization.models import StringUnit, UiSpec
from localization.overflow import measure, overflow_issues, plain_text, render_preview_svg


def make_unit(target, profile="settings_tab", **overrides):
    base = {
        "font_size": 16,
        "box_w": 110,
        "box_h": 36,
        "max_lines": 1,
        "line_height": 1.3,
        "padding": 6,
        "letter_spacing": 0,
    }
    base.update(overrides)
    return StringUnit(
        id="unit.test",
        source="测试",
        target=target,
        ui=UiSpec(profile=profile, **base),
    )


def codes(unit):
    result = measure(unit)
    return [issue.code for issue in overflow_issues(unit, result)], result


class OverflowTests(unittest.TestCase):
    def test_normal_fits(self):
        unit = make_unit("Áudio")
        result = measure(unit)
        self.assertTrue(result["supported"])
        self.assertFalse(result["measured"]["overflow"])
        self.assertTrue(result["naive"]["fits"])

    def test_real_overflow(self):
        unit = make_unit("Configurações")
        issues, result = codes(unit)
        self.assertTrue(result["measured"]["overflow"])
        self.assertIn("OVF001", issues)
        self.assertEqual(result["measured"]["line_count"], 1)
        self.assertGreater(result["measured"]["max_line_width_px"], 98)

    def test_near_threshold(self):
        unit = make_unit("Sensibilidade")
        issues, result = codes(unit)
        self.assertFalse(result["measured"]["overflow"])
        self.assertGreaterEqual(result["measured"]["width_ratio"], 0.9)
        self.assertIn("OVF002", issues)

    def test_char_baseline_false_negative(self):
        unit = make_unit("MMXXV", profile="badge", font_size=14, box_w=51, box_h=26, padding=4, line_height=1.2)
        issues, result = codes(unit)
        self.assertTrue(result["measured"]["overflow"])
        self.assertTrue(result["naive"]["fits"])
        self.assertIn("OVF004", issues)

    def test_char_baseline_false_positive(self):
        unit = make_unit("Ilha", profile="micro_badge", font_size=14, box_w=38, box_h=26, padding=4, line_height=1.2)
        issues, result = codes(unit)
        self.assertFalse(result["measured"]["overflow"])
        self.assertFalse(result["naive"]["fits"])
        self.assertIn("OVF005", issues)
        self.assertNotIn("OVF001", issues)

    def test_wrapping_fits_two_lines(self):
        unit = make_unit(
            "Clique em Confirmar para entrar na próxima fase",
            profile="mobile_dialog",
            font_size=16,
            box_w=280,
            box_h=72,
            max_lines=2,
            padding=10,
            line_height=1.4,
        )
        result = measure(unit)
        self.assertFalse(result["measured"]["overflow"])
        self.assertGreaterEqual(result["measured"]["line_count"], 2)

    def test_single_line_does_not_invent_wrapping(self):
        unit = make_unit(
            "Festival de Inverno por tempo limitado",
            profile="banner_title",
            font_size=22,
            box_w=360,
            box_h=44,
            max_lines=1,
            padding=8,
            line_height=1.2,
            letter_spacing=0.2,
        )
        result = measure(unit)
        self.assertTrue(result["measured"]["overflow"])
        self.assertEqual(result["measured"]["line_count"], 1)
        self.assertTrue(any("宽度" in reason for reason in result["measured"]["reasons"]))
        self.assertFalse(any("行" in reason for reason in result["measured"]["reasons"]))

    def test_unsupported_cjk_is_not_a_fake_measurement(self):
        unit = make_unit("设置")
        result = measure(unit)
        self.assertFalse(result["supported"])
        self.assertIn("CJK", result["reason"])
        issues = overflow_issues(unit, result)
        self.assertEqual(issues[0].code, "OVF000")

    def test_icu_template_measurement_is_refused(self):
        unit = make_unit("Получено {0, plural, one {# предмет} other {# предмета}}")
        result = measure(unit)
        self.assertFalse(result["supported"])
        self.assertIn("plural", result["reason"])
        self.assertEqual(overflow_issues(unit, result)[0].code, "OVF000")

    def test_empty_text(self):
        unit = make_unit("")
        result = measure(unit)
        self.assertTrue(result["supported"])
        self.assertEqual(result["measured"]["line_count"], 1)
        self.assertFalse(result["measured"]["overflow"])

    def test_letter_spacing_increases_width(self):
        normal = measure(make_unit("Configurações", letter_spacing=0))["measured"]["max_line_width_px"]
        spaced = measure(make_unit("Configurações", letter_spacing=2))["measured"]["max_line_width_px"]
        self.assertGreater(spaced, normal)

    def test_plain_text_strips_tags_and_keeps_newlines(self):
        self.assertEqual(plain_text("<b>Olá</b><br/>mundo"), "Olá\nmundo")
        self.assertEqual(plain_text("{0} <color=#fff>itens</color>"), "{0} itens")

    def test_preview_svg(self):
        unit = make_unit("Configurações")
        result = measure(unit)
        svg = render_preview_svg(unit, result)
        self.assertIn("<svg", svg)
        self.assertIn("Configurações", svg)


if __name__ == "__main__":
    unittest.main()

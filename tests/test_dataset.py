import json
import unittest

from localization.dataset import (
    DatasetError,
    build_dataset,
    list_demos,
    load_demo,
    parse_text,
)


class DatasetTests(unittest.TestCase):
    def test_json_with_overrides(self):
        text = json.dumps(
            {
                "project": "demo",
                "source_locale": "zh-CN",
                "target_locale": "de-DE",
                "strings": [
                    {"id": "a", "source": "设置", "target": "Einstellungen", "key": "settings.tab"},
                ],
            }
        )
        dataset = parse_text(text, "json", {"target_locale": "pt-BR", "ui_profile": "settings_tab"})
        self.assertEqual(dataset.target_locale, "pt-BR")
        self.assertEqual(dataset.units[0].ui.profile, "settings_tab")

    def test_json_list_shorthand(self):
        dataset = build_dataset([{"id": "a", "source": "确认", "target": "Confirmar"}])
        self.assertEqual(len(dataset.units), 1)
        self.assertEqual(dataset.source_locale, "zh-CN")

    def test_jsonl(self):
        text = '\n'.join(
            [
                json.dumps({"id": "a", "source": "设置", "target": "Configurações"}),
                json.dumps({"id": "b", "source": "确认", "target": "Confirmar"}),
            ]
        )
        dataset = parse_text(text, "jsonl")
        self.assertEqual([unit.id for unit in dataset.units], ["a", "b"])

    def test_csv_with_meta_and_ui(self):
        text = """# project=CSV 演示
# target_locale=pt-BR
# source_locale=zh-CN
id,source,target,key,screen,component,neighbors,max_chars,profile,box_w
a,设置,Configurações,settings.tab,settings,tab,画面|音频,12,settings_tab,120
b,确认,Confirmar,common.confirm,dialog,button,,,,
"""
        dataset = parse_text(text, "csv")
        self.assertEqual(dataset.project, "CSV 演示")
        self.assertEqual(dataset.target_locale, "pt-BR")
        self.assertEqual(dataset.units[0].neighbors, ["画面", "音频"])
        self.assertEqual(dataset.units[0].max_chars, 12)
        self.assertEqual(dataset.units[0].ui.profile, "settings_tab")
        self.assertEqual(dataset.units[0].ui.box_w, 120)
        self.assertEqual(dataset.units[1].ui.profile, "mobile_dialog")

    def test_auto_detects_formats(self):
        self.assertEqual(parse_text('{"strings":[{"id":"a","source":"x","target":"y"}]}').units[0].id, "a")
        self.assertEqual(parse_text('{"id":"a","source":"x","target":"y"}').units[0].id, "a")
        self.assertEqual(parse_text('id,source,target\na,x,y').units[0].id, "a")
        jsonl = '{"id":"a","source":"x","target":"y"}\n{"id":"b","source":"x2","target":"y2"}'
        self.assertEqual([unit.id for unit in parse_text(jsonl).units], ["a", "b"])

    def test_xliff_import(self):
        text = """<?xml version="1.0" encoding="UTF-8"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
  <file source-language="zh-CN" target-language="pt-BR" original="xliff demo">
    <body>
      <trans-unit id="a"><source>设置</source><target>Configurações</target>
        <note from="dsh-context">{"key":"settings.tab","screen":"settings","neighbors":["画面","音频"],"ui":{"profile":"settings_tab"}}</note>
      </trans-unit>
    </body>
  </file>
</xliff>"""
        dataset = parse_text(text, "xliff")
        self.assertEqual(dataset.project, "xliff demo")
        self.assertEqual(dataset.units[0].key, "settings.tab")
        self.assertEqual(dataset.units[0].neighbors, ["画面", "音频"])
        self.assertEqual(dataset.units[0].ui.profile, "settings_tab")

    def test_duplicate_id_rejected(self):
        with self.assertRaises(DatasetError):
            build_dataset(
                {
                    "strings": [
                        {"id": "a", "source": "x", "target": "y"},
                        {"id": "a", "source": "x2", "target": "y2"},
                    ]
                }
            )

    def test_missing_source_rejected(self):
        with self.assertRaises(DatasetError):
            build_dataset({"strings": [{"id": "a", "target": "y"}]})

    def test_ui_must_be_object(self):
        with self.assertRaises(DatasetError):
            build_dataset({"strings": [{"id": "a", "source": "x", "target": "y", "ui": "settings_tab"}]})

    def test_unknown_profile_rejected(self):
        with self.assertRaises(DatasetError):
            build_dataset(
                {"strings": [{"id": "a", "source": "x", "target": "y", "ui": {"profile": "nope"}}]}
            )

    def test_bad_box_rejected(self):
        with self.assertRaises(DatasetError):
            build_dataset(
                {
                    "strings": [
                        {"id": "a", "source": "x", "target": "y", "ui": {"profile": "settings_tab", "padding": 60}}
                    ]
                }
            )

    def test_empty_strings_rejected(self):
        with self.assertRaises(DatasetError):
            build_dataset({"strings": []})

    def test_bad_json_rejected(self):
        with self.assertRaises(DatasetError):
            parse_text("{not json", "json")

    def test_bad_format_rejected(self):
        with self.assertRaises(DatasetError):
            parse_text("whatever", "yaml")

    def test_demo_catalogue(self):
        demos = list_demos()
        self.assertGreaterEqual(len(demos), 3)
        for demo in demos:
            payload, _ = load_demo(demo["name"])
            dataset = build_dataset(payload)
            self.assertGreater(len(dataset.units), 0)

    def test_unknown_demo_rejected(self):
        with self.assertRaises(DatasetError):
            load_demo("../etc/passwd")


if __name__ == "__main__":
    unittest.main()

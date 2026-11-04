import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class CLITests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "check.py")] + list(args),
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_batch_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_cli(str(ROOT / "data" / "demo_zh_ptbr.json"), "--out", tmp, "--target", "pt-BR")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("文本: 28 条", result.stdout)
            out = Path(tmp)
            for name in ("report.json", "report.csv", "checked.xliff"):
                self.assertTrue((out / name).exists(), name)
            report = json.loads((out / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["total_units"], 28)
            csv_bytes = (out / "report.csv").read_bytes()
            self.assertTrue(csv_bytes.startswith(b"\xef\xbb\xbf"), "CSV 应带 UTF-8 BOM 便于 Excel")
            self.assertIn(b"settings.tab.settings", csv_bytes)

    def test_fail_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_cli(
                str(ROOT / "data" / "demo_zh_ptbr.json"),
                "--out", tmp,
                "--fail-on", "error",
            )
            self.assertEqual(result.returncode, 1, result.stderr)

    def test_invalid_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            result = self.run_cli(str(bad), "--out", str(Path(tmp) / "out"))
            self.assertEqual(result.returncode, 2)
            self.assertIn("输入校验失败", result.stderr)

    def test_xliff_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "in.xliff"
            source.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
  <file source-language="zh-CN" target-language="pt-BR" original="cli-xliff">
    <body><trans-unit id="a"><source>设置</source><target>Configurações</target></trans-unit></body>
  </file>
</xliff>""",
                encoding="utf-8",
            )
            out = Path(tmp) / "out"
            result = self.run_cli(str(source), "--out", str(out), "--format", "xliff")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("文本: 1 条", result.stdout)


if __name__ == "__main__":
    unittest.main()

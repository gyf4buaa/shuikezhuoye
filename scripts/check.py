#!/usr/bin/env python3
"""Reproducible batch flow: import -> analyze -> export.

Example:
    python3 scripts/check.py data/demo_zh_ptbr.json --out out/demo --target pt-BR
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from localization.dataset import DatasetError, parse_text  # noqa: E402
from localization.engine import analyze  # noqa: E402
from localization.report import to_csv, to_json, to_xliff  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="本地化预检：批量导入 → 检查 → 导出")
    parser.add_argument("input", help="输入文件（JSON / JSONL / CSV / XLIFF 1.2）")
    parser.add_argument("--format", default="auto", choices=["auto", "json", "jsonl", "csv", "xliff"])
    parser.add_argument("--target", default="", help="覆盖目标语言，如 pt-BR")
    parser.add_argument("--source", default="", help="覆盖源语言，如 zh-CN")
    parser.add_argument("--ui-profile", default="", help="覆盖默认 UI 盒模型")
    parser.add_argument("--out", default="out", help="输出目录（默认 out/）")
    parser.add_argument("--llm", action="store_true", help="对修辞风险调用已配置的实时 LLM（需 LLM_API_KEY）")
    parser.add_argument("--fail-on", choices=["none", "error", "warning"], default="none",
                        help="达到该严重级别时以非零码退出（用于 CI）")
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        print("输入文件不存在: %s" % input_path, file=sys.stderr)
        return 2
    text = input_path.read_text(encoding="utf-8")
    overrides = {}
    for name, value in (("target_locale", args.target), ("source_locale", args.source), ("ui_profile", args.ui_profile)):
        if value:
            overrides[name] = value

    try:
        dataset = parse_text(text, args.format, overrides)
    except DatasetError as exc:
        print("输入校验失败: %s" % exc, file=sys.stderr)
        return 2

    report = analyze(dataset, llm_enhance=args.llm)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(to_json(report), encoding="utf-8")
    (out_dir / "report.csv").write_text(to_csv(report), encoding="utf-8-sig")
    (out_dir / "checked.xliff").write_text(to_xliff(report), encoding="utf-8")

    summary = report.summary
    print("项目: %s" % dataset.project)
    print("语言: %s → %s" % (dataset.source_locale, dataset.target_locale))
    print("文本: %d 条" % summary["total_units"])
    print("问题: error=%d warning=%d info=%d" % (
        summary["issues"]["by_severity"]["error"],
        summary["issues"]["by_severity"]["warning"],
        summary["issues"]["by_severity"]["info"],
    ))
    print("需人工: %d 条 | 渲染溢出: %d 条 | 消歧弃答: %d 条" % (
        summary["needs_human_units"],
        summary["overflow"]["overflow_units"],
        summary["context"]["insufficient"],
    ))
    print("输出: %s" % out_dir.resolve())
    for path in ("report.json", "report.csv", "checked.xliff"):
        print("  - %s" % (out_dir / path))

    if args.fail_on != "none":
        threshold = args.fail_on
        counts = summary["issues"]["by_severity"]
        if threshold == "error" and counts["error"] > 0:
            return 1
        if threshold == "warning" and (counts["error"] > 0 or counts["warning"] > 0):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

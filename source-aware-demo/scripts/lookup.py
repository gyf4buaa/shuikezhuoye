#!/usr/bin/env python3
"""Reproducible offline retrieval check (no model call).

Examples:
    python3 scripts/lookup.py --list
    python3 scripts/lookup.py ui.leaderboard.rank_column
    python3 scripts/lookup.py ui.leaderboard.rank_column --json

The printed paths, lines and snippets come from a live read of demo_project/.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sourceaware.catalog import Catalog, CatalogError, UnknownStringKey  # noqa: E402
from sourceaware.retrieval import search  # noqa: E402


def _pretty(payload) -> str:
    counts = payload["counts"]
    scope = payload["scope"]
    lines = [
        "Key:    %s" % payload["key"],
        'Source: "%s"' % payload["source"],
        "Shared: %s" % (", ".join(payload["shared_with"]) or "(none)"),
        "Found:  %s (direct key refs=%s, literal candidates=%s, string tables=%s)"
        % (payload["found"], counts["code_key"], counts["code_literal"], counts["string_table"]),
        "Scan:   %s files / %s lines in demo_project (read-only), %s ms"
        % (scope["files_scanned"], scope["lines_scanned"], payload["elapsed_ms"]),
    ]
    if payload["note"]:
        lines.append("Note:   %s" % payload["note"])
    for item in payload["evidence"]:
        symbol = item["symbol"]
        symbol_text = ""
        if symbol.get("class"):
            symbol_text = symbol["class"]
            if symbol.get("member"):
                symbol_text += "." + symbol["member"]
        lines.append("")
        lines.append(
            "[%s] %s %s %s:%s:%s %s"
            % (
                item["id"],
                item["kind"],
                "direct" if item["direct"] else "candidate",
                item["path"],
                item["line"],
                item["column"],
                symbol_text,
            )
        )
        for snippet in item["snippet"]:
            marker = ">" if snippet["match"] else " "
            lines.append("  %s %4s | %s" % (marker, snippet["line"], snippet["text"]))
        inference = item["inference"]
        lines.append(
            "  inference: %s (confidence=%s, needs_human=%s)"
            % (inference["summary"], inference["confidence"], inference["needs_human"])
        )
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="源码检索证据检查（不调用模型）")
    parser.add_argument("key", nargs="?", help="字符串 Key")
    parser.add_argument("--list", action="store_true", help="列出所有 Key")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    parser.add_argument("--project", default=str(ROOT / "demo_project"), help="演示工程目录")
    args = parser.parse_args(argv)

    try:
        catalog = Catalog(Path(args.project))
        if args.list:
            for record in catalog.strings():
                suffix = " [shared: %s]" % ", ".join(record.shared_with) if record.shared_with else ""
                print("%-30s %-18s %s:%s%s" % (record.key, record.source, record.table, record.line, suffix))
            return 0
        if not args.key:
            parser.print_help()
            return 2
        payload = search(catalog, args.key)
    except UnknownStringKey as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except CatalogError as exc:
        print("无法加载演示工程: %s" % exc, file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_pretty(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

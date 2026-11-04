"""Structured exports: JSON, CSV and XLIFF 1.2."""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List

from .models import Report
from .xliff import build_xliff


def to_json(report: Report, pretty: bool = True) -> str:
    data = report.to_dict()
    if pretty:
        return json.dumps(data, ensure_ascii=False, indent=2)
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


CSV_HEADERS = [
    "id",
    "key",
    "screen",
    "component",
    "source",
    "target",
    "status",
    "needs_human",
    "issue_codes",
    "issue_messages",
    "placeholder_errors",
    "overflow_measured",
    "overflow_naive_width_px",
    "context_term",
    "context_status",
    "context_selected",
    "source_gap_types",
    "register_types",
]


def to_csv(report: Report) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_HEADERS)
    for unit in report.units:
        issues = unit.issues
        placeholder_errors = [
            issue for issue in issues if issue.category in ("placeholder", "template") and issue.severity == "error"
        ]
        overflow_measured = ""
        overflow_naive = ""
        if unit.overflow and unit.overflow.get("supported", True):
            overflow_measured = "overflow" if unit.overflow["measured"]["overflow"] else "fit"
            overflow_naive = unit.overflow["naive"]["estimated_width_px"]
        writer.writerow(
            [
                unit.id,
                unit.key,
                unit.screen,
                unit.component,
                unit.source,
                unit.target,
                unit.status,
                "yes" if unit.needs_human else "no",
                ";".join(issue.code for issue in issues),
                " | ".join("[%s] %s" % (issue.severity, issue.message) for issue in issues),
                len(placeholder_errors),
                overflow_measured,
                overflow_naive,
                (unit.context or {}).get("term", ""),
                (unit.context or {}).get("status", ""),
                ((unit.context or {}).get("selected") or {}).get("translation", ""),
                ";".join(gap.get("type", "") for gap in unit.source_gaps),
                ";".join(risk.get("type", "") for risk in unit.register_risks),
            ]
        )
    return buffer.getvalue()


def to_xliff(report: Report) -> str:
    return build_xliff(report.dataset, report)


EXPORTERS = {
    "json": ("application/json; charset=utf-8", "report.json", to_json),
    "csv": ("text/csv; charset=utf-8", "report.csv", to_csv),
    "xliff": ("application/xliff+xml; charset=utf-8", "checked.xliff", to_xliff),
}


def export(report: Report, fmt: str) -> Dict[str, str]:
    fmt = (fmt or "json").lower()
    if fmt not in EXPORTERS:
        raise ValueError("未知导出格式 %r（可选 json/csv/xliff）" % fmt)
    mime, filename, writer = EXPORTERS[fmt]
    return {
        "mime": mime,
        "filename": filename,
        "content": writer(report),
    }

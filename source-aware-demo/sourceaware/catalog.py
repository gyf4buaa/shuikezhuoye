"""Read the synthetic demo project's string tables.

The catalog is a faithful reader of files on disk: it does not contain a
hand-written table of expected results. If the files change, the keys, source
text and line numbers change with them.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


class CatalogError(Exception):
    """Base error for demo-project catalog problems."""


class UnknownStringKey(CatalogError):
    """Raised when a requested key is not present in the string table."""


@dataclass(frozen=True)
class StringRecord:
    key: str
    source: str
    table: str
    line: int
    shared_with: Tuple[str, ...] = ()

    def public(self) -> Dict[str, object]:
        return {
            "key": self.key,
            "source": self.source,
            "table": self.table,
            "line": self.line,
            "shared_with": list(self.shared_with),
        }


def _json_key_line(lines: Sequence[str], key: str) -> int:
    token = json.dumps(key, ensure_ascii=False)
    for index, line in enumerate(lines, start=1):
        if token in line:
            return index
    return 0


def _load_json_table(path: Path) -> Tuple[str, List[Tuple[str, str, int]]]:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise CatalogError("字符串表必须是 JSON 对象: %s" % path.name)
    meta = data.get("_meta")
    project_name = ""
    if isinstance(meta, dict) and isinstance(meta.get("project"), str):
        project_name = meta["project"]
    lines = text.splitlines()
    rows: List[Tuple[str, str, int]] = []
    for key, value in data.items():
        if key == "_meta":
            continue
        if not isinstance(value, str):
            raise CatalogError("字符串值必须是文本: %s" % key)
        rows.append((key, value, _json_key_line(lines, key)))
    return project_name, rows


def _load_csv_table(path: Path) -> List[Tuple[str, str, int]]:
    text = path.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "key" not in reader.fieldnames or "source" not in reader.fieldnames:
        raise CatalogError("CSV 字符串表需要 key, source 两列: %s" % path.name)
    rows: List[Tuple[str, str, int]] = []
    for index, row in enumerate(reader, start=2):
        key = (row.get("key") or "").strip()
        source = (row.get("source") or "").strip()
        if key and source:
            rows.append((key, source, index))
    return rows


class Catalog:
    """Read-only catalog of the synthetic project's source strings."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root).resolve()
        if not self.project_root.is_dir():
            raise CatalogError("演示工程目录不存在: %s" % self.project_root)
        self._records: Optional[List[StringRecord]] = None
        self._project_name = "Synthetic Demo Project"
        self.table_file = self.project_root / "Assets" / "Localization" / "en.json"

    @property
    def project_name(self) -> str:
        self._ensure_loaded()
        return self._project_name

    def _ensure_loaded(self) -> None:
        if self._records is not None:
            return
        if self.table_file.is_file():
            project_name, rows = _load_json_table(self.table_file)
            relative_table = self.table_file.relative_to(self.project_root).as_posix()
        else:
            csv_path = self.csv_table()
            if not csv_path.is_file():
                raise CatalogError("找不到字符串表: %s" % self.table_file)
            project_name = ""
            rows = _load_csv_table(csv_path)
            relative_table = csv_path.relative_to(self.project_root).as_posix()
        if project_name:
            self._project_name = project_name

        by_source: Dict[str, List[str]] = {}
        for key, source, _line in rows:
            by_source.setdefault(source, []).append(key)

        records: List[StringRecord] = []
        for key, source, line in rows:
            peers = tuple(sorted(other for other in by_source[source] if other != key))
            records.append(
                StringRecord(
                    key=key,
                    source=source,
                    table=relative_table,
                    line=line,
                    shared_with=peers,
                )
            )
        self._records = sorted(records, key=lambda record: record.key)

    def strings(self) -> List[StringRecord]:
        self._ensure_loaded()
        assert self._records is not None
        return list(self._records)

    def get(self, key: str) -> StringRecord:
        self._ensure_loaded()
        assert self._records is not None
        for record in self._records:
            if record.key == key:
                return record
        raise UnknownStringKey("未知字符串 Key: %s" % key)

    def csv_table(self) -> Path:
        return self.project_root / "Assets" / "Localization" / "ui_strings.csv"

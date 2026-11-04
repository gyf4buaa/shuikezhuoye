"""Dataset loading: JSON, JSONL and CSV with explicit validation.

The prototype deliberately uses a plain, documented interchange format so a
course reviewer can inspect every input without installing a CAT tool.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .models import Dataset, StringUnit, UiSpec
from .xliff import parse_xliff

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

MAX_UNITS = 500
MAX_TEXT_LEN = 4000

DEFAULT_UI_PROFILES: Dict[str, Dict[str, Any]] = {
    "mobile_dialog": {
        "font_size": 16,
        "box_w": 280,
        "box_h": 72,
        "max_lines": 2,
        "line_height": 1.4,
        "padding": 10,
        "letter_spacing": 0,
    },
    "settings_tab": {
        "font_size": 16,
        "box_w": 110,
        "box_h": 36,
        "max_lines": 1,
        "line_height": 1.3,
        "padding": 6,
        "letter_spacing": 0,
    },
    "inventory_cell": {
        "font_size": 13,
        "box_w": 100,
        "box_h": 48,
        "max_lines": 2,
        "line_height": 1.25,
        "padding": 4,
        "letter_spacing": 0,
    },
    "banner_title": {
        "font_size": 22,
        "box_w": 360,
        "box_h": 44,
        "max_lines": 1,
        "line_height": 1.2,
        "padding": 8,
        "letter_spacing": 0.2,
    },
    "tooltip": {
        "font_size": 16,
        "box_w": 240,
        "box_h": 72,
        "max_lines": 3,
        "line_height": 1.3,
        "padding": 8,
        "letter_spacing": 0,
    },
    "badge": {
        "font_size": 14,
        "box_w": 51,
        "box_h": 26,
        "max_lines": 1,
        "line_height": 1.2,
        "padding": 4,
        "letter_spacing": 0,
    },
    "micro_badge": {
        "font_size": 14,
        "box_w": 38,
        "box_h": 26,
        "max_lines": 1,
        "line_height": 1.2,
        "padding": 4,
        "letter_spacing": 0,
    },
}

UI_FIELDS = ("font_size", "box_w", "box_h", "max_lines", "line_height", "padding", "letter_spacing")


class DatasetError(ValueError):
    """Raised when an input dataset cannot be analysed safely."""


def _load_ui_profiles() -> Dict[str, Dict[str, Any]]:
    path = DATA_DIR / "ui_profiles.json"
    if not path.exists():
        return dict(DEFAULT_UI_PROFILES)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - defensive
        raise DatasetError("data/ui_profiles.json 无法读取: %s" % exc) from exc
    if not isinstance(data, dict) or not data:
        raise DatasetError("data/ui_profiles.json 必须是非空 JSON 对象")
    merged = dict(DEFAULT_UI_PROFILES)
    for name, profile in data.items():
        if name.startswith("_"):
            continue
        if not isinstance(profile, dict):
            raise DatasetError("UI profile %r 必须是对象" % name)
        merged[name] = profile
    return merged


UI_PROFILES = _load_ui_profiles()


def _as_text(value: Any, field: str, where: str, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise DatasetError("%s 的 %s 必须是字符串" % (where, field))
    text = value
    if len(text) > MAX_TEXT_LEN:
        raise DatasetError("%s 的 %s 超过 %d 字符上限" % (where, field, MAX_TEXT_LEN))
    if required and not text.strip():
        raise DatasetError("%s 缺少必填字段 %s" % (where, field))
    return text


def _as_int(value: Any, field: str, where: str, minimum: int = 0) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise DatasetError("%s 的 %s 必须是整数" % (where, field))
    if isinstance(value, str):
        try:
            value = int(value.strip())
        except ValueError as exc:
            raise DatasetError("%s 的 %s 必须是整数" % (where, field)) from exc
    if not isinstance(value, int):
        raise DatasetError("%s 的 %s 必须是整数" % (where, field))
    if value < minimum:
        raise DatasetError("%s 的 %s 不能小于 %d" % (where, field, minimum))
    return value


def _as_float(value: Any, field: str, where: str) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise DatasetError("%s 的 %s 必须是数字" % (where, field))
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DatasetError("%s 的 %s 必须是数字" % (where, field)) from exc
    if number <= 0 and field != "letter_spacing":
        raise DatasetError("%s 的 %s 必须大于 0" % (where, field))
    if field == "letter_spacing" and number < 0:
        raise DatasetError("%s 的 %s 不能为负数" % (where, field))
    return number


def _parse_neighbors(value: Any, where: str) -> List[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in value.split("|")]
    elif isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            if not isinstance(item, str):
                raise DatasetError("%s 的 neighbors 必须是字符串列表" % where)
            parts.append(item.strip())
    else:
        raise DatasetError("%s 的 neighbors 必须是字符串或字符串列表" % where)
    return [p for p in parts if p]


def _resolve_ui(profile_name: str, ui_override: Optional[Dict[str, Any]], where: str) -> UiSpec:
    if not isinstance(profile_name, str) or not profile_name:
        raise DatasetError("%s 的 ui.profile 必须是非空字符串" % where)
    base = UI_PROFILES.get(profile_name)
    if base is None:
        raise DatasetError(
            "%s 引用了未知 UI profile %r；可用: %s"
            % (where, profile_name, ", ".join(sorted(UI_PROFILES)))
        )
    merged = dict(base)
    if ui_override:
        if not isinstance(ui_override, dict):
            raise DatasetError("%s 的 ui 必须是对象" % where)
        for name in UI_FIELDS:
            if name in ui_override and ui_override[name] not in (None, ""):
                merged[name] = ui_override[name]
    values: Dict[str, Any] = {"profile": profile_name}
    values["font_size"] = _as_float(merged.get("font_size"), "font_size", where)
    values["box_w"] = _as_float(merged.get("box_w"), "box_w", where)
    values["box_h"] = _as_float(merged.get("box_h"), "box_h", where)
    values["line_height"] = _as_float(merged.get("line_height"), "line_height", where)
    values["padding"] = _as_float(merged.get("padding", 0), "padding", where)
    values["letter_spacing"] = _as_float(merged.get("letter_spacing", 0), "letter_spacing", where)
    max_lines = _as_int(merged.get("max_lines"), "max_lines", where, minimum=1)
    if max_lines is None:
        raise DatasetError("%s 缺少 max_lines" % where)
    values["max_lines"] = max_lines
    if values["box_w"] - 2 * values["padding"] <= 0 or values["box_h"] - 2 * values["padding"] <= 0:
        raise DatasetError("%s 的文本盒减去内边距后没有可用空间" % where)
    return UiSpec(**values)


def _project_root() -> Path:
    return ROOT


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DatasetError("无法读取示例数据集 %s: %s" % (path.name, exc)) from exc
    except json.JSONDecodeError as exc:
        raise DatasetError("示例数据集 %s 不是合法 JSON: %s" % (path.name, exc)) from exc


def list_demos() -> List[Dict[str, str]]:
    """Return the demo catalogue shown in the UI."""
    catalogue = [
        {"name": "zh_ptbr", "label": "中 → 巴西葡语（主演示：占位符/溢出/语境缺口/修辞）"},
        {"name": "en_ptbr", "label": "英 → 巴西葡语（UI 多义词消歧）"},
        {"name": "zh_ru", "label": "中 → 俄语（复数与长文本溢出）"},
    ]
    available = []
    for item in catalogue:
        path = DATA_DIR / ("demo_%s.json" % item["name"])
        if path.exists():
            available.append(item)
    return available


def load_demo(name: str) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Load a demo payload and its optional UI profile.

    Returns (payload, None). The second value exists for symmetry with future
    external fixtures; it is intentionally unused today.
    """
    if not name or not all(c.isalnum() or c in "_-" for c in name):
        raise DatasetError("非法的示例名称")
    path = DATA_DIR / ("demo_%s.json" % name)
    if not path.exists():
        raise DatasetError("示例 %r 不存在" % name)
    data = _read_json(path)
    if not isinstance(data, dict):
        raise DatasetError("示例数据集必须是 JSON 对象")
    return data, None


def _normalise_payload(payload: Any, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if isinstance(payload, list):
        payload = {"strings": payload}
    if not isinstance(payload, dict):
        raise DatasetError("数据集必须是 JSON 对象或字符串数组")
    data = dict(payload)
    if "strings" not in data and "source" in data:
        # A single trans-unit object is accepted as a one-string dataset.
        data = {"strings": [data]}
    if "strings" not in data or not isinstance(data["strings"], list):
        raise DatasetError("数据集缺少 strings 数组")
    if not data["strings"]:
        raise DatasetError("strings 不能为空")
    if len(data["strings"]) > MAX_UNITS:
        raise DatasetError("单次最多分析 %d 条文本" % MAX_UNITS)
    if overrides:
        for key in ("project", "source_locale", "target_locale", "ui_profile"):
            if overrides.get(key):
                data[key] = overrides[key]
    data.setdefault("project", "未命名项目")
    data.setdefault("source_locale", "zh-CN")
    data.setdefault("target_locale", "pt-BR")
    data.setdefault("ui_profile", "mobile_dialog")
    data.setdefault("synthetic", True)
    data.setdefault("notice", "")
    return data


def build_dataset(payload: Any, overrides: Optional[Dict[str, Any]] = None) -> Dataset:
    data = _normalise_payload(payload, overrides)
    project = _as_text(data.get("project"), "project", "meta", required=True)
    source_locale = _as_text(data.get("source_locale"), "source_locale", "meta", required=True)
    target_locale = _as_text(data.get("target_locale"), "target_locale", "meta", required=True)
    ui_profile = _as_text(data.get("ui_profile"), "ui_profile", "meta", required=True)
    if ui_profile not in UI_PROFILES:
        raise DatasetError(
            "未知 UI profile %r；可用: %s" % (ui_profile, ", ".join(sorted(UI_PROFILES)))
        )
    notice = _as_text(data.get("notice"), "notice", "meta")
    synthetic = data.get("synthetic", True)
    if not isinstance(synthetic, bool):
        raise DatasetError("meta.synthetic 必须是布尔值")

    units: List[StringUnit] = []
    seen_ids = set()
    for index, raw in enumerate(data["strings"]):
        where = "strings[%d]" % index
        if not isinstance(raw, dict):
            raise DatasetError("%s 必须是对象" % where)
        unit_id = _as_text(raw.get("id"), "id", where, required=True).strip()
        if unit_id in seen_ids:
            raise DatasetError("%s 的 id %r 重复" % (where, unit_id))
        seen_ids.add(unit_id)
        source = _as_text(raw.get("source"), "source", where, required=True)
        target = _as_text(raw.get("target", ""), "target", where)
        key = _as_text(raw.get("key", ""), "key", where).strip()
        screen = _as_text(raw.get("screen", ""), "screen", where).strip()
        component = _as_text(raw.get("component", ""), "component", where).strip()
        neighbors = _parse_neighbors(raw.get("neighbors"), where)
        max_chars = _as_int(raw.get("max_chars"), "max_chars", where, minimum=1)
        ui_raw = raw.get("ui")
        if ui_raw is not None and not isinstance(ui_raw, dict):
            raise DatasetError("%s 的 ui 必须是对象" % where)
        ui_override = ui_raw or {}
        profile = ui_profile
        if ui_override.get("profile"):
            profile = _as_text(ui_override.get("profile"), "ui.profile", where)
        spec = _resolve_ui(profile, ui_override, where)
        units.append(
            StringUnit(
                id=unit_id,
                source=source,
                target=target,
                key=key,
                screen=screen,
                component=component,
                neighbors=neighbors,
                max_chars=max_chars,
                ui=spec,
                raw=raw,
            )
        )
    return Dataset(
        project=project,
        source_locale=source_locale,
        target_locale=target_locale,
        units=units,
        ui_profile=ui_profile,
        synthetic=synthetic,
        notice=notice,
    )


def _parse_jsonl(text: str) -> Dict[str, Any]:
    strings: List[Dict[str, Any]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetError("JSONL 第 %d 行不是合法 JSON: %s" % (lineno, exc)) from exc
        if not isinstance(item, dict):
            raise DatasetError("JSONL 第 %d 行必须是对象" % lineno)
        strings.append(item)
    return {"strings": strings}


def _parse_csv(text: str) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    data_lines: List[str] = []
    for line in text.splitlines():
        if line.startswith("#"):
            body = line[1:].strip()
            if "=" in body:
                name, value = body.split("=", 1)
                meta[name.strip()] = value.strip()
            continue
        data_lines.append(line)
    if not data_lines:
        raise DatasetError("CSV 内容为空")
    reader = csv.DictReader(io.StringIO("\n".join(data_lines)))
    if not reader.fieldnames or "source" not in reader.fieldnames:
        raise DatasetError("CSV 需要表头，且至少包含 source 列")
    strings: List[Dict[str, Any]] = []
    for row in reader:
        if not any((value or "").strip() for value in row.values()):
            continue
        item: Dict[str, Any] = {
            "id": (row.get("id") or "").strip(),
            "source": row.get("source") or "",
            "target": row.get("target") or "",
            "key": (row.get("key") or "").strip(),
            "screen": (row.get("screen") or "").strip(),
            "component": (row.get("component") or "").strip(),
            "neighbors": (row.get("neighbors") or "").strip(),
        }
        if not item["id"]:
            item["id"] = "row_%d" % (len(strings) + 1)
        for numeric in ("max_chars",):
            if (row.get(numeric) or "").strip():
                item[numeric] = (row.get(numeric) or "").strip()
        ui: Dict[str, Any] = {}
        for name in ("profile",) + UI_FIELDS:
            value = (row.get(name) or "").strip()
            if value:
                ui[name] = value
        if ui:
            item["ui"] = ui
        strings.append(item)
    if not strings:
        raise DatasetError("CSV 没有数据行")
    payload: Dict[str, Any] = {"strings": strings}
    for name in ("project", "source_locale", "target_locale", "ui_profile"):
        if meta.get(name):
            payload[name] = meta[name]
    if meta.get("synthetic"):
        payload["synthetic"] = meta["synthetic"].lower() in ("1", "true", "yes")
    return payload


def parse_text(text: str, fmt: str = "auto", overrides: Optional[Dict[str, Any]] = None) -> Dataset:
    """Parse JSON, JSONL or CSV text into a validated Dataset."""
    if not isinstance(text, str) or not text.strip():
        raise DatasetError("输入内容为空")
    if len(text) > 2_000_000:
        raise DatasetError("输入内容超过 2MB 上限")
    fmt = (fmt or "auto").lower()
    if fmt not in ("auto", "json", "jsonl", "csv", "xliff"):
        raise DatasetError("未知输入格式 %r（可选 auto/json/jsonl/csv/xliff）" % fmt)
    stripped = text.lstrip("\ufeff \t\r\n")
    payload: Any
    if fmt == "csv":
        payload = _parse_csv(stripped)
    elif fmt == "jsonl":
        payload = _parse_jsonl(stripped)
    elif fmt == "json":
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise DatasetError("JSON 解析失败: %s" % exc) from exc
    elif fmt == "xliff":
        try:
            payload = parse_xliff(stripped)
        except ValueError as exc:
            raise DatasetError(str(exc)) from exc
    else:
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                # JSONL also starts with "{"; try it before giving up on auto.
                if len([line for line in stripped.splitlines() if line.strip()]) > 1:
                    try:
                        payload = _parse_jsonl(stripped)
                    except DatasetError:
                        raise DatasetError("JSON 解析失败: %s" % exc) from exc
                else:
                    raise DatasetError("JSON 解析失败: %s" % exc) from exc
        elif stripped.startswith("<"):
            try:
                payload = parse_xliff(stripped)
            except ValueError as exc:
                raise DatasetError(str(exc)) from exc
        elif stripped.startswith("#") or (
            stripped.splitlines()
            and "," in stripped.splitlines()[0]
            and "source" in stripped.splitlines()[0]
        ):
            payload = _parse_csv(stripped)
        else:
            payload = _parse_jsonl(stripped)
    return build_dataset(payload, overrides)


def iter_lines(text: str) -> Iterable[str]:
    return text.splitlines()

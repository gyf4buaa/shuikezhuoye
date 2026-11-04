"""XLIFF 1.2 import/export for the batch flow.

CAT/TMS tools exchange XLIFF. This lightweight reader supports the common
``trans-unit`` structure plus the JSON context note this prototype writes.
Inline ``<g>``/``<ph>`` markup is flattened to text in v0.1 and called out as a
limitation; it is not silently treated as plain text without notice.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from .models import Dataset, Report

NAMESPACE = "urn:oasis:names:tc:xliff:document:1.2"
ET.register_namespace("", NAMESPACE)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _itertext(element: Optional[ET.Element]) -> str:
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def _find_text(parent: ET.Element, name: str) -> str:
    for child in parent:
        if _local(child.tag) == name:
            return _itertext(child)
    return ""


def _context_from_notes(trans_unit: ET.Element) -> Dict[str, Any]:
    context: Dict[str, Any] = {}
    for child in trans_unit:
        if _local(child.tag) == "note":
            source = (child.attrib.get("from") or "").lower()
            raw = _itertext(child)
            if source == "dsh-context" and raw:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        context.update(parsed)
                except json.JSONDecodeError:
                    context.setdefault("notes", []).append(raw)
            elif raw:
                context.setdefault("notes", []).append(raw)
        elif _local(child.tag) == "context-group":
            for item in child:
                if _local(item.tag) != "context":
                    continue
                ctype = (item.attrib.get("context-type") or "").strip()
                value = _itertext(item)
                if ctype and value:
                    context[ctype] = value
    return context


def parse_xliff(text: str) -> Dict[str, Any]:
    """Convert an XLIFF 1.2 document into the prototype's JSON payload."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError("XLIFF 解析失败: %s" % exc) from exc
    if _local(root.tag) != "xliff":
        raise ValueError("不是 XLIFF 文档（根元素为 %s）" % _local(root.tag))
    files = [el for el in root if _local(el.tag) == "file"]
    if not files:
        raise ValueError("XLIFF 缺少 <file> 元素")
    file_el = files[0]
    source_locale = file_el.attrib.get("source-language") or "zh-CN"
    target_locale = file_el.attrib.get("target-language") or "pt-BR"
    project = file_el.attrib.get("original") or "XLIFF 导入"
    units: List[Dict[str, Any]] = []
    flattened = False
    for index, trans_unit in enumerate(
        [el for el in file_el.iter() if _local(el.tag) == "trans-unit"], 1
    ):
        unit_id = (
            trans_unit.attrib.get("id")
            or trans_unit.attrib.get("resname")
            or "xliff_%d" % index
        )
        source_el = next(
            (el for el in trans_unit if _local(el.tag) == "source"), None
        )
        target_el = next(
            (el for el in trans_unit if _local(el.tag) == "target"), None
        )
        source = _itertext(source_el)
        target = _itertext(target_el)
        if (source_el is not None and len(source_el)) or (
            target_el is not None and len(target_el)
        ):
            flattened = True
        context = _context_from_notes(trans_unit)
        item: Dict[str, Any] = {
            "id": unit_id,
            "source": source,
            "target": target,
            "key": context.get("key", trans_unit.attrib.get("resname") or unit_id),
            "screen": context.get("screen", ""),
            "component": context.get("component", ""),
        }
        neighbors = context.get("neighbors")
        if isinstance(neighbors, str):
            item["neighbors"] = neighbors
        elif isinstance(neighbors, list):
            item["neighbors"] = neighbors
        if context.get("max_chars"):
            item["max_chars"] = context["max_chars"]
        if isinstance(context.get("ui"), dict):
            item["ui"] = context["ui"]
        units.append(item)
    if not units:
        raise ValueError("XLIFF 中没有 trans-unit")
    payload: Dict[str, Any] = {
        "project": project,
        "source_locale": source_locale,
        "target_locale": target_locale,
        "ui_profile": "mobile_dialog",
        "synthetic": True,
        "notice": "从 XLIFF 导入；内联标签在 v0.1 中被展平。" if flattened else "从 XLIFF 导入。",
        "strings": units,
    }
    return payload


def _note(parent: ET.Element, name: str, text: str) -> None:
    note = ET.SubElement(parent, "note")
    note.set("from", name)
    note.text = text


def build_xliff(dataset: Dataset, report: Optional[Report] = None) -> str:
    """Export the dataset (and optional findings) as XLIFF 1.2."""
    root = ET.Element("xliff")
    root.set("version", "1.2")
    file_el = ET.SubElement(root, "file")
    file_el.set("source-language", dataset.source_locale)
    file_el.set("target-language", dataset.target_locale)
    file_el.set("original", dataset.project)
    file_el.set("datatype", "plaintext")
    body = ET.SubElement(file_el, "body")
    report_by_id = {unit.id: unit for unit in report.units} if report else {}
    for unit in dataset.units:
        trans = ET.SubElement(body, "trans-unit")
        trans.set("id", unit.id)
        if unit.key:
            trans.set("resname", unit.key)
        source_el = ET.SubElement(trans, "source")
        source_el.text = unit.source
        target_el = ET.SubElement(trans, "target")
        target_el.text = unit.target
        context: Dict[str, Any] = {
            "key": unit.key,
            "screen": unit.screen,
            "component": unit.component,
            "neighbors": unit.neighbors,
        }
        if unit.max_chars is not None:
            context["max_chars"] = unit.max_chars
        context["ui"] = {
            "profile": unit.ui.profile,
            "font_size": unit.ui.font_size,
            "box_w": unit.ui.box_w,
            "box_h": unit.ui.box_h,
            "max_lines": unit.ui.max_lines,
            "line_height": unit.ui.line_height,
            "padding": unit.ui.padding,
            "letter_spacing": unit.ui.letter_spacing,
        }
        _note(trans, "dsh-context", json.dumps(context, ensure_ascii=False, sort_keys=True))
        result = report_by_id.get(unit.id)
        if result and result.issues:
            for issue in result.issues:
                _note(
                    trans,
                    "dsh-issue",
                    "[%s][%s] %s" % (issue.severity.upper(), issue.code, issue.message),
                )
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", xml_declaration=True)

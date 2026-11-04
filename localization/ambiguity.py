"""Source-context gap detection and register/idiom risk flags.

The tool must not invent missing context. These checks turn hidden questions
(subject, tense, reference, placeholder semantics) into explicit review items,
and keep confidence plus evidence next to every item.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import Issue, StringUnit
from .placeholders import infer_placeholder_semantics

ROOT = Path(__file__).resolve().parent.parent
IDIOM_PATH = ROOT / "data" / "idioms.json"

PRONOUNS = ("你", "您", "我", "他", "她", "它", "玩家", "英雄", "角色", "队伍", "敌人", "系统")
STATE_VERBS = (
    "解锁",
    "开启",
    "关闭",
    "完成",
    "获得",
    "装备",
    "购买",
    "升级",
    "通关",
    "失败",
    "成功",
    "领取",
)
ASPECT_MARKERS = ("已", "已经", "刚刚", "正在", "将", "将要", "即将", "会", "了", "过", "可", "可以")
DEMONSTRATIVES = ("这个", "那个", "该", "此", "其")
REFERENCE_PRONOUNS = ("它", "他", "她")

SUBJECT_PATTERNS = [
    # 点击确认后，将进入下一关
    re.compile(
        r"(?:点击|选择|进入|前往|返回|获得|领取|解锁|装备|使用|购买|升级|开启|关闭)"
        r"[^。！？]{0,16}[，,]\s*(?:将|会|即可|就能|可以|可)(?P<clause>[^，。！？]{1,20})"
    ),
    re.compile(r"(?:^|[，,；;])\s*(?:将|会)(?P<clause>[\u4e00-\u9fff]{2,16})"),
]


def _load_idioms() -> List[Dict[str, Any]]:
    if not IDIOM_PATH.exists():  # pragma: no cover - packaging guard
        return []
    try:
        data = json.loads(IDIOM_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - defensive
        raise RuntimeError("data/idioms.json 无法读取: %s" % exc) from exc
    return data.get("entries", [])


IDIOMS = _load_idioms()


def _is_supported_source(locale: str) -> bool:
    return locale.lower().startswith("zh")


def _contains_actor(text: str) -> bool:
    return any(pronoun in text for pronoun in PRONOUNS)


def _gap(
    code: str,
    gap_type: str,
    severity: str,
    message: str,
    question: str,
    evidence: List[str],
    confidence: str,
) -> Dict[str, Any]:
    return {
        "code": code,
        "type": gap_type,
        "severity": severity,
        "message": message,
        "question": question,
        "evidence": evidence,
        "confidence": confidence,
    }


def _gap_issue(unit: StringUnit, gap: Dict[str, Any]) -> Issue:
    return Issue(
        code=gap["code"],
        severity=gap["severity"],
        category="source_context",
        message=gap["message"],
        unit_id=unit.id,
        evidence=gap["evidence"],
        suggestion=gap["question"],
        extra={"gap_type": gap["type"], "confidence": gap["confidence"]},
    )


def detect_source_gaps(unit: StringUnit, source_locale: str) -> Tuple[List[Issue], List[Dict[str, Any]]]:
    """Return (issues, findings). Non-Chinese sources return an empty result."""
    source = unit.source.strip()
    if not source or not _is_supported_source(source_locale):
        return [], []
    findings: List[Dict[str, Any]] = []

    # 1) Subject omitted across a clause boundary.
    for pattern in SUBJECT_PATTERNS:
        match = pattern.search(source)
        if not match:
            continue
        clause = match.group("clause")
        prefix = source[: match.start("clause")]
        if _contains_actor(prefix) or _contains_actor(clause):
            continue
        findings.append(
            _gap(
                "SRC001",
                "subject",
                "warning",
                "动作主体未在源文出现：“%s”" % clause,
                "“%s”的主语是谁/什么（玩家、角色、队伍、系统）？请补充后再翻译。" % clause,
                ["源文: " + source, "命中片段: " + match.group(0)],
                "medium",
            )
        )
        break

    # 2) Tense / state ambiguity in short status labels.
    compact = re.sub(r"\s+", "", source)
    if (
        len(compact) <= 8
        and unit.component != "button"
        and any(compact.startswith(v) or compact == v for v in STATE_VERBS)
    ):
        if not any(marker in compact for marker in ASPECT_MARKERS):
            findings.append(
                _gap(
                    "SRC002",
                    "tense",
                    "info",
                    "状态/时态不明确：“%s”" % source,
                    "“%s”表示已发生、可执行，还是即将发生？请补充时态或状态。" % source,
                    ["源文: " + source, "未出现“已/将/正在/了/过/可”等时体标记"],
                    "medium",
                )
            )

    # 3) Demonstratives / pronouns whose referent lives in another string.
    demonstrative = next((d for d in DEMONSTRATIVES if d in source), None)
    pronoun = next((p for p in REFERENCE_PRONOUNS if p in source), None)
    if demonstrative and not pronoun:
        findings.append(
            _gap(
                "SRC003",
                "reference",
                "info",
                "指代对象可能不在本句：“%s”" % demonstrative,
                "“%s”具体指哪个对象/界面元素？请提供上一句或界面上下文。" % demonstrative,
                ["源文: " + source],
                "low",
            )
        )
    elif pronoun:
        findings.append(
            _gap(
                "SRC004",
                "reference",
                "warning",
                "代词“%s”的先行词不在本条文本中" % pronoun,
                "“%s”指代哪个名词？性别/单复数会影响目标语一致性，请补充先行词。" % pronoun,
                ["源文: " + source],
                "high",
            )
        )

    # 4) Placeholder semantics that the surrounding text cannot establish.
    semantics = infer_placeholder_semantics(source)
    for item in semantics:
        if item["inferred"] == "unknown":
            findings.append(
                _gap(
                    "SRC005",
                    "placeholder_semantics",
                    "warning",
                    "占位符 %s 的语义无法从局部文本确认" % item["placeholder"],
                    "占位符 %s 代表数量、名称、日期还是地点？请补充变量类型；工具不会猜测语法。" % item["placeholder"],
                    ["源文: " + source] + item["evidence"],
                    "high",
                )
            )
        elif item["confidence"] == "low":
            findings.append(
                _gap(
                    "SRC006",
                    "placeholder_semantics",
                    "info",
                    "占位符 %s 的语义仅为低置信推测（%s）" % (item["placeholder"], item["inferred"]),
                    "请确认占位符 %s 是否确实表示“%s”；确认后才能讨论目标语语法一致性。" % (item["placeholder"], item["inferred"]),
                    ["源文: " + source] + item["evidence"],
                    "low",
                )
            )

    issues = [_gap_issue(unit, gap) for gap in findings]
    return issues, findings


def detect_register_risks(unit: StringUnit) -> Tuple[List[Issue], List[Dict[str, Any]]]:
    """Detect idioms/sarcasm/marketing language that needs a strategy."""
    text = unit.source
    lowered = text.lower()
    findings: List[Dict[str, Any]] = []
    for entry in IDIOMS:
        pattern = entry.get("pattern", "")
        if not pattern:
            continue
        matched = pattern.lower() in lowered if entry.get("case_insensitive") else pattern in text
        if not matched:
            continue
        findings.append(
            {
                "code": "REG001",
                "type": entry.get("type", "idiom"),
                "pattern": pattern,
                "strategy": entry.get("strategy", "人工判断"),
                "note": entry.get("note", ""),
                "severity": "warning",
                "confidence": "medium",
                "question": "“%s”不能按字面直译；请确认采用%s，或交由母语译者处理。"
                % (pattern, entry.get("strategy", "改写")),
            }
        )
    issues = [
        Issue(
            code="REG001",
            severity="warning",
            category="register",
            message="修辞/语气风险（%s）：“%s”" % (finding["type"], finding["pattern"]),
            unit_id=unit.id,
            evidence=["源文: " + unit.source, finding["note"]],
            suggestion=finding["question"],
            extra={"strategy": finding["strategy"], "type": finding["type"]},
        )
        for finding in findings
    ]
    return issues, findings

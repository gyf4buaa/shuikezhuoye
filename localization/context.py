"""UI-context term disambiguation with explicit evidence.

A term like ``Setting`` / ``Rank`` / ``Claim`` / ``March`` cannot be
translated from the isolated string. This module uses the context a game
project usually already has (string key, screen, component, neighbouring UI
labels, co-text) to score known senses. It refuses to resolve when the
evidence is too thin, and it flags a target translation that matches the
wrong sense.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .models import Issue, StringUnit

ROOT = Path(__file__).resolve().parent.parent
KB_PATH = ROOT / "data" / "polysemy.json"
CJK_RE = re.compile(r"[\u3400-\u9fff]")
TOKEN_RE = re.compile(r"[^._\-/\s]+")

RESOLVED_SCORE = 4
RESOLVED_MARGIN = 2
INFERRED_SCORE = 3
INFERRED_MARGIN = 1


def normalize(text: str) -> str:
    """Lowercase and strip Latin diacritics, keeping Cyrillic/CJK letters.

    NFKD on the whole string would decompose Cyrillic ``й`` into ``и`` plus a
    combining breve and silently change the word; only Latin-range characters
    are decomposed here.
    """
    if not text:
        return ""
    lowered = unicodedata.normalize("NFC", text).casefold()
    pieces = []
    for ch in lowered:
        if ord(ch) < 0x0250:  # Latin / IPA range
            decomposed = unicodedata.normalize("NFKD", ch)
            pieces.append("".join(part for part in decomposed if not unicodedata.combining(part)))
        else:
            pieces.append(ch)
    cleaned = re.sub(r"[^\w\u3400-\u9fff]+", " ", "".join(pieces), flags=re.UNICODE)
    return " ".join(cleaned.split())


def _load_kb() -> List[Dict[str, Any]]:
    if not KB_PATH.exists():  # pragma: no cover - packaging guard
        return []
    try:
        data = json.loads(KB_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - defensive
        raise RuntimeError("data/polysemy.json 无法读取: %s" % exc) from exc
    return data.get("terms", [])


TERMS: List[Dict[str, Any]] = _load_kb()


def _alias_matches(alias: str, source_norm: str) -> bool:
    alias_norm = normalize(alias)
    if not alias_norm:
        return False
    if CJK_RE.search(alias_norm):
        return alias_norm in source_norm
    pattern = r"(?<![a-z0-9])" + re.escape(alias_norm) + r"(?![a-z0-9])"
    return re.search(pattern, source_norm) is not None


def match_term(source: str) -> Optional[Tuple[Dict[str, Any], str]]:
    """Return the longest matching (term, alias), if any."""
    source_norm = normalize(source)
    candidates: List[Tuple[int, Dict[str, Any], str]] = []
    for term in TERMS:
        for alias in term.get("aliases", []):
            if _alias_matches(alias, source_norm):
                candidates.append((len(alias), term, alias))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[2]))
    return candidates[0][1], candidates[0][2]


def _key_tokens(key: str) -> List[str]:
    return [t for t in TOKEN_RE.findall(normalize(key)) if t]


def _list_matches(value: str, candidates: Sequence[str]) -> bool:
    value_norm = normalize(value)
    if not value_norm:
        return False
    for candidate in candidates:
        cand = normalize(candidate)
        if not cand:
            continue
        if CJK_RE.search(cand):
            if cand in value_norm:
                return True
        elif cand == value_norm or cand in value_norm.split():
            return True
    return False


def _score_sense(
    unit: StringUnit, source: str, matched_alias: str, sense: Dict[str, Any]
) -> Tuple[int, List[Dict[str, Any]]]:
    score = 0
    evidence: List[Dict[str, Any]] = []
    bias = sense.get("alias_bias", {}) or {}
    if matched_alias in bias:
        weight = int(bias[matched_alias])
        score += weight
        evidence.append(
            {"type": "alias", "value": matched_alias, "weight": weight, "label": "词形倾向"}
        )

    key_tokens = set(_key_tokens(unit.key))
    if key_tokens:
        key_hits = [word for word in sense.get("keys", []) if normalize(word) in key_tokens]
        if key_hits:
            weight = min(6, 3 * len(key_hits))
            score += weight
            evidence.append(
                {
                    "type": "key",
                    "value": unit.key,
                    "weight": weight,
                    "label": "字符串 key 命中: %s" % ", ".join(key_hits),
                }
            )

    if unit.screen and _list_matches(unit.screen, sense.get("screens", [])):
        score += 2
        evidence.append(
            {"type": "screen", "value": unit.screen, "weight": 2, "label": "界面与义项一致"}
        )

    if unit.component and normalize(unit.component) in {
        normalize(c) for c in sense.get("components", [])
    }:
        score += 1
        evidence.append(
            {"type": "component", "value": unit.component, "weight": 1, "label": "控件类型一致"}
        )

    neighbor_hits = [
        n for n in unit.neighbors if _list_matches(n, sense.get("neighbors", []))
    ]
    if neighbor_hits:
        weight = min(4, len(neighbor_hits))
        score += weight
        evidence.append(
            {
                "type": "neighbors",
                "value": ", ".join(neighbor_hits),
                "weight": weight,
                "label": "相邻 UI 文案命中",
            }
        )

    source_norm = normalize(source)
    cotext_hits = []
    for phrase in sense.get("cotext", []):
        phrase_norm = normalize(phrase)
        if not phrase_norm or phrase_norm == normalize(matched_alias):
            continue
        if phrase_norm in source_norm:
            cotext_hits.append(phrase)
    if cotext_hits:
        weight = min(4, 2 * len(cotext_hits))
        score += weight
        evidence.append(
            {
                "type": "cotext",
                "value": ", ".join(cotext_hits),
                "weight": weight,
                "label": "源文共现词命中",
            }
        )
    return score, evidence


def _translation_for(sense: Dict[str, Any], locale: str) -> Tuple[str, bool]:
    translations = sense.get("translations", {}) or {}
    if locale in translations:
        return translations[locale], True
    base = locale.split("-")[0]
    for key, value in translations.items():
        if key.split("-")[0] == base:
            return value, True
    return translations.get("en-US", ""), False


def _translation_present(target_norm: str, expected: str) -> bool:
    expected_norm = normalize(expected)
    if not expected_norm:
        return False
    if expected_norm in target_norm:
        return True
    # Inflected forms (Russian/German/Portuguese) keep a stable prefix.
    if len(expected_norm) >= 6:
        stem = expected_norm[: max(4, len(expected_norm) - 2)]
        if stem in target_norm:
            return True
    return False


def resolve(unit: StringUnit, locale: str) -> Optional[Dict[str, Any]]:
    matched = match_term(unit.source)
    if not matched:
        return None
    term, alias = matched
    scored = []
    for sense in term.get("senses", []):
        score, evidence = _score_sense(unit, unit.source, alias, sense)
        translation, translated = _translation_for(sense, locale)
        scored.append(
            {
                "id": sense["id"],
                "label": sense["label"],
                "score": score,
                "evidence": evidence,
                "translation": translation,
                "translation_available": translated,
            }
        )
    scored.sort(key=lambda item: (-item["score"], item["id"]))
    top = scored[0]
    second = scored[1] if len(scored) > 1 else {"score": 0}
    margin = top["score"] - second["score"]
    total = sum(item["score"] for item in scored)
    if top["score"] >= RESOLVED_SCORE and margin >= RESOLVED_MARGIN:
        status = "resolved"
    elif top["score"] >= INFERRED_SCORE and margin >= INFERRED_MARGIN:
        status = "inferred"
    else:
        status = "insufficient"
    confidence = round(top["score"] / total, 2) if total else 0.0
    result: Dict[str, Any] = {
        "term": term.get("term", alias),
        "matched_alias": alias,
        "status": status,
        "confidence": confidence,
        "selected": top if status != "insufficient" else None,
        "alternatives": [
            {
                "id": item["id"],
                "label": item["label"],
                "score": item["score"],
                "translation": item["translation"],
            }
            for item in scored[:3]
        ],
        "scores": {item["id"]: item["score"] for item in scored},
        "evidence": top["evidence"],
        "locale": locale,
        "method": "策展义项库 + 现有 key/界面/组件/相邻文案的加权证据；不是语义理解，证据不足时弃答",
    }
    if status == "insufficient":
        result["reason"] = "现有 key/界面/组件/相邻文案不足以唯一确定义项"
        result["question"] = (
            "“%s”在界面中表示哪个义项？候选: %s。请补充 screen、相邻文案或人工指定。"
            % (
                alias,
                "；".join("%s(%d分)" % (item["label"], item["score"]) for item in scored),
            )
        )
        return result

    target_norm = normalize(unit.target)
    expected = top["translation"]
    result["target_check"] = {
        "expected": expected,
        "expected_present": False,
        "conflict_with": None,
    }
    if unit.target.strip():
        present = _translation_present(target_norm, expected)
        result["target_check"]["expected_present"] = present
        if not present:
            for other in scored:
                if other["id"] == top["id"] or not other["translation"]:
                    continue
                if _translation_present(target_norm, other["translation"]):
                    result["target_check"]["conflict_with"] = {
                        "id": other["id"],
                        "label": other["label"],
                        "translation": other["translation"],
                    }
                    break
    return result


def context_issues(unit: StringUnit, resolution: Optional[Dict[str, Any]]) -> List[Issue]:
    if not resolution:
        return []
    issues: List[Issue] = []
    if resolution["status"] == "insufficient":
        issues.append(
            Issue(
                code="CTX001",
                severity="warning",
                category="context",
                message="无法消歧: “%s”的义项证据不足" % resolution["matched_alias"],
                unit_id=unit.id,
                evidence=[e["label"] + ": " + e["value"] for e in resolution["evidence"]]
                or ["没有命中任何 key/界面/组件/相邻文案"],
                suggestion=resolution["question"],
                extra={"alternatives": resolution["alternatives"]},
            )
        )
        return issues

    selected = resolution["selected"]
    check = resolution.get("target_check") or {}
    selected_label = "%s（%s）" % (selected["label"], selected["translation"])
    if check.get("expected_present"):
        return issues
    if check.get("conflict_with"):
        conflict = check["conflict_with"]
        issues.append(
            Issue(
                code="CTX002",
                severity="error",
                category="context",
                message="译名与 UI 上下文冲突: 应为“%s”，译文却用了“%s”" % (selected["translation"], conflict["translation"]),
                unit_id=unit.id,
                evidence=[
                    "上下文判定义项: " + selected_label,
                    "冲突义项: %s（%s）" % (conflict["label"], conflict["translation"]),
                    "译文: " + unit.target,
                ],
                suggestion="按当前 UI 上下文改用“%s”，并同步术语表。" % selected["translation"],
                extra={"selected": selected, "conflict": conflict},
            )
        )
    elif unit.target.strip():
        issues.append(
            Issue(
                code="CTX003",
                severity="warning",
                category="context",
                message="译文中未找到该义项的建议译名“%s”" % selected["translation"],
                unit_id=unit.id,
                evidence=[
                    "上下文判定义项: " + selected_label,
                    "译文: " + unit.target,
                ],
                suggestion="若使用了变格/缩写/同义表达，请在术语表登记变体；否则请核对义项。",
                extra={"selected": selected},
            )
        )
    return issues

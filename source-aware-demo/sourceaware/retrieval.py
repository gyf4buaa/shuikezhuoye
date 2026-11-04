"""Read-only retrieval of real code references for a source string.

Everything returned here is derived from files under ``demo_project`` at
request time: paths, 1-based line numbers, code snippets and the identifiers
that triggered a heuristic. There is no per-key canned explanation and no
model involvement. The heuristics are deliberately labelled as inference, not
as ground truth.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .catalog import Catalog

CODE_SUFFIXES = {".cs"}
TABLE_SUFFIXES = {".json", ".csv"}
ALLOWED_SUFFIXES = CODE_SUFFIXES | TABLE_SUFFIXES
MAX_FILE_BYTES = 256 * 1024
MAX_RESULTS = 40
MAX_LINE_CHARS = 600
SNIPPET_RADIUS = 2

QUOTED_STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
CLASS_RE = re.compile(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)")
CONTROL_KEYWORDS = ("if", "for", "foreach", "while", "switch", "catch", "using", "lock", "return", "new")
METHOD_RE = re.compile(
    r"^(?!(?:" + "|".join(CONTROL_KEYWORDS) + r")\b)"
    r"(?:(?:public|private|protected|internal|static|sealed|async|virtual|override|partial|extern|unsafe|new)\s+)*"
    r"(?:[A-Za-z_][A-Za-z0-9_<>\[\],\.\?]*\s+)?"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*\([^;{}]*\)\s*$"
)

# Deterministic inference vocabulary. The tokens are intentionally UI-oriented;
# matches are reported with the actual identifier/word that triggered them.
CATEGORY_RULES: List[Tuple[str, str, Tuple[str, ...]]] = [
    (
        "interaction",
        "按钮/交互语境",
        ("button", "onclick", "addlistener", "interactable", "click", "toggle"),
    ),
    (
        "table",
        "列表/表头语境",
        ("column", "header", "row", "table", "leaderboard", "ladder", "sort"),
    ),
    (
        "identity",
        "等级/身份展示语境",
        ("badge", "profile", "career", "military", "fleet", "tier", "capacity"),
    ),
    (
        "fallback",
        "回退/硬编码文案语境",
        ("fallback", "isnullorempty", "editor", "preview", "hardcode", "todo"),
    ),
    (
        "label",
        "文本展示语境",
        ("title", "label", "text"),
    ),
]


@dataclass
class Evidence:
    path: str
    line: int
    column: int
    kind: str
    direct: bool
    match_kinds: List[str]
    matched_text: str
    symbol: Dict[str, str]
    snippet: List[Dict[str, object]]
    inference: Dict[str, object]
    id: str = ""

    def public(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "kind": self.kind,
            "direct": self.direct,
            "match_kinds": list(self.match_kinds),
            "matched_text": self.matched_text,
            "symbol": dict(self.symbol),
            "snippet": [dict(item) for item in self.snippet],
            "inference": dict(self.inference),
        }


def _code_only(line: str) -> str:
    """Approximate C# code without string literals or trailing line comments."""
    without_strings = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)
    return without_strings.split("//", 1)[0]


def _brace_depths(lines: Sequence[str]) -> List[int]:
    depths: List[int] = []
    depth = 0
    for line in lines:
        code = _code_only(line)
        depth += code.count("{") - code.count("}")
        depths.append(depth)
    return depths


def _next_open_line(lines: Sequence[str], start: int) -> Optional[int]:
    for index in range(start, min(len(lines), start + 4)):
        stripped = _code_only(lines[index]).strip()
        if not stripped:
            continue
        return index if stripped.startswith("{") else None
    return None


def _symbol_for(lines: Sequence[str], target: int) -> Dict[str, str]:
    """Find the innermost class/method scope containing ``target`` (0-based).

    This is a small brace-aware heuristic, not a C# parser. It is used only to
    label where a snippet lives, and the UI says so explicitly.
    """
    depths = _brace_depths(lines)
    scopes: List[Tuple[int, int, str, str]] = []  # open, close, class, member

    class_scopes: List[Tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = CLASS_RE.search(_code_only(line))
        if not match:
            continue
        open_line = index if "{" in _code_only(line) else _next_open_line(lines, index + 1)
        if open_line is None or open_line >= len(lines):
            continue
        close_line = len(lines) - 1
        for probe in range(open_line + 1, len(lines)):
            if depths[probe] < depths[open_line]:
                close_line = probe
                break
        class_scopes.append((open_line, close_line, match.group(1)))

    for open_line, close_line, class_name in class_scopes:
        if not (open_line <= target <= close_line):
            continue
        scopes.append((open_line, close_line, class_name, class_name))
        for index in range(open_line + 1, close_line + 1):
            stripped = _code_only(lines[index]).strip()
            match = METHOD_RE.match(stripped)
            if not match:
                continue
            method_open = index if "{" in _code_only(lines[index]) else _next_open_line(lines, index + 1)
            if method_open is None or method_open > close_line:
                continue
            method_close = close_line
            for probe in range(method_open + 1, close_line + 1):
                if depths[probe] < depths[method_open]:
                    method_close = probe
                    break
            if method_open <= target <= method_close:
                scopes.append((method_open, method_close, class_name, match.group(1)))

    if not scopes:
        return {}
    open_line, close_line, class_name, member = min(
        scopes, key=lambda item: (item[1] - item[0], item[0])
    )
    result: Dict[str, str] = {"class": class_name}
    if member != class_name:
        result["member"] = member
    return result


def _decode_quoted(raw: str) -> str:
    return re.sub(r'\\(["\\])', r"\1", raw)


def _quoted_values(line: str) -> List[Tuple[str, int]]:
    values: List[Tuple[str, int]] = []
    for match in QUOTED_STRING_RE.finditer(line):
        values.append((_decode_quoted(match.group(1)), match.start(1)))
    return values


def _key_pattern(key: str) -> re.Pattern:
    # Do not match a longer key such as ui.reward.claim_all when looking for
    # ui.reward.claim.
    return re.compile(r"(?<![\w.])" + re.escape(key) + r"(?![\w.])")


def _snippet(lines: Sequence[str], target: int) -> List[Dict[str, object]]:
    start = max(0, target - SNIPPET_RADIUS)
    end = min(len(lines), target + SNIPPET_RADIUS + 1)
    result: List[Dict[str, object]] = []
    for index in range(start, end):
        raw = lines[index].rstrip("\n")
        clipped = raw[:MAX_LINE_CHARS]
        result.append(
            {
                "line": index + 1,
                "text": clipped,
                "match": index == target,
                "truncated": len(raw) > MAX_LINE_CHARS,
            }
        )
    return result


def _collect_tokens(texts: Iterable[str]) -> List[str]:
    seen = set()
    tokens: List[str] = []
    for text in texts:
        for token in IDENTIFIER_RE.findall(text):
            lowered = token.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            tokens.append(token)
    return tokens


def _infer(
    relative_path: str,
    target_line: str,
    context_lines: Sequence[str],
    direct: bool,
    kind: str,
    symbol: Dict[str, str],
) -> Dict[str, object]:
    if kind == "string-table":
        if direct:
            summary = "字符串表定义：确认所选 Key 与源文本，不提供界面语境。"
        else:
            summary = "字符串表定义（同文本候选，可能属于其他 Key）：只确认文本出现，不提供界面语境。"
        return {
            "summary": summary,
            "categories": [],
            "signals": [],
            "confidence": "none",
            "needs_human": True,
            "policy": "deterministic-heuristics",
        }

    line_tokens = _collect_tokens([target_line])
    context_tokens = _collect_tokens(context_lines)
    line_lower = {token.lower() for token in line_tokens}

    scored: List[Tuple[int, int, str, str, List[str]]] = []
    for order, (category_id, label, keywords) in enumerate(CATEGORY_RULES):
        score = 0
        matched: List[str] = []
        for token in line_tokens:
            lowered = token.lower()
            if any(keyword in lowered for keyword in keywords):
                score += 2
                matched.append(token)
        for token in context_tokens:
            if token.lower() in line_lower:
                continue
            lowered = token.lower()
            if any(keyword in lowered for keyword in keywords):
                score += 1
                matched.append(token)
        if score:
            deduped: List[str] = []
            seen = set()
            for token in matched:
                if token.lower() in seen:
                    continue
                seen.add(token.lower())
                deduped.append(token)
            scored.append((score, -order, category_id, label, deduped))
    scored.sort(reverse=True)

    if not scored:
        return {
            "summary": "证据不足以判断具体语义；需要人工确认。",
            "categories": [],
            "signals": [],
            "confidence": "low",
            "needs_human": True,
            "policy": "deterministic-heuristics",
        }

    top = scored[0][0]
    top_categories = [item for item in scored if item[0] >= max(1, top - 1)][:2]
    labels = [item[3] for item in top_categories]
    signals: List[str] = []
    seen_signals = set()
    for item in top_categories:
        for token in item[4]:
            if token.lower() in seen_signals:
                continue
            seen_signals.add(token.lower())
            signals.append(token)
    signals = signals[:6]

    if direct:
        confidence = "high" if top >= 3 else "medium"
        prefix = "直接引用该 Key"
    else:
        confidence = "low"
        prefix = "同文本候选（该行未引用所选 Key，可能属于其他 Key）"
    if not direct:
        confidence = "low"

    location = relative_path
    if symbol.get("class") and symbol.get("member"):
        location = "%s.%s" % (symbol["class"], symbol["member"])
    elif symbol.get("class"):
        location = symbol["class"]
    basis = "、".join(signals) if signals else "无明确界面词元"
    summary = "在 %s 中，%s；%s（依据：%s）。" % (
        location,
        prefix,
        "、".join(labels),
        basis,
    )
    return {
        "summary": summary,
        "categories": labels,
        "signals": signals,
        "confidence": confidence,
        "needs_human": (not direct) or top == 0,
        "policy": "deterministic-heuristics",
    }


def _iter_project_files(root: Path) -> Iterable[Tuple[Path, str]]:
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(str(root), followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            if path.is_symlink():
                continue
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, ValueError):
                continue
            try:
                if resolved.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield resolved, path.relative_to(root).as_posix()


def _read_lines(path: Path) -> Optional[List[str]]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None


def search(catalog: Catalog, key: str) -> Dict[str, object]:
    started = time.time()
    record = catalog.get(key)
    key_re = _key_pattern(record.key)
    evidence: List[Evidence] = []
    files_scanned = 0
    lines_scanned = 0
    bytes_scanned = 0

    for path, relative_path in _iter_project_files(catalog.project_root):
        lines = _read_lines(path)
        if lines is None:
            continue
        files_scanned += 1
        lines_scanned += len(lines)
        try:
            bytes_scanned += path.stat().st_size
        except OSError:
            pass
        is_code = path.suffix.lower() in CODE_SUFFIXES
        for index, line in enumerate(lines):
            key_match = key_re.search(line)
            literal_matches = [
                (value, column)
                for value, column in _quoted_values(line)
                if value == record.source
            ]
            if not key_match and not literal_matches:
                continue
            match_kinds: List[str] = []
            if key_match:
                match_kinds.append("key")
            if literal_matches:
                match_kinds.append("literal")
            direct = bool(key_match)
            if is_code:
                kind = "code-key" if key_match else "code-literal"
            else:
                kind = "string-table"
            column = key_match.start() + 1 if key_match else literal_matches[0][1] + 1
            target_line = line.rstrip("\n")
            snippet = _snippet(lines, index)
            context_lines = [item["text"] for item in snippet if not item["match"]]
            symbol = _symbol_for(lines, index) if is_code else {}
            inference = _infer(
                relative_path,
                target_line,
                context_lines,
                direct=direct,
                kind=kind,
                symbol=symbol,
            )
            evidence.append(
                Evidence(
                    path=relative_path,
                    line=index + 1,
                    column=column,
                    kind=kind,
                    direct=direct,
                    match_kinds=match_kinds,
                    matched_text=target_line[:MAX_LINE_CHARS],
                    symbol=symbol,
                    snippet=snippet,
                    inference=inference,
                )
            )

    order = {
        "code-key": 0,
        "code-literal": 1,
        "string-table": 2,
    }
    evidence.sort(key=lambda item: (order.get(item.kind, 9), item.path, item.line))
    truncated = len(evidence) > MAX_RESULTS
    evidence = evidence[:MAX_RESULTS]
    for index, item in enumerate(evidence, start=1):
        item.id = "ev-%02d" % index

    counts = {
        "total": len(evidence),
        "code_key": sum(1 for item in evidence if item.kind == "code-key"),
        "code_literal": sum(1 for item in evidence if item.kind == "code-literal"),
        "string_table": sum(1 for item in evidence if item.kind == "string-table"),
    }
    found = bool(evidence)
    note = ""
    if not found:
        note = "未在演示工程中找到该 Key 或源文本的引用；不会编造证据。"
    elif counts["code_key"] == 0 and counts["code_literal"] == 0:
        note = "只找到字符串表定义，没有找到代码引用。"
    elif counts["code_key"] == 0:
        note = "没有找到该 Key 的直接代码引用，仅有同文本候选；候选可能属于其他 Key。"
    elif counts["code_literal"]:
        note = "另有 %d 条同文本候选未直接引用所选 Key，可能属于其他 Key。" % counts["code_literal"]

    result: Dict[str, object] = {
        "status": "ok",
        "synthetic": True,
        "project": {
            "name": catalog.project_name,
            "root": "demo_project",
        },
        "key": record.key,
        "source": record.source,
        "shared_with": list(record.shared_with),
        "table": {"path": record.table, "line": record.line},
        "found": found,
        "note": note,
        "counts": counts,
        "has_direct_code_reference": counts["code_key"] > 0,
        "has_code_references": (counts["code_key"] + counts["code_literal"]) > 0,
        "truncated": truncated,
        "evidence": [item.public() for item in evidence],
        "scope": {
            "root": "demo_project",
            "directories": ["Assets/Scripts", "Assets/Localization"],
            "files_scanned": files_scanned,
            "lines_scanned": lines_scanned,
            "bytes_scanned": bytes_scanned,
            "max_results": MAX_RESULTS,
            "read_only": True,
        },
        "elapsed_ms": int((time.time() - started) * 1000),
    }
    return result

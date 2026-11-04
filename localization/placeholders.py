"""Placeholder, ICU plural and rich-text integrity checks.

The checks are deterministic: every finding carries the source/target token
that produced it. The module intentionally does not guess what an ambiguous
``{0}`` means; that belongs to :mod:`localization.ambiguity`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .models import Issue

# CLDR plural categories. We only *require* categories, never invent forms.
PLURAL_CATEGORIES: Dict[str, List[str]] = {
    "en": ["one", "other"],
    "pt": ["one", "other"],
    "es": ["one", "other"],
    "de": ["one", "other"],
    "fr": ["one", "other"],
    "ru": ["one", "few", "many", "other"],
    "pl": ["one", "few", "many", "other"],
    "ar": ["zero", "one", "two", "few", "many", "other"],
}

PRINTF_TYPES = set("sdifuxXeE")
NAME_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.]*|\d+)$")
PRINTF_RE = re.compile(r"%(?:(\d+)\$)?([-+ 0#]*)(\d+)?(?:\.(\d+))?([sdifuxXeE])")
TAG_RE = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9_-]*)([^<>]*?)(/?)>")
STRICT_TAG_RE = re.compile(r"^<([A-Za-z][A-Za-z0-9_-]*)(?:\s[^<>]*)?>$")

# Structural tags that do not need a closing partner.
VOID_TAGS = {"br", "hr", "img", "icon", "sprite"}


class PlaceholderSyntaxError(ValueError):
    def __init__(self, message: str, position: int):
        super().__init__(message)
        self.position = position


@dataclass
class Token:
    kind: str  # icu | printf | tag | escaped
    raw: str
    start: int
    end: int
    key: str = ""
    fmt: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def describe(self) -> str:
        return self.raw


def _match_brace(text: str, start: int) -> int:
    """Find the matching brace of ``text[start]``.

    Nested braces are counted by depth. Top-level ``{{``/``}}`` escapes are
    handled by :func:`tokenize` before this function is called, so that
    ``{count, plural, one {..}}`` (adjacent closing braces at different
    depths) is parsed correctly.
    """
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _split_branches(body: str, start: int) -> Tuple[List[Tuple[str, str]], int]:
    """Parse the ``one {..} other {..}`` part of an ICU plural."""
    branches: List[Tuple[str, str]] = []
    seen = set()
    i = 0
    while i < len(body):
        while i < len(body) and body[i] in " \t\r\n,":
            i += 1
        if i >= len(body):
            break
        if body[i] == "=":
            m = re.match(r"=(\d+)", body[i:])
            if not m:
                raise PlaceholderSyntaxError("ICU 复数分类 '%s' 非法" % body[i : i + 8], start + i)
            category = "=" + m.group(1)
            i += m.end()
        else:
            m = re.match(r"[A-Za-z_][A-Za-z0-9_-]*", body[i:])
            if not m:
                raise PlaceholderSyntaxError("ICU 复数分类非法: %r" % body[i : i + 12], start + i)
            category = m.group(0)
            i += m.end()
            if category not in ("zero", "one", "two", "few", "many", "other"):
                raise PlaceholderSyntaxError(
                    "未知 ICU 复数分类 %r（应为 zero/one/two/few/many/other 或 =N）" % category,
                    start + i,
                )
        if category in seen:
            raise PlaceholderSyntaxError("ICU 复数分类 %r 重复" % category, start + i)
        seen.add(category)
        while i < len(body) and body[i] in " \t\r\n":
            i += 1
        if i >= len(body) or body[i] != "{":
            raise PlaceholderSyntaxError("ICU 复数分类 %r 后缺少 { } 分支" % category, start + i)
        end = _match_brace(body, i)
        if end < 0:
            raise PlaceholderSyntaxError("ICU 复数分支缺少右花括号", start + i)
        branches.append((category, body[i + 1 : end]))
        i = end + 1
    return branches, i


def parse_icu(inner: str, raw: str, start: int) -> Token:
    head_match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_.]*|\d+)\s*([,:])?\s*(.*)$", inner, re.S)
    if not head_match:
        raise PlaceholderSyntaxError(
            "占位符内容 %r 非法；命名占位符只能包含字母、数字、下划线和点" % inner.strip(),
            start,
        )
    name = head_match.group(1)
    separator = head_match.group(2)
    rest = head_match.group(3).strip()
    if separator == ":":
        # .NET-style custom format, e.g. {0:N0} or {0:0.00}.
        token = Token(kind="icu", raw=raw, start=start, end=start + len(raw), key=name)
        token.fmt = "custom:" + rest
        token.meta["format_kind"] = "custom"
        return token
    token = Token(kind="icu", raw=raw, start=start, end=start + len(raw), key=name, fmt=rest)
    if not rest:
        return token
    head = rest.split(",", 1)[0].strip()
    if head in ("plural", "select", "selectordinal"):
        body = rest.split(",", 1)[1] if "," in rest else ""
        branches, consumed = _split_branches(body, start)
        remaining = body[consumed:].strip()
        if remaining:
            raise PlaceholderSyntaxError("ICU 复数尾部有无法解析的内容 %r" % remaining[:20], start)
        if not branches:
            raise PlaceholderSyntaxError("ICU %s 至少需要一个分支" % head, start)
        token.meta["branch_kind"] = head
        token.meta["branches"] = dict(branches)
        token.fmt = head + ":" + ",".join(name for name, _ in branches)
    else:
        # Number/date/time/custom format, e.g. {0, number, integer}.
        token.meta["format_kind"] = head
    return token


def tokenize(text: str) -> Tuple[List[Token], List[Dict[str, Any]]]:
    """Return placeholders/tags plus syntax problems found while scanning."""
    tokens: List[Token] = []
    problems: List[Dict[str, Any]] = []
    unindexed = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if text.startswith("{{", i) or text.startswith("}}", i):
            tokens.append(Token("escaped", text[i : i + 2], i, i + 2))
            i += 2
            continue
        if ch == "{":
            end = _match_brace(text, i)
            if end < 0:
                problems.append(
                    {"position": i, "raw": text[i : i + 20], "message": "花括号未闭合"}
                )
                i += 1
                continue
            inner = text[i + 1 : end]
            try:
                token = parse_icu(inner, text[i : end + 1], i)
            except PlaceholderSyntaxError as exc:
                problems.append({"position": i, "raw": text[i : end + 1], "message": str(exc)})
                i = end + 1
                continue
            tokens.append(token)
            i = end + 1
            continue
        if ch == "}":
            problems.append({"position": i, "raw": "}", "message": "多余的右花括号"})
            i += 1
            continue
        if ch == "%":
            m = PRINTF_RE.match(text, i)
            if m:
                index = int(m.group(1)) if m.group(1) else None
                token = Token(
                    kind="printf",
                    raw=m.group(0),
                    start=i,
                    end=m.end(),
                    fmt="".join(g for g in m.groups()[1:4] if g),
                    meta={"index": index, "type": m.group(5)},
                )
                if index is None:
                    token.key = "printf:seq%d" % unindexed
                    token.meta["seq"] = unindexed
                    unindexed += 1
                else:
                    token.key = "printf:arg%d" % index
                tokens.append(token)
                i = m.end()
                continue
            if text.startswith("%%", i):
                tokens.append(Token("escaped", "%%", i, i + 2))
                i += 2
                continue
            following = text[i + 1] if i + 1 < len(text) else ""
            if not following or not (following.isalnum() or following in "$-+ 0#."):
                # Literal percent in display text, e.g. "{0}%" or "100%".
                tokens.append(Token("percent", "%", i, i + 1))
            else:
                problems.append(
                    {"position": i, "raw": text[i : i + 6], "message": "% 后不是合法格式说明符"}
                )
            i += 1
            continue
        if ch == "<":
            m = TAG_RE.match(text, i)
            if m:
                closing, name, attrs, selfclose = m.group(1), m.group(2), m.group(3), m.group(4)
                raw = m.group(0)
                token = Token(
                    kind="tag",
                    raw=raw,
                    start=i,
                    end=m.end(),
                    key=name.lower(),
                    meta={
                        "closing": bool(closing),
                        "self_closing": bool(selfclose) or name.lower() in VOID_TAGS,
                        "attrs": attrs.strip(),
                    },
                )
                tokens.append(token)
                i = m.end()
                continue
            problems.append({"position": i, "raw": text[i : i + 12], "message": "< 后不是合法标签"})
            i += 1
            continue
        i += 1
    return tokens, problems


def _tag_balance(text: str) -> Tuple[List[str], List[str], List[str]]:
    """Return (unclosed, unexpected_closings, problems) for HTML-ish tags."""
    tokens, problems = tokenize(text)
    stack: List[str] = []
    unexpected: List[str] = []
    for token in tokens:
        if token.kind != "tag":
            continue
        if token.meta.get("self_closing"):
            continue
        if token.meta.get("closing"):
            if stack and stack[-1] == token.key:
                stack.pop()
            elif token.key in stack:
                # Mismatched nesting: <b><i></b></i>
                unexpected.append(token.raw)
            else:
                unexpected.append(token.raw)
        else:
            stack.append(token.key)
    return stack, unexpected, [p["message"] for p in problems]


def _icu_required_categories(token: Token, locale: str, unit_id: str = "") -> List[Issue]:
    issues: List[Issue] = []
    kind = token.meta.get("branch_kind")
    if not kind:
        return issues
    base = locale.split("-")[0].lower()
    if kind == "plural":
        required = PLURAL_CATEGORIES.get(base, ["other"])
    else:
        required = ["other"]
    branches = token.meta.get("branches", {})
    present = {name for name in branches if not name.startswith("=")}
    missing = [name for name in required if name not in present]
    if missing:
        issues.append(
            Issue(
                code="PH008",
                severity="error",
                category="template",
                message="ICU %s 模板缺少 %s 的 CLDR 必需分类: %s" % (kind, locale, ", ".join(missing)),
                unit_id=unit_id,
                evidence=[token.raw],
                suggestion="按 CLDR 补齐 %s 分类；缺失分类的模板在运行时无法正确选择复数形式。"
                % ", ".join(missing),
                extra={"missing_categories": missing, "present": sorted(present)},
            )
        )
    return issues


def _placeholder_keys(tokens: Sequence[Token]) -> List[str]:
    return [t.key for t in tokens if t.kind in ("icu", "printf")]


def _printf_types(tokens: Sequence[Token]) -> List[str]:
    return [t.meta.get("type", "") for t in tokens if t.kind == "printf"]


def _is_unindexed_printf(tokens: Sequence[Token]) -> bool:
    printf = [t for t in tokens if t.kind == "printf"]
    return bool(printf) and all(t.meta.get("index") is None for t in printf)


def _is_indexed_printf(tokens: Sequence[Token]) -> bool:
    printf = [t for t in tokens if t.kind == "printf"]
    return bool(printf) and all(t.meta.get("index") is not None for t in printf)


def _describe_keys(keys: Sequence[str]) -> str:
    return ", ".join(keys) if keys else "（无）"


def check_placeholders(
    source: str, target: str, locale: str, unit_id: str = ""
) -> Tuple[List[Issue], Dict[str, Any]]:
    """Validate placeholder/tag integrity between source and target."""
    issues: List[Issue] = []
    source_tokens, source_problems = tokenize(source)
    target_tokens, target_problems = tokenize(target)

    for problem in source_problems:
        issues.append(
            Issue(
                code="PH001",
                severity="error",
                category="placeholder",
                message="源文格式错误: %s" % problem["message"],
                unit_id=unit_id,
                evidence=[problem["raw"]],
                suggestion="源文本身必须能被运行时格式化；请先修复源文模板。",
                extra={"position": problem["position"], "side": "source"},
            )
        )
    for problem in target_problems:
        issues.append(
            Issue(
                code="PH001",
                severity="error",
                category="placeholder",
                message="译文格式错误: %s" % problem["message"],
                unit_id=unit_id,
                evidence=[problem["raw"]],
                suggestion="修正花括号/格式说明符，确保运行时格式化不会崩溃。",
                extra={"position": problem["position"], "side": "target"},
            )
        )

    source_keys = _placeholder_keys(source_tokens)
    target_keys = _placeholder_keys(target_tokens)
    source_set = set(source_keys)
    target_set = set(target_keys)

    # Safe reorder: unindexed printf in the source, positional printf in the
    # target, same argument types (translation may have moved the arguments).
    source_printf = [t for t in source_tokens if t.kind == "printf"]
    target_printf = [t for t in target_tokens if t.kind == "printf"]
    indexed_reorder = (
        source_printf
        and target_printf
        and _is_unindexed_printf(source_tokens)
        and _is_indexed_printf(target_tokens)
        and sorted(_printf_types(source_tokens)) == sorted(_printf_types(target_tokens))
        and len(source_printf) == len(target_printf)
    )

    if not indexed_reorder:
        missing = [k for k in source_keys if k not in target_set]
        extra = [k for k in target_keys if k not in source_set]
        if missing:
            issues.append(
                Issue(
                    code="PH002",
                    severity="error",
                    category="placeholder",
                    message="译文缺少占位符: %s" % _describe_keys(missing),
                    unit_id=unit_id,
                    evidence=["源文: %s" % _describe_keys(source_keys), "译文: %s" % _describe_keys(target_keys)],
                    suggestion="补回同名占位符，保持变量完整性。",
                    extra={"missing": missing},
                )
            )
        if extra:
            issues.append(
                Issue(
                    code="PH003",
                    severity="error",
                    category="placeholder",
                    message="译文多出未知占位符: %s" % _describe_keys(extra),
                    unit_id=unit_id,
                    evidence=["源文: %s" % _describe_keys(source_keys), "译文: %s" % _describe_keys(target_keys)],
                    suggestion="删除多余占位符，或确认它确实存在于运行时变量表中。",
                    extra={"extra": extra},
                )
            )

    # printf argument type/order checks.
    source_types = {t.meta.get("index"): t.meta.get("type") for t in source_printf if t.meta.get("index")}
    target_types = {t.meta.get("index"): t.meta.get("type") for t in target_printf if t.meta.get("index")}
    for index in sorted(set(source_types) & set(target_types)):
        if source_types[index] != target_types[index]:
            issues.append(
                Issue(
                    code="PH004",
                    severity="error",
                    category="placeholder",
                    message="printf 参数 %%%d$ 类型改变: %%%s → %%%s"
                    % (index, source_types[index], target_types[index]),
                    unit_id=unit_id,
                    evidence=["源文: %%%d$%s" % (index, source_types[index]), "译文: %%%d$%s" % (index, target_types[index])],
                    suggestion="保持参数类型一致（%d 需要数字，%s 需要字符串）。",
                    extra={"index": index},
                )
            )

    if not indexed_reorder:
        source_seq = _printf_types([t for t in source_tokens if t.kind == "printf"])
        target_seq = _printf_types([t for t in target_tokens if t.kind == "printf"])
        if len(source_seq) == len(target_seq) and source_seq and source_seq != target_seq:
            issues.append(
                Issue(
                    code="PH005",
                    severity="error",
                    category="placeholder",
                    message="printf 参数顺序/类型改变，非位置参数会按新顺序取值",
                    unit_id=unit_id,
                    evidence=["源文: %s" % " ".join("%" + t for t in source_seq), "译文: %s" % " ".join("%" + t for t in target_seq)],
                    suggestion="改用 %%1$s/%%2$s 位置参数，明确每个参数的用途。",
                    extra={"source_order": source_seq, "target_order": target_seq},
                )
            )
    elif source_printf and [t.meta.get("seq") for t in source_printf] != [
        t.meta.get("index") for t in target_printf
    ]:
        issues.append(
            Issue(
                code="PH011",
                severity="info",
                category="placeholder",
                message="已将非位置参数改为位置参数，顺序调整是安全的",
                unit_id=unit_id,
                evidence=["源文: %s" % _describe_keys(source_keys), "译文: %s" % _describe_keys(target_keys)],
                suggestion="保留位置参数写法；若运行时平台仅支持非位置参数，请人工确认顺序。",
            )
        )

    # Format specifier changes on ICU placeholders.
    source_icu = {t.key: t for t in source_tokens if t.kind == "icu"}
    target_icu = {t.key: t for t in target_tokens if t.kind == "icu"}
    for key in sorted(set(source_icu) & set(target_icu)):
        s, t = source_icu[key], target_icu[key]
        if s.fmt != t.fmt:
            if not s.fmt and t.fmt:
                issues.append(
                    Issue(
                        code="PH010",
                        severity="info",
                        category="template",
                        message="占位符扩展了 ICU 格式: %s → %s" % (s.raw, t.raw),
                        unit_id=unit_id,
                        evidence=[s.raw, t.raw],
                        suggestion="确认运行时支持该 ICU 扩展；这不代表工具已验证目标语语法正确。",
                    )
                )
            elif s.fmt and not t.fmt:
                issues.append(
                    Issue(
                        code="PH010",
                        severity="warning",
                        category="template",
                        message="译文丢失了占位符格式: %s → %s" % (s.raw, t.raw),
                        unit_id=unit_id,
                        evidence=[s.raw, t.raw],
                        suggestion="核对数字/日期/复数格式是否被有意移除。",
                    )
                )
            else:
                severe = bool(s.meta.get("branch_kind") or t.meta.get("branch_kind"))
                issues.append(
                    Issue(
                        code="PH010",
                        severity="error" if severe else "warning",
                        category="template" if severe else "placeholder",
                        message="ICU 格式说明改变: %s → %s" % (s.raw, t.raw),
                        unit_id=unit_id,
                        evidence=[s.raw, t.raw],
                        suggestion="占位符名称必须保留；数字/日期/复数格式调整需记录原因。",
                    )
                )

    for token in [t for t in target_tokens if t.kind == "icu"]:
        issues.extend(_icu_required_categories(token, locale, unit_id))

    # Rich text tag integrity.
    source_tags = [t for t in source_tokens if t.kind == "tag" and not t.meta.get("self_closing")]
    target_tags = [t for t in target_tokens if t.kind == "tag" and not t.meta.get("self_closing")]
    stack, unexpected, _ = _tag_balance(target)
    if stack:
        issues.append(
            Issue(
                code="PH006",
                severity="error",
                category="placeholder",
                message="译文富文本标签未闭合: %s" % ", ".join("<%s>" % name for name in stack),
                unit_id=unit_id,
                evidence=["译文: %s" % target],
                suggestion="补全闭合标签，或从源文同步标签结构。",
            )
        )
    if unexpected:
        issues.append(
            Issue(
                code="PH006",
                severity="error",
                category="placeholder",
                message="译文富文本标签闭合不匹配: %s" % ", ".join(unexpected),
                unit_id=unit_id,
                evidence=["译文: %s" % target],
                suggestion="检查 </b>/</color> 的嵌套顺序。",
            )
        )
    source_tag_names = sorted(t.key for t in source_tags)
    target_tag_names = sorted(t.key for t in target_tags)
    if source_tag_names != target_tag_names:
        # Only warn when counts differ; attribute values may legitimately change.
        from collections import Counter

        if Counter(source_tag_names) != Counter(target_tag_names):
            issues.append(
                Issue(
                    code="PH007",
                    severity="warning",
                    category="placeholder",
                    message="译文富文本标签结构与源文不一致",
                    unit_id=unit_id,
                    evidence=["源文标签: %s" % (source_tag_names or "无"), "译文标签: %s" % (target_tag_names or "无")],
                    suggestion="确认标签差异是否为设计需求；否则从源文复制标签结构。",
                )
            )

    source_escaped = sum(1 for t in source_tokens if t.kind == "escaped" and t.raw == "{{")
    target_escaped = sum(1 for t in target_tokens if t.kind == "escaped" and t.raw == "{{")
    if source_escaped != target_escaped:
        issues.append(
            Issue(
                code="PH009",
                severity="warning",
                category="placeholder",
                message="转义花括号数量不一致: 源文 %d / 译文 %d" % (source_escaped, target_escaped),
                unit_id=unit_id,
                evidence=["源文: %s" % source, "译文: %s" % target],
                suggestion="成对使用 {{ 与 }} 表示字面花括号。",
            )
        )

    # Advisory grammar signal: a quantity placeholder without plural handling.
    if _quantity_placeholder_in_source(source) and not _target_handles_plural(target):
        base = locale.split("-")[0].lower()
        if base in PLURAL_CATEGORIES:
            issues.append(
                Issue(
                    code="PH012",
                    severity="info",
                    category="template",
                    message="占位符语义未类型化：无法自动验证目标语单复数/性数一致",
                    unit_id=unit_id,
                    evidence=["源文: %s" % source, "目标语: %s" % locale],
                    suggestion="工具只做模板完整性检查，不判断语法正确性；请由译者确认数量语义并使用 ICU plural 或平台接口。",
                )
            )

    summary = {
        "source_keys": source_keys,
        "target_keys": target_keys,
        "missing": [k for k in source_keys if k not in target_set],
        "extra": [k for k in target_keys if k not in source_set],
        "syntax_problems": source_problems + target_problems,
        "printf_reorder_safe": indexed_reorder,
        "tags": {
            "source": [t.raw for t in source_tokens if t.kind == "tag"],
            "target": [t.raw for t in target_tokens if t.kind == "tag"],
        },
    }
    return issues, summary


QUANTITY_CLASSIFIERS = (
    "个",
    "名",
    "条",
    "件",
    "次",
    "级",
    "天",
    "小时",
    "分钟",
    "秒",
    "岁",
    "颗",
    "张",
    "把",
    "本",
    "份",
    "封",
    "篇",
    "首",
    "种",
    "款",
    "位",
    "只",
    "枚",
    "箱",
    "瓶",
    "金币",
    "钻石",
    "经验",
    "体力",
    "点券",
    "积分",
)


def _quantity_placeholder_in_source(source: str) -> bool:
    tokens, _ = tokenize(source)
    for token in tokens:
        if token.kind not in ("icu", "printf"):
            continue
        after = source[token.end : token.end + 8].lstrip(" ")
        before = source[max(0, token.start - 4) : token.start]
        if any(after.startswith(c) for c in QUANTITY_CLASSIFIERS):
            return True
        if before.endswith("第") and re.match(r"\s*[级名]", after):
            return True
    return False


def _target_handles_plural(target: str) -> bool:
    lowered = target.lower()
    if re.search(r"\{\s*[A-Za-z0-9_]+,\s*(plural|selectordinal)\b", target):
        return True
    if re.search(r"\(s\)|\[s\]|/s\b", lowered):
        return True
    return False


def infer_placeholder_semantics(source: str) -> List[Dict[str, Any]]:
    """Infer the *likely* role of each placeholder from its immediate co-text.

    This is evidence, not proof. Unknown cases stay ``unknown``.
    """
    tokens, _ = tokenize(source)
    results: List[Dict[str, Any]] = []
    for token in tokens:
        if token.kind not in ("icu", "printf"):
            continue
        after = source[token.end :]
        before = source[: token.start]
        evidence: List[str] = []
        inferred = "unknown"
        confidence = "low"
        after_trim = after.lstrip(" ")
        if token.meta.get("format_kind") in ("number", "date", "time"):
            inferred = token.meta["format_kind"]
            confidence = "high"
            evidence.append("占位符显式声明 %s 格式" % token.meta["format_kind"])
        elif any(after_trim.startswith(c) for c in QUANTITY_CLASSIFIERS):
            classifier = next(c for c in QUANTITY_CLASSIFIERS if after_trim.startswith(c))
            inferred = "count"
            confidence = "high"
            evidence.append("占位符后紧跟量词/资源名词“%s”" % classifier)
        elif re.search(r"[年月日时分秒]$", before[-3:]) or re.match(
            r"\s*[年月日时分秒]", after_trim
        ):
            inferred = "date"
            confidence = "medium"
            evidence.append("占位符位于日期部件之间")
        elif after_trim.startswith("%") or after_trim.startswith("％"):
            inferred = "number"
            confidence = "medium"
            evidence.append("占位符后紧跟百分号，推测为数值")
        elif any(after_trim.startswith(w) for w in ("前", "后", "内", "时", "区", "服", "线")):
            inferred = "time_or_server"
            confidence = "medium"
            evidence.append("占位符后紧跟时间/区服词“%s”" % after_trim[:2])
        elif any(before.rstrip().endswith(w) for w in ("前往", "到达", "进入", "来自", "去往")):
            inferred = "name_or_location"
            confidence = "low"
            evidence.append("占位符位于位移动词后，可能是地名/人名")
        elif any(before.rstrip().endswith(w) for w in ("名为", "叫做", "玩家", "英雄", "道具")):
            inferred = "name"
            confidence = "low"
            evidence.append("占位符位于名词性提示后，可能是名称")
        if inferred == "unknown":
            evidence.append("没有足够的局部搭配词判定语义")
        results.append(
            {
                "placeholder": token.raw,
                "key": token.key,
                "inferred": inferred,
                "confidence": confidence,
                "evidence": evidence,
            }
        )
    return results

"""Real font-metric UI overflow measurement.

This is the part that distinguishes the prototype from a character counter:
the target string is shaped with an actual TTF (the same file the browser
loads), wrapped at real glyph widths, and compared against the real content
box. A naive character-count baseline is kept side by side so the difference
is visible and testable.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import ImageFont

from .models import Issue, StringUnit, UiSpec

ROOT = Path(__file__).resolve().parent.parent
FONT_PATH = ROOT / "assets" / "fonts" / "NotoSans-Variable.ttf"
FONT_NAME = "NotoSans-Variable.ttf"

# Noto Sans (Latin/Greek/Cyrillic) does not ship CJK glyphs. Rather than
# measuring tofu boxes and pretending, we report the limitation.
CJK_RE = re.compile(r"[\u2e80-\u9fff\u3040-\u30ff\uac00-\ud7af\uf900-\ufaff]")
TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9_-]*[^<>]*?/?>")
ICU_TEMPLATE_RE = re.compile(r"\{[^{}]*,\s*(plural|select|selectordinal)\b", re.IGNORECASE)
BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
BREAKABLE_RE = re.compile(
    r"(\s+|[\u2e80-\u9fff\u3040-\u30ff\uac00-\ud7af]|[^\s\u2e80-\u9fff\u3040-\u30ff\uac00-\ud7af]+)"
)


def _font(size: float) -> ImageFont.FreeTypeFont:
    if not FONT_PATH.exists():  # pragma: no cover - packaging guard
        raise RuntimeError("缺少字体文件 assets/fonts/%s" % FONT_NAME)
    return _load_font(str(FONT_PATH), int(round(size)))


@lru_cache(maxsize=64)
def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(path, size=size)
    try:
        # Keep the variable font on its Regular instance regardless of the
        # ambient default. Axes are [width, weight] for Noto Sans.
        axes = font.get_variation_axes()
        if len(axes) == 2:
            font.set_variation_by_axes([100, 400])
    except (AttributeError, OSError, TypeError):
        pass
    return font


def plain_text(text: str) -> str:
    """Replace structural tags with newlines and drop formatting tags."""
    text = BR_RE.sub("\n", text or "")
    return TAG_RE.sub("", text)


def _shape_width(font: ImageFont.FreeTypeFont, text: str, letter_spacing: float) -> float:
    if not text:
        return 0.0
    return float(font.getlength(text)) + max(0, len(text) - 1) * letter_spacing


def _wrap(font: ImageFont.FreeTypeFont, text: str, content_w: float, letter_spacing: float) -> List[str]:
    """Greedy wrap at word boundaries; CJK chars are breakable individually."""
    if not text:
        return [""]
    lines: List[str] = []
    for paragraph in text.split("\n"):
        if paragraph == "":
            lines.append("")
            continue
        tokens = [t for t in BREAKABLE_RE.split(paragraph) if t]
        current = ""
        for token in tokens:
            if token.isspace():
                if current and not current.endswith(" "):
                    current += " "
                continue
            candidate = current + token
            if _shape_width(font, candidate, letter_spacing) <= content_w:
                current = candidate
                continue
            if current.strip():
                lines.append(current.rstrip())
                current = ""
            if _shape_width(font, token, letter_spacing) <= content_w:
                current = token
                continue
            # A single unbreakable token is wider than the box: break by char.
            for ch in token:
                candidate = current + ch
                if current and _shape_width(font, candidate, letter_spacing) > content_w:
                    lines.append(current.rstrip())
                    current = ch
                else:
                    current = candidate
        if current or not lines:
            lines.append(current.rstrip())
    return lines or [""]


def _naive_baseline(text: str, ui: UiSpec) -> Dict[str, Any]:
    """A deliberately naive character-count heuristic, kept for comparison.

    Width estimate: 0.55em per character. This is the common CAT-tool rule of
    thumb; the demo shows where it is wrong in both directions.
    """
    chars = len(text)
    avg_char_px = round(0.55 * ui.font_size, 2)
    estimated_width = chars * avg_char_px
    estimated_lines = 1
    if ui.content_width > 0:
        import math

        estimated_lines = max(1, int(math.ceil(estimated_width / ui.content_width)))
    return {
        "method": "字符数 × 0.55em",
        "avg_char_px": avg_char_px,
        "estimated_width_px": round(estimated_width, 1),
        "estimated_lines": estimated_lines,
        "overflow": estimated_width - ui.content_width if estimated_lines > ui.max_lines else max(
            0.0, estimated_width - ui.content_width
        ),
        "fits": estimated_lines <= ui.max_lines and estimated_width <= ui.content_width,
    }


def measure(unit: StringUnit) -> Dict[str, Any]:
    """Measure one unit against its UI box. Never raises for user text."""
    ui = unit.ui
    text = plain_text(unit.target)
    if ICU_TEMPLATE_RE.search(unit.target):
        # A plural/select template renders one branch per runtime value; measuring
        # the raw template would be a fake result, so report the limitation.
        return {
            "supported": False,
            "reason": "ICU plural/select 模板需按运行时分支渲染后测量；v0.1 不展开分支，拒绝给出伪测量值",
            "font": {"file": FONT_NAME, "size": ui.font_size},
            "box": ui.to_dict(),
            "text": text,
            "char_count": len(text),
            "max_chars": unit.max_chars,
        }
    if CJK_RE.search(text):
        return {
            "supported": False,
            "reason": "内置 NotoSans 字体不含 CJK 字形，无法可靠测量中文/日文/韩文译文",
            "font": {"file": FONT_NAME, "size": ui.font_size},
            "box": ui.to_dict(),
            "text": text,
            "char_count": len(text),
            "max_chars": unit.max_chars,
        }
    font = _font(ui.font_size)
    if ui.max_lines == 1:
        # Single-line labels clip or stay on one line; do not invent wrapping.
        lines = text.split("\n") if text else [""]
    else:
        lines = _wrap(font, text, ui.content_width, ui.letter_spacing)
    widths = [round(_shape_width(font, line, ui.letter_spacing), 1) for line in lines]
    max_width = max(widths) if widths else 0.0
    line_height_px = ui.font_size * ui.line_height
    required_height = line_height_px * max(1, len(lines)) + 2 * ui.padding
    width_overflow = max(0.0, max_width - ui.content_width)
    height_overflow = max(0.0, required_height - ui.box_h)
    reasons: List[str] = []
    if width_overflow > 0.5:
        reasons.append("文本宽度超出内容区 %.1fpx" % width_overflow)
    if len(lines) > ui.max_lines:
        reasons.append("需要 %d 行，超过上限 %d 行" % (len(lines), ui.max_lines))
    if height_overflow > 0.5:
        reasons.append("所需高度超出文本框 %.1fpx" % height_overflow)
    actual_overflow = bool(reasons)
    naive = _naive_baseline(text, ui)
    char_budget_overflow = bool(unit.max_chars is not None and len(text) > unit.max_chars)
    width_ratio = round(max_width / ui.content_width, 3) if ui.content_width else 0.0
    return {
        "supported": True,
        "font": {"file": FONT_NAME, "size": ui.font_size, "weight": 400},
        "box": ui.to_dict(),
        "text": text,
        "char_count": len(text),
        "max_chars": unit.max_chars,
        "char_budget_overflow": char_budget_overflow,
        "assumptions": [
            "字形宽度来自 Pillow/FreeType + 同一 TTF（Noto Sans Regular）",
            "仅按给定字号、字重、字距与文本框尺寸计算，不模拟游戏引擎布局",
            "按词/中日韩字符贪心换行，不支持自动缩放、富文本内联样式或 fallback 字体链",
            "占位符按字面宽度测量；运行时替换后的实际宽度可能不同",
        ],
        "naive": naive,
        "measured": {
            "lines": lines,
            "line_widths_px": widths,
            "line_count": len(lines),
            "max_line_width_px": max_width,
            "line_height_px": round(line_height_px, 1),
            "required_height_px": round(required_height, 1),
            "width_overflow_px": round(width_overflow, 1),
            "height_overflow_px": round(height_overflow, 1),
            "width_ratio": width_ratio,
            "overflow": actual_overflow,
            "reasons": reasons,
        },
        "disagreement": {
            "naive_says_fits": naive["fits"],
            "measured_fits": not actual_overflow,
            "kind": (
                "none"
                if naive["fits"] == (not actual_overflow)
                else ("false_negative" if naive["fits"] and actual_overflow else "false_positive")
            ),
        },
    }


def overflow_issues(unit: StringUnit, result: Dict[str, Any]) -> List[Issue]:
    """Turn a measurement into user-facing issues."""
    if not result.get("supported", True):
        return [
            Issue(
                code="OVF000",
                severity="info",
                category="overflow",
                message="无法测量: %s" % result.get("reason", "字体不支持"),
                unit_id=unit.id,
                evidence=[unit.target],
                suggestion="为目标语加载对应字体后再测量；不要把字符数当作渲染结果。",
            )
        ]
    measured = result["measured"]
    naive = result["naive"]
    issues: List[Issue] = []
    evidence = [
        "内容区 %.0f×%.0fpx，字号 %.0fpx，上限 %d 行"
        % (
            result["box"]["content_width"],
            result["box"]["content_height"],
            result["box"]["font_size"],
            result["box"]["max_lines"],
        ),
        "实测最宽行 %.1fpx，%d 行，需要高度 %.1fpx"
        % (measured["max_line_width_px"], measured["line_count"], measured["required_height_px"]),
        "字符数基线: %d 字符 × %.2fpx = %.1fpx"
        % (result["char_count"], naive["avg_char_px"], naive["estimated_width_px"]),
    ]
    if measured["overflow"]:
        issues.append(
            Issue(
                code="OVF001",
                severity="error",
                category="overflow",
                message="按给定字体/布局假设实测宽度风险: %s" % "；".join(measured["reasons"]),
                unit_id=unit.id,
                evidence=evidence,
                suggestion="缩短译文、允许换行/缩小字号，或在 UI 中扩大文本框后重新测量；并在目标引擎中确认。",
                extra={"measured": measured, "naive": naive},
            )
        )
    elif measured["width_ratio"] >= 0.9 and result["char_count"] > 0:
        issues.append(
            Issue(
                code="OVF002",
                severity="warning",
                category="overflow",
                message="接近溢出边界（宽度占用 %.0f%%）" % (measured["width_ratio"] * 100),
                unit_id=unit.id,
                evidence=evidence,
                suggestion="该语种后续文案迭代容易越界，建议预留余量。",
            )
        )
    if result.get("char_budget_overflow") and not measured["overflow"]:
        issues.append(
            Issue(
                code="OVF003",
                severity="info",
                category="overflow",
                message="字符数超出设计预算，但按给定字体/布局假设测量仍可容纳",
                unit_id=unit.id,
                evidence=evidence + ["设计预算 %s 字符" % result["max_chars"]],
                suggestion="字符数只能预警；本次字体测量是给定布局假设下的风险信号，也需结合游戏内实测。",
            )
        )
    if naive["fits"] and measured["overflow"]:
        issues.append(
            Issue(
                code="OVF004",
                severity="warning",
                category="overflow",
                message="字符数基线误判为“可容纳”，按字体测量则溢出",
                unit_id=unit.id,
                evidence=evidence,
                suggestion="宽字形、窄容器等场景应做字体测量；最终仍以游戏引擎内实测为准。",
            )
        )
    if not naive["fits"] and not measured["overflow"]:
        issues.append(
            Issue(
                code="OVF005",
                severity="info",
                category="overflow",
                message="字符数基线误判为“溢出”，按字体测量则可容纳",
                unit_id=unit.id,
                evidence=evidence,
                suggestion="窄字形或大容器下，字符数会高估宽度；以实测为准。",
            )
        )
    return issues


def render_preview_svg(unit: StringUnit, result: Dict[str, Any]) -> str:
    """Generate a small SVG preview of the measured box (used in exports)."""
    if not result.get("supported", True):
        return ""
    box = result["box"]
    measured = result["measured"]
    width = int(box["box_w"])
    height = int(box["box_h"])
    pad = int(box["padding"])
    overflow = measured["overflow"]
    color = "#d64545" if overflow else "#2f9e6e"
    rows = []
    for index, line in enumerate(measured["lines"][: box["max_lines"] + 1]):
        y = pad + int(box["font_size"]) + index * int(measured["line_height_px"])
        rows.append(
            '<text x="%d" y="%d" font-family="Noto Sans, sans-serif" font-size="%d" fill="#222">%s</text>'
            % (pad, y, int(box["font_size"]), _svg_escape(line))
        )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">'
        '<rect x="1" y="1" width="%d" height="%d" rx="6" fill="#fff" stroke="%s" stroke-width="2"/>'
        "%s</svg>"
        % (width, height, width, height, width - 2, height - 2, color, "".join(rows))
    )


def _svg_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

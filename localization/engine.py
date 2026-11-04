"""Analysis orchestration: run every check and aggregate a review report."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import __version__
from .ambiguity import detect_register_risks, detect_source_gaps
from .context import context_issues, resolve
from .llm import LLMConfig, suggest_strategy
from .models import Dataset, Issue, Report, StringUnit, UnitResult
from .overflow import measure, overflow_issues
from .placeholders import check_placeholders

ENGINE_NAME = "game-localization-preflight"

CORE_CHECKS = [
    "占位符/变量保留、重排合法性与 printf 类型完整性",
    "ICU plural 模板的 CLDR 分类完整性（仅模板格式，不判断语法正确性）",
    "富文本标签闭合与结构一致性",
    "给定字体、字号、字距、文本框与换行假设下的宽度风险测量（含字符数基线）",
]

EXPERIMENTAL_CHECKS = [
    "UI 多义词消歧（基于项目现有 key/界面/组件/相邻文案的策展义项库 + 证据打分，可弃答）",
    "中文源文语境缺口标注（主语/时态/指代/占位符语义，改为人工问题而非猜测）",
    "语气/梗/黑话风险标记（策略建议；实时 LLM 仅在配置并显式开启时调用）",
]

LIMITATIONS = [
    "不验证目标语语法是否正确；无类型 {0} 的语义未知时只检查保留/重排，并标记“需上下文”。",
    "字体测量是“给定字体与布局假设下的宽度风险”，不等于游戏引擎内真实布局；不模拟自动缩放、富文本内联样式、fallback 字体链与换行策略。",
    "多义词消歧依赖策展义项库与现有元数据；证据不足时弃答，不把关键词映射伪装成语义理解。",
    "XLIFF 导入 v0.1 展平内联 <g>/<ph> 标记；不支持 XLIFF 2.0 与完整占位符映射。",
    "没有厂商访谈或竞品 A/B 数据；本原型仅声称课程级可运行演示，不声称商业优势。",
]

VALIDATION_CAVEATS = [
    "目标语复数/性数一致只有在变量语义、CLDR 规则和模板格式都已知时才可检查；本工具的 PH008 只检查 ICU 模板分类是否齐全。",
    "字符数基线仅用于对照，不能代替字体测量，也不能代替游戏内实测。",
]


def _sort_issues(issues: List[Issue]) -> List[Issue]:
    order = {"error": 0, "warning": 1, "info": 2}
    return sorted(issues, key=lambda item: (order.get(item.severity, 9), item.code, item.message))


def analyze(
    dataset: Dataset,
    llm_enhance: bool = False,
    llm_config: Optional[LLMConfig] = None,
) -> Report:
    config = llm_config or LLMConfig.from_env()
    results: List[UnitResult] = []
    llm_calls = 0
    llm_errors: List[str] = []
    for unit in dataset.units:
        issues: List[Issue] = []
        result = UnitResult(
            id=unit.id,
            source=unit.source,
            target=unit.target,
            key=unit.key,
            screen=unit.screen,
            component=unit.component,
            neighbors=list(unit.neighbors),
            ui=unit.ui,
        )
        if not unit.target.strip():
            if unit.source.strip():
                issues.append(
                    Issue(
                        code="PH013",
                        severity="warning",
                        category="placeholder",
                        message="译文为空，无法检查占位符与布局",
                        unit_id=unit.id,
                        evidence=["源文: " + unit.source],
                        suggestion="补全译文后再运行完整预检。",
                    )
                )
        else:
            placeholder_issues, placeholder_summary = check_placeholders(
                unit.source, unit.target, dataset.target_locale, unit.id
            )
            result.placeholder = placeholder_summary
            issues.extend(placeholder_issues)
            measurement = measure(unit)
            result.overflow = measurement
            issues.extend(overflow_issues(unit, measurement))

        resolution = resolve(unit, dataset.target_locale)
        result.context = resolution
        issues.extend(context_issues(unit, resolution))

        gap_issues, gaps = detect_source_gaps(unit, dataset.source_locale)
        result.source_gaps = gaps
        issues.extend(gap_issues)

        register_issues, risks = detect_register_risks(unit)
        result.register_risks = risks
        issues.extend(register_issues)
        if llm_enhance and risks and config.enabled:
            for risk, issue in zip(risks, register_issues):
                suggestion = suggest_strategy(unit, dataset.target_locale, issue.message, config)
                llm_calls += 1
                if suggestion.get("status") == "ok":
                    risk["llm_suggestion"] = suggestion
                else:
                    risk["llm_error"] = suggestion.get("detail", "未知错误")
                    llm_errors.append("%s: %s" % (unit.id, suggestion.get("detail", "未知错误")))

        result.issues = _sort_issues(issues)
        result.needs_human = any(issue.severity in ("error", "warning") for issue in result.issues)
        results.append(result)

    summary = _summarise(results)
    engine = {
        "name": ENGINE_NAME,
        "version": __version__,
        "mode": "deterministic+llm" if llm_enhance and config.enabled else "deterministic",
        "core_checks": CORE_CHECKS,
        "experimental_checks": EXPERIMENTAL_CHECKS,
        "limitations": LIMITATIONS,
        "caveats": VALIDATION_CAVEATS,
    }
    llm_info = {
        "configured": config.enabled,
        "requested": bool(llm_enhance),
        "model": config.model if config.enabled else "",
        "calls": llm_calls,
        "errors": llm_errors,
    }
    return Report(
        dataset=dataset,
        units=results,
        summary=summary,
        engine=engine,
        llm=llm_info,
        generated_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    )


def _summarise(results: List[UnitResult]) -> Dict[str, Any]:
    status_counts = Counter(result.status for result in results)
    all_issues = [issue for result in results for issue in result.issues]
    severity_counts = Counter(issue.severity for issue in all_issues)
    category_counts = Counter(issue.category for issue in all_issues)
    code_counts = Counter(issue.code for issue in all_issues)

    matched = [result for result in results if result.context]
    context_counts = Counter(
        (result.context or {}).get("status", "") for result in matched
    )
    with_key = sum(1 for result in results if result.key)
    with_screen = sum(1 for result in results if result.screen)
    with_neighbors = sum(1 for result in results if result.neighbors)
    with_any = sum(
        1 for result in results if result.key or result.screen or result.neighbors or result.component
    )

    measured = [result for result in results if result.overflow and result.overflow.get("supported", True)]
    measured = [result for result in measured if result.overflow]
    overflow_units = [
        result
        for result in measured
        if result.overflow and result.overflow.get("measured", {}).get("overflow")
    ]
    near = [result for result in measured if any(i.code == "OVF002" for i in result.issues)]
    unsupported = [
        result
        for result in results
        if result.overflow and not result.overflow.get("supported", True)
    ]
    naive_fp = [result for result in measured if any(i.code == "OVF005" for i in result.issues)]
    naive_fn = [result for result in measured if any(i.code == "OVF004" for i in result.issues)]

    gap_units = [result for result in results if result.source_gaps]
    gap_types = Counter(
        gap.get("type", "") for result in results for gap in result.source_gaps
    )
    register_units = [result for result in results if result.register_risks]
    register_types = Counter(
        risk.get("type", "") for result in results for risk in result.register_risks
    )

    placeholder_errors = [
        issue
        for result in results
        for issue in result.issues
        if issue.category in ("placeholder", "template") and issue.severity == "error"
    ]
    units_with_placeholders = sum(
        1
        for result in results
        if result.placeholder and result.placeholder.get("source_keys")
    )

    return {
        "total_units": len(results),
        "unit_status": {
            "pass": status_counts.get("pass", 0),
            "info": status_counts.get("info", 0),
            "warning": status_counts.get("warning", 0),
            "error": status_counts.get("error", 0),
        },
        "issues": {
            "total": len(all_issues),
            "by_severity": {
                "error": severity_counts.get("error", 0),
                "warning": severity_counts.get("warning", 0),
                "info": severity_counts.get("info", 0),
            },
            "by_category": dict(sorted(category_counts.items())),
            "by_code": dict(sorted(code_counts.items())),
        },
        "needs_human_units": sum(1 for result in results if result.needs_human),
        "context": {
            "matched_units": len(matched),
            "resolved": context_counts.get("resolved", 0),
            "inferred": context_counts.get("inferred", 0),
            "insufficient": context_counts.get("insufficient", 0),
            "coverage": {
                "with_key": with_key,
                "with_screen": with_screen,
                "with_component": sum(1 for result in results if result.component),
                "with_neighbors": with_neighbors,
                "with_any_context": with_any,
                "ratio": round(with_any / len(results), 2) if results else 0.0,
            },
            "method": "策展义项库 + 现有元数据证据打分；证据不足时弃答，不做语义理解",
        },
        "overflow": {
            "measured_units": len(measured),
            "overflow_units": len(overflow_units),
            "near_threshold_units": len(near),
            "unsupported_units": len(unsupported),
            "naive_false_positive_units": len(naive_fp),
            "naive_false_negative_units": len(naive_fn),
            "method": "Pillow/FreeType + 同一 TTF，按给定字体/字号/字距/文本框/换行假设测量",
        },
        "placeholders": {
            "units_with_placeholders": units_with_placeholders,
            "units_with_errors": len({issue.unit_id for issue in placeholder_errors}),
            "errors": len(placeholder_errors),
        },
        "source_gaps": {
            "units": len(gap_units),
            "by_type": dict(sorted(gap_types.items())),
        },
        "register": {
            "units": len(register_units),
            "by_type": dict(sorted(register_types.items())),
        },
    }

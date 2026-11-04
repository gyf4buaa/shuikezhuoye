"""Data models shared by the analysis engine, report writers and the web app."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
SEVERITY_LABELS = {"error": "阻断错误", "warning": "需复核", "info": "提示"}

CATEGORY_LABELS = {
    "placeholder": "占位符",
    "template": "目标语模板",
    "overflow": "UI 溢出",
    "context": "术语消歧",
    "source_context": "源文语境缺口",
    "register": "语气/修辞",
    "format": "格式",
}


@dataclass
class UiSpec:
    """A synthetic UI text box specification used for measurement.

    All values are CSS pixels. The same numbers are used by the browser
    preview so that server measurement and browser measurement describe the
    same box.
    """

    profile: str = "mobile_dialog"
    font_size: float = 16.0
    box_w: float = 280.0
    box_h: float = 60.0
    max_lines: int = 2
    line_height: float = 1.4
    padding: float = 10.0
    letter_spacing: float = 0.0

    @property
    def content_width(self) -> float:
        return max(0.0, self.box_w - 2 * self.padding)

    @property
    def content_height(self) -> float:
        return max(0.0, self.box_h - 2 * self.padding)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["content_width"] = round(self.content_width, 2)
        data["content_height"] = round(self.content_height, 2)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UiSpec":
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {k: v for k, v in (data or {}).items() if k in allowed}
        return cls(**clean)


@dataclass
class StringUnit:
    """One localizable string plus the context the project already has."""

    id: str
    source: str
    target: str = ""
    key: str = ""
    screen: str = ""
    component: str = ""
    neighbors: List[str] = field(default_factory=list)
    max_chars: Optional[int] = None
    ui: UiSpec = field(default_factory=UiSpec)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Issue:
    code: str
    severity: str  # error | warning | info
    category: str
    message: str
    unit_id: str = ""
    evidence: List[str] = field(default_factory=list)
    suggestion: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["severity_label"] = SEVERITY_LABELS.get(self.severity, self.severity)
        data["category_label"] = CATEGORY_LABELS.get(self.category, self.category)
        return data


@dataclass
class UnitResult:
    id: str
    source: str
    target: str
    key: str
    screen: str
    component: str
    neighbors: List[str]
    ui: UiSpec
    issues: List[Issue] = field(default_factory=list)
    context: Optional[Dict[str, Any]] = None
    placeholder: Optional[Dict[str, Any]] = None
    overflow: Optional[Dict[str, Any]] = None
    source_gaps: List[Dict[str, Any]] = field(default_factory=list)
    register_risks: List[Dict[str, Any]] = field(default_factory=list)
    needs_human: bool = False

    @property
    def status(self) -> str:
        if any(i.severity == "error" for i in self.issues):
            return "error"
        if any(i.severity == "warning" for i in self.issues):
            return "warning"
        if any(i.severity == "info" for i in self.issues):
            return "info"
        return "pass"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "key": self.key,
            "screen": self.screen,
            "component": self.component,
            "neighbors": self.neighbors,
            "ui": self.ui.to_dict(),
            "status": self.status,
            "needs_human": self.needs_human,
            "issues": [i.to_dict() for i in self.issues],
            "context": self.context,
            "placeholder": self.placeholder,
            "overflow": self.overflow,
            "source_gaps": self.source_gaps,
            "register_risks": self.register_risks,
        }


@dataclass
class Dataset:
    project: str
    source_locale: str
    target_locale: str
    units: List[StringUnit]
    ui_profile: str = "mobile_dialog"
    synthetic: bool = True
    notice: str = ""

    def meta(self) -> Dict[str, Any]:
        return {
            "project": self.project,
            "source_locale": self.source_locale,
            "target_locale": self.target_locale,
            "ui_profile": self.ui_profile,
            "synthetic": self.synthetic,
            "notice": self.notice,
            "count": len(self.units),
        }


@dataclass
class Report:
    dataset: Dataset
    units: List[UnitResult]
    summary: Dict[str, Any]
    engine: Dict[str, Any]
    llm: Dict[str, Any] = field(default_factory=dict)
    generated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "meta": self.dataset.meta(),
            "engine": self.engine,
            "llm": self.llm,
            "generated_at": self.generated_at,
            "summary": self.summary,
            "units": [u.to_dict() for u in self.units],
        }

    @property
    def issues(self) -> List[Issue]:
        out: List[Issue] = []
        for unit in self.units:
            out.extend(unit.issues)
        return out

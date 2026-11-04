"""Dataset loading and validation for the A/B/C experiment.

The dataset deliberately contains no model outputs and no target-language
strings.  ``expected_context`` is a human audit field; it is written to the
manual review template but never to a prompt.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from .corpus import LeakageError, OpenTTDCorpus
from .openttd import Bundle, OpenTTDLocator
from .prompts import Prompt, build_prompts


@dataclass(frozen=True)
class Case:
    id: str
    key: str
    category: str
    expected_context: str
    expected_locations: Sequence[str] = ()
    notes: str = ""
    expected_status: Optional[str] = None


@dataclass
class CaseRecord:
    case: Case
    bundle: Bundle
    prompts: Dict[str, Prompt]

    @property
    def evidence_ids(self) -> List[str]:
        return self.bundle.evidence_ids


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_dataset(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1:
        raise ValueError(f"unsupported dataset schema: {data.get('schema')!r}")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("dataset has no cases")
    return data


def parse_cases(data: dict) -> List[Case]:
    cases: List[Case] = []
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()
    for raw in data["cases"]:
        case = Case(
            id=str(raw["id"]),
            key=str(raw["key"]),
            category=str(raw["category"]),
            expected_context=str(raw["expected_context"]),
            expected_locations=tuple(raw.get("expected_locations", [])),
            notes=str(raw.get("notes", "")),
            expected_status=raw.get("expected_status"),
        )
        if case.id in seen_ids:
            raise ValueError(f"duplicate case id: {case.id}")
        if case.key in seen_keys:
            raise ValueError(f"duplicate key in dataset: {case.key}")
        seen_ids.add(case.id)
        seen_keys.add(case.key)
        cases.append(case)
    return cases


def validate_case_evidence(case: Case, corpus: OpenTTDCorpus) -> None:
    """Expected locations must point at allowlisted English source files."""
    for location in case.expected_locations:
        path = location.rpartition(":")[0]
        try:
            allowed = corpus.is_evidence_path(path)
        except LeakageError:
            allowed = False
        if not allowed:
            raise LeakageError(
                f"case {case.id} expected location is not allowlisted evidence: {path}"
            )
        if path.startswith("src/lang/") or path.endswith((".po", ".mo")):
            raise LeakageError(
                f"case {case.id} points at a language table: {path}"
            )


def build_records(
    corpus: OpenTTDCorpus,
    locator: OpenTTDLocator,
    cases: Sequence[Case],
    target_locale: str,
) -> List[CaseRecord]:
    records: List[CaseRecord] = []
    for case in cases:
        if case.key not in corpus.entry_by_key:
            raise ValueError(f"case {case.id} uses an unknown key: {case.key}")
        validate_case_evidence(case, corpus)
        bundle = locator.lookup(case.key)
        prompts = build_prompts(bundle, target_locale)
        records.append(CaseRecord(case=case, bundle=bundle, prompts=prompts))
    return records


RUBRIC_COLUMNS = (
    "case_id",
    "key",
    "arm",
    "source_text",
    "expected_context",
    "translation",
    "context_sense",
    "terminology",
    "placeholders",
    "fluency",
    "overall",
    "reviewer",
    "notes",
)

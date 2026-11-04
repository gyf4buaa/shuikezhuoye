#!/usr/bin/env python3
"""Summarise the human A/B/C review rubric.

The rubric is fixed before the live run:

* context_sense: 1-5, the translation fits the source usage context;
* terminology: 1-5, game terms and entities are translated consistently;
* placeholders: 1-5, every placeholder/control code is preserved and placed
  naturally;
* fluency: 1-5, target-language grammar and UI concision;
* overall: 1-5, an overall usefulness judgement.

Scores are human input.  This tool never invents or averages empty cells; a
missing score is reported as missing.  Pairwise comparisons are only computed
for cases where both arms have an ``overall`` score.

Usage:
    python3 scripts/review.py --scores runs/live-1/review_template.csv \
        --out runs/live-1/review_summary.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from statistics import mean
from typing import Dict, Iterable, List, Optional, Sequence

SCORE_FIELDS = ("context_sense", "terminology", "placeholders", "fluency", "overall")
ARMS = ("A", "B", "C")


def _score(value: str) -> Optional[float]:
    text = (value or "").strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        raise ValueError(f"not a number: {value!r}")
    if not (1.0 <= number <= 5.0):
        raise ValueError(f"score outside 1-5: {value!r}")
    return number


def load_rows(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [field for field in ("case_id", "key", "arm", *SCORE_FIELDS) if field not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"score CSV is missing columns: {missing}")
        rows: List[dict] = []
        for raw in reader:
            arm = raw["arm"].strip().upper()
            if arm not in ARMS:
                raise ValueError(f"invalid arm: {raw['arm']!r}")
            row = {
                "case_id": raw["case_id"].strip(),
                "key": raw["key"].strip(),
                "arm": arm,
                "scores": {field: _score(raw.get(field, "")) for field in SCORE_FIELDS},
                "reviewer": (raw.get("reviewer") or "").strip(),
                "notes": (raw.get("notes") or "").strip(),
            }
            rows.append(row)
    return rows


def summarise(rows: Sequence[dict]) -> dict:
    by_arm: Dict[str, Dict[str, Optional[float]]] = {}
    counts: Dict[str, Dict[str, int]] = {}
    for arm in ARMS:
        arm_rows = [row for row in rows if row["arm"] == arm]
        counts[arm] = {"rows": len(arm_rows)}
        by_arm[arm] = {}
        for field in SCORE_FIELDS:
            values = [row["scores"][field] for row in arm_rows if row["scores"][field] is not None]
            by_arm[arm][field] = round(mean(values), 3) if values else None
            counts[arm][field] = len(values)
    by_case: Dict[str, Dict[str, Optional[float]]] = {}
    for row in rows:
        by_case.setdefault(row["case_id"], {})[row["arm"]] = row["scores"]["overall"]
    pairs: Dict[str, Dict[str, int]] = {}
    for left, right in (("C", "A"), ("C", "B")):
        wins = ties = losses = 0
        for case_id, scores in by_case.items():
            a, b = scores.get(left), scores.get(right)
            if a is None or b is None:
                continue
            if a > b:
                wins += 1
            elif a == b:
                ties += 1
            else:
                losses += 1
        pairs[f"{left}_vs_{right}"] = {
            "comparable_cases": wins + ties + losses,
            "left_wins": wins,
            "ties": ties,
            "right_wins": losses,
        }
    return {
        "scored_rows": sum(1 for row in rows if row["scores"]["overall"] is not None),
        "total_rows": len(rows),
        "by_arm": by_arm,
        "counts": counts,
        "pairwise_overall": pairs,
        "note": (
            "Scores are human judgements; empty cells are not imputed. "
            "A/B/C quality is only reported when a live run has actually been "
            "scored."
        ),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scores", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    rows = load_rows(Path(args.scores))
    summary = summarise(rows)
    output = Path(args.out).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if summary["scored_rows"] == 0:
        print("no manual scores yet; template written but no quality conclusions drawn")
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2 if args.pretty else None))
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

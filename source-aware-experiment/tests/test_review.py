"""Manual-review summarisation tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import review  # noqa: E402


def write_csv(path: Path, rows: list[dict]) -> None:
    import csv

    fields = ["case_id", "key", "arm"] + list(review.SCORE_FIELDS) + ["reviewer", "notes"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def loaded(rows: List[dict]) -> List[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "scores.csv"
        write_csv(path, rows)
        return review.load_rows(path)


def row(case: str, arm: str, overall: int, placeholders: int = 4) -> dict:
    return {
        "case_id": case,
        "key": "STR_X",
        "arm": arm,
        "context_sense": 4,
        "terminology": 4,
        "placeholders": placeholders,
        "fluency": 4,
        "overall": overall,
        "reviewer": "r1",
        "notes": "",
    }


class ReviewTests(unittest.TestCase):
    def test_summary_computes_pairwise_win_rates(self) -> None:
        rows = [row("a", "A", 2), row("a", "B", 3), row("a", "C", 5), row("b", "A", 4), row("b", "C", 3)]
        summary = review.summarise(loaded(rows))
        self.assertEqual(summary["scored_rows"], 5)
        self.assertAlmostEqual(summary["by_arm"]["C"]["overall"], 4.0)
        self.assertEqual(summary["pairwise_overall"]["C_vs_A"]["comparable_cases"], 2)
        self.assertEqual(summary["pairwise_overall"]["C_vs_A"]["left_wins"], 1)
        self.assertEqual(summary["pairwise_overall"]["C_vs_A"]["right_wins"], 1)
        self.assertEqual(summary["pairwise_overall"]["C_vs_B"]["comparable_cases"], 1)

    def test_empty_scores_are_not_imputed(self) -> None:
        rows = [row("a", "A", 0)]
        rows[0]["overall"] = ""
        summary = review.summarise(loaded(rows))
        self.assertEqual(summary["scored_rows"], 0)
        self.assertIsNone(summary["by_arm"]["A"]["overall"])

    def test_invalid_scores_are_rejected(self) -> None:
        row_bad = row("a", "A", 5)
        row_bad["overall"] = 9
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scores.csv"
            write_csv(path, [row_bad])
            with self.assertRaises(ValueError):
                review.load_rows(path)

    def test_cli_writes_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scores = Path(tmp) / "scores.csv"
            summary_path = Path(tmp) / "summary.json"
            write_csv(scores, [row("a", "A", 3), row("a", "C", 5)])
            code = review.main(["--scores", str(scores), "--out", str(summary_path)])
            self.assertEqual(code, 0)
            self.assertTrue(summary_path.is_file())
            text = summary_path.read_text(encoding="utf-8")
            self.assertIn('"C_vs_A"', text)


if __name__ == "__main__":
    unittest.main()

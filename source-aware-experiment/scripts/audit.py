#!/usr/bin/env python3
"""Run the real-corpus retrieval audit against a pinned OpenTTD checkout.

For each hand-audited case the script compares:

* the practical locator (direct token, cargo macro, settings range, verified
  arithmetic range), and
* a deliberately naive baseline (token substring + display-text substring
  over all evidence files, including the string-table definition row).

The output contains real ``path:line`` evidence, retrieval status and
correctness; it never invents a hit.  It does not call any model.

Usage:
    python3 scripts/audit.py --corpus .corpus/openttd-15.3 \
        --output audit/results.json
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from srcaware.corpus import CorpusSpec, OpenTTDCorpus  # noqa: E402
from srcaware.openttd import OpenTTDLocator, placeholder_tokens  # noqa: E402

STYLE_RE = re.compile(r"\{[^{}]*\}")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_location(value: str) -> Tuple[str, int]:
    path, _, line = value.rpartition(":")
    return path, int(line)


class NaiveBaseline:
    """Token-substring + display-text substring, no definition/reference split."""

    def __init__(self, corpus: OpenTTDCorpus, locator: OpenTTDLocator) -> None:
        self.corpus = corpus
        self.locator = locator
        self._all_lines: List[Tuple[str, int, str]] = []
        for path in corpus.evidence_files():
            for line_no, line in enumerate(locator.lines(path), 1):
                self._all_lines.append((path, line_no, line))
        # The naive scanner reads the definition table too; that is exactly the
        # weakness we want to measure.
        for entry in corpus.entries:
            # Keep the key visible so the naive token substring scan also
            # returns the definition row, which is noise for a usage query.
            self._all_lines.append((entry.file, entry.line, f"{entry.key} :{entry.text}"))

    def scan(self, key: str, text: str, limit: int = 100) -> List[Tuple[str, int]]:
        plain = STYLE_RE.sub("", text).strip()
        token_sites: List[Tuple[str, int]] = []
        text_sites: List[Tuple[str, int]] = []
        for path, line_no, line in self._all_lines:
            if key in line and len(token_sites) < limit:
                token_sites.append((path, line_no))
            if len(plain) >= 3 and plain in line and len(text_sites) < limit:
                text_sites.append((path, line_no))
        found: List[Tuple[str, int]] = []
        for site in token_sites + text_sites:
            if site not in found:
                found.append(site)
        return found


def location_in(needle: str, haystack: Iterable[Tuple[str, int]]) -> bool:
    path, line = parse_location(needle)
    return any(candidate_path == path and candidate_line == line for candidate_path, candidate_line in haystack)


def direct_locations(locator: OpenTTDLocator, key: str) -> set[Tuple[str, int]]:
    return {(ref.path, ref.line) for ref in locator.direct_refs(key)}


def summarise(cases: List[dict], results: List[dict]) -> dict:
    total = len(results)
    practical_hits = sum(1 for item in results if item["practical"]["hit"])
    practical_correct_missing = sum(1 for item in results if item["practical"]["correctly_missing"])
    unresolved_failures = sum(
        1 for item in results if item["practical"]["expected_exists_but_missing"]
    )
    naive_hits = sum(1 for item in results if item["naive"]["hit"])
    definition_noise = sum(1 for item in results if item["naive"]["definition_noise"])
    confuser_noise = sum(1 for item in results if item["naive"]["confuser_noise"])
    practical_wrong = sum(1 for item in results if item["practical"]["wrong_association"])
    naive_wrong = sum(1 for item in results if item["naive"]["wrong_association"])
    by_category: Dict[str, Dict[str, int]] = {}
    for item in results:
        bucket = by_category.setdefault(
            item["category"], {"cases": 0, "practical_hits": 0, "naive_hits": 0}
        )
        bucket["cases"] += 1
        bucket["practical_hits"] += int(item["practical"]["hit"])
        bucket["naive_hits"] += int(item["naive"]["hit"])
    status_counts: Dict[str, int] = {}
    for item in results:
        status = item["practical"]["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "cases": total,
        "practical_hits": practical_hits,
        "practical_correctly_missing": practical_correct_missing,
        "practical_unresolved_failures": unresolved_failures,
        "practical_wrong_associations": practical_wrong,
        "naive_hits": naive_hits,
        "naive_definition_noise_cases": definition_noise,
        "naive_confuser_noise_cases": confuser_noise,
        "naive_wrong_associations": naive_wrong,
        "practical_status_counts": dict(sorted(status_counts.items())),
        "by_category": dict(sorted(by_category.items())),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, help="path to the extracted OpenTTD 15.3 tree")
    parser.add_argument("--cases", default=str(ROOT / "audit" / "cases.json"))
    parser.add_argument("--output", default=str(ROOT / "audit" / "results.json"))
    args = parser.parse_args(argv)

    cases_path = Path(args.cases).expanduser().resolve()
    cases_doc = load_json(cases_path)
    corpus_meta = load_json((ROOT / "audit" / "corpus.json").resolve())
    spec = CorpusSpec(
        project=corpus_meta["project"],
        version=corpus_meta["version"],
        commit=corpus_meta["commit"],
        license=corpus_meta["license"],
        repo_url=corpus_meta["repo_url"],
        archive_sha256=corpus_meta.get("archive_sha256"),
    )
    corpus = OpenTTDCorpus(Path(args.corpus), spec)
    corpus.verify_spec()
    locator = OpenTTDLocator(corpus)
    baseline = NaiveBaseline(corpus, locator)

    results: List[dict] = []
    for case in cases_doc["cases"]:
        key = case["key"]
        bundle = locator.lookup(key)
        expected = case.get("expected_locations", [])
        expected_status = case.get("expected_status")
        practical_sites = [(ref.path, ref.line) for ref in bundle.refs]
        hit = any(location_in(location, practical_sites) for location in expected)
        correctly_missing = (
            expected_status == "missing"
            and not expected
            and bundle.status in ("missing", "dynamic_unresolved")
        )
        expected_exists_but_missing = (
            bool(expected) and not hit and bundle.status in ("missing", "dynamic_unresolved")
        )
        confuser_keys = case.get("confuser_keys", [])
        confuser_sites: set[Tuple[str, int]] = set()
        for confuser in confuser_keys:
            confuser_sites |= direct_locations(locator, confuser)
        wrong = any(site in confuser_sites for site in practical_sites)

        naive_sites = baseline.scan(key, bundle.text)
        naive_hit = any(location_in(location, naive_sites) for location in expected)
        naive_definition_noise = any(
            path == "src/lang/english.txt" and line == corpus.entry_by_key[key].line
            for path, line in naive_sites
        )
        naive_confuser_noise = any(site in confuser_sites for site in naive_sites)

        results.append(
            {
                "id": case["id"],
                "key": key,
                "category": case["category"],
                "text": bundle.text,
                "expected_context": case["expected_context"],
                "expected_locations": expected,
                "notes": case.get("notes", ""),
                "placeholders": placeholder_tokens(bundle.text),
                "practical": {
                    "status": bundle.status,
                    "confidence": bundle.confidence,
                    "hit": hit,
                    "correctly_missing": correctly_missing,
                    "expected_exists_but_missing": expected_exists_but_missing,
                    "wrong_association": wrong,
                    "evidence": [
                        {
                            "path": ref.path,
                            "line": ref.line,
                            "kind": ref.kind,
                            "scope": ref.scope,
                            "call": ref.call,
                            "args": list(ref.args),
                            "relation": ref.relation,
                        }
                        for ref in bundle.refs
                    ],
                    "notes": bundle.notes,
                },
                "naive": {
                    "hit": naive_hit,
                    "definition_noise": naive_definition_noise,
                    "confuser_noise": naive_confuser_noise,
                    "wrong_association": naive_confuser_noise,
                    "site_count": len(naive_sites),
                    "sites": [
                        {"path": path, "line": line} for path, line in naive_sites[:12]
                    ],
                },
            }
        )

    summary = summarise(cases_doc["cases"], results)
    payload = {
        "corpus": corpus_meta,
        "schema": 1,
        "summary": summary,
        "locator": locator.summary(),
        "cases": results,
    }
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        f"cases={summary['cases']} practical_hits={summary['practical_hits']} "
        f"correctly_missing={summary['practical_correctly_missing']} "
        f"unresolved_failures={summary['practical_unresolved_failures']} "
        f"naive_hits={summary['naive_hits']} "
        f"naive_definition_noise={summary['naive_definition_noise_cases']} "
        f"naive_confuser_noise={summary['naive_confuser_noise_cases']}"
    )
    for category, bucket in summary["by_category"].items():
        print(
            f"  {category:18s} cases={bucket['cases']:2d} "
            f"practical={bucket['practical_hits']:2d} naive={bucket['naive_hits']:2d}"
        )
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

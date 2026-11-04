#!/usr/bin/env python3
"""Build and run the A/B/C translation experiment.

Default is a side-effect-free dry run: it retrieves evidence, builds the three
prompts, validates leakage guards and writes a review template.  A live model
call requires an explicit ``--live``, an API key in an environment variable and
a positive token budget; without a key nothing is called and the command exits
non-zero instead of fabricating results.

Usage:
    # no key needed, no network
    python3 scripts/evaluate.py --corpus .corpus/openttd-15.3 \
        --out runs/dryrun-1 --dry-run

    # explicit live run (only when a key is provided in the environment)
    python3 scripts/evaluate.py --corpus .corpus/openttd-15.3 \
        --out runs/live-1 --live --model deepseek-chat \
        --max-total-tokens 20000
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from srcaware.corpus import CorpusSpec, OpenTTDCorpus  # noqa: E402
from srcaware.dataset import (  # noqa: E402
    RUBRIC_COLUMNS,
    CaseRecord,
    build_records,
    file_sha256,
    load_dataset,
    parse_cases,
)
from srcaware.live import (  # noqa: E402
    Budget,
    BudgetExceeded,
    ChatResult,
    LiveConfig,
    LiveError,
    MissingApiKey,
    Transport,
    chat,
    estimate_tokens,
    parse_translation,
)
from srcaware.openttd import OpenTTDLocator  # noqa: E402
from srcaware.prompts import (  # noqa: E402
    PROMPT_VERSION,
    Prompt,
    check_arm_invariants,
    truncate_evidence_for_budget,
)

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"
API_KEY_ENV = "SOURCEAWARE_API_KEY"


def prompt_sha256(prompt: Prompt) -> str:
    payload = json.dumps(
        {"system": prompt.system, "user": prompt.user}, sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def new_run_id(mode: str, dataset_sha: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{mode}-{dataset_sha[:8]}"


def prepare_records(
    corpus: OpenTTDCorpus,
    cases_path: Path,
    target_locale: str,
    max_context_chars: int,
) -> Tuple[List[CaseRecord], dict, str]:
    data = load_dataset(cases_path)
    cases = parse_cases(data)
    locator = OpenTTDLocator(corpus)
    records = build_records(corpus, locator, cases, target_locale)
    for record in records:
        check_arm_invariants(record.prompts)
        c_prompt = record.prompts["C"]
        record.prompts["C"] = truncate_evidence_for_budget(c_prompt, max_context_chars)
    return records, data, locator.summary()


def write_prompts(path: Path, records: Sequence[CaseRecord], target_locale: str) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            for arm in ("A", "B", "C"):
                prompt = record.prompts[arm]
                row = {
                    "case_id": record.case.id,
                    "key": record.case.key,
                    "arm": arm,
                    "prompt_version": PROMPT_VERSION,
                    "target_locale": target_locale,
                    "system": prompt.system,
                    "user": prompt.user,
                    "prompt_sha256": prompt_sha256(prompt),
                    "evidence_ids": list(prompt.evidence_ids),
                    "retrieval_status": record.bundle.status,
                }
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_review_template(path: Path, records: Sequence[CaseRecord]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RUBRIC_COLUMNS)
        writer.writeheader()
        for record in records:
            for arm in ("A", "B", "C"):
                writer.writerow(
                    {
                        "case_id": record.case.id,
                        "key": record.case.key,
                        "arm": arm,
                        "source_text": record.bundle.text,
                        "expected_context": record.case.expected_context,
                        "translation": "",
                        "context_sense": "",
                        "terminology": "",
                        "placeholders": "",
                        "fluency": "",
                        "overall": "",
                        "reviewer": "",
                        "notes": "",
                    }
                )


def dry_run_results(records: Sequence[CaseRecord]) -> List[dict]:
    rows: List[dict] = []
    for record in records:
        for arm in ("A", "B", "C"):
            prompt = record.prompts[arm]
            rows.append(
                {
                    "case_id": record.case.id,
                    "key": record.case.key,
                    "arm": arm,
                    "status": "not_called",
                    "reason": "dry_run: live model experiment was not executed",
                    "prompt_sha256": prompt_sha256(prompt),
                    "evidence_ids": list(prompt.evidence_ids),
                }
            )
    return rows


def leakage_checks(
    corpus: OpenTTDCorpus, records: Sequence[CaseRecord]
) -> Dict[str, object]:
    offending: List[str] = []
    for record in records:
        for evidence_id in record.bundle.evidence_ids:
            path = evidence_id.rsplit(":", 2)[0]
            if not corpus.is_evidence_path(path):
                offending.append(evidence_id)
    return {
        "evidence_paths_allowlisted": not offending,
        "offending_evidence_ids": offending,
        "no_target_language_in_prompts": True,
        "string_table_read": "src/lang/english.txt only",
        "target_language_tables_read": [],
        "note": (
            "The corpus reader denies every src/lang file except the English "
            "source table; retrieval never touches translated tables. Prompts "
            "are additionally scanned for CJK text."
        ),
    }


def _manifest_base(
    mode: str,
    run_id: str,
    corpus_meta: dict,
    dataset_path: Path,
    dataset_sha: str,
    records: Sequence[CaseRecord],
    target_locale: str,
    locator_summary: dict,
    checks: dict,
) -> dict:
    return {
        "schema": 1,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "live_executed": mode == "live",
        "prompt_version": PROMPT_VERSION,
        "target_locale": target_locale,
        "model": None,
        "corpus": corpus_meta,
        "dataset": {
            "path": str(dataset_path),
            "sha256": dataset_sha,
            "cases": len(records),
            "prompts": len(records) * 3,
        },
        "locator": locator_summary,
        "leakage_checks": checks,
        "totals": {},
        "budget": None,
        "aborted": False,
        "abort_reason": None,
    }


def ensure_output_dir(path: Path, force: bool) -> None:
    if path.exists() and any(path.iterdir()):
        if not force:
            raise SystemExit(
                f"output directory is not empty: {path} (choose a new --out or pass --force)"
            )
    path.mkdir(parents=True, exist_ok=True)


def write_dry_run(
    corpus: OpenTTDCorpus,
    corpus_meta: dict,
    cases_path: Path,
    out_dir: Path,
    records: Sequence[CaseRecord],
    dataset_sha: str,
    target_locale: str,
    locator_summary: dict,
    force: bool,
) -> dict:
    ensure_output_dir(out_dir, force)
    checks = leakage_checks(corpus, records)
    run_id = new_run_id("dryrun", dataset_sha)
    manifest = _manifest_base(
        "dry_run",
        run_id,
        corpus_meta,
        cases_path,
        dataset_sha,
        records,
        target_locale,
        locator_summary,
        checks,
    )
    manifest["totals"] = {
        "cases": len(records),
        "prompts_built": len(records) * 3,
        "live_calls": 0,
        "note": "Live model experiment NOT executed. No API request was made.",
    }
    write_prompts(out_dir / "prompts.jsonl", records, target_locale)
    write_review_template(out_dir / "review_template.csv", records)
    with (out_dir / "results.jsonl").open("w", encoding="utf-8") as handle:
        for row in dry_run_results(records):
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def run_live(
    corpus: OpenTTDCorpus,
    corpus_meta: dict,
    cases_path: Path,
    out_dir: Path,
    records: Sequence[CaseRecord],
    dataset_sha: str,
    target_locale: str,
    locator_summary: dict,
    force: bool,
    config: LiveConfig,
    budget: Budget,
    transport: Optional[Transport] = None,
) -> dict:
    ensure_output_dir(out_dir, force)
    checks = leakage_checks(corpus, records)
    run_id = new_run_id("live", dataset_sha)
    manifest = _manifest_base(
        "live",
        run_id,
        corpus_meta,
        cases_path,
        dataset_sha,
        records,
        target_locale,
        locator_summary,
        checks,
    )
    manifest["model"] = {
        "base_url": config.base_url,
        "model": config.model,
        "temperature": config.temperature,
        "max_output_tokens": config.max_output_tokens,
        "api_key": "[from environment; not recorded]",
    }
    write_prompts(out_dir / "prompts.jsonl", records, target_locale)
    write_review_template(out_dir / "review_template.csv", records)
    responses: List[dict] = []
    aborted = False
    abort_reason = None
    try:
        with (out_dir / "results.jsonl").open("w", encoding="utf-8") as handle:
            for record in records:
                for arm in ("A", "B", "C"):
                    prompt = record.prompts[arm]
                    estimate = estimate_tokens(prompt.system + "\n" + prompt.user) + config.max_output_tokens
                    try:
                        budget.preflight(estimate)
                    except BudgetExceeded as exc:
                        aborted = True
                        abort_reason = str(exc)
                        break
                    row = {
                        "case_id": record.case.id,
                        "key": record.case.key,
                        "arm": arm,
                        "prompt_version": PROMPT_VERSION,
                        "target_locale": target_locale,
                        "prompt_sha256": prompt_sha256(prompt),
                        "evidence_ids": list(prompt.evidence_ids),
                        "retrieval_status": record.bundle.status,
                    }
                    try:
                        result: ChatResult = chat(prompt.messages(), config, transport)
                    except LiveError as exc:
                        row.update(
                            {
                                "status": "transport_error",
                                "error": str(exc)[:500],
                                "translation": None,
                                "usage": None,
                                "latency_ms": None,
                            }
                        )
                        responses.append(row)
                        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                        aborted = True
                        abort_reason = f"transport error: {exc}"
                        break
                    translation, parse_error = parse_translation(result.text)
                    budget.record(result, fallback_tokens=estimate)
                    row.update(
                        {
                            "status": "ok" if parse_error is None else "parse_error",
                            "translation": translation,
                            "parse_error": parse_error,
                            "raw_response": result.text[:4000],
                            "usage": result.usage,
                            "latency_ms": round(result.latency_ms, 1),
                            "finish_reason": result.finish_reason,
                            "provider_response_id": result.raw_id,
                            "cost_usd": _call_cost(result, config),
                        }
                    )
                    responses.append(row)
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    try:
                        budget.check_after_call()
                    except BudgetExceeded as exc:
                        aborted = True
                        abort_reason = str(exc)
                        break
                if aborted:
                    break
    finally:
        manifest["aborted"] = aborted
        manifest["abort_reason"] = abort_reason
        manifest["budget"] = budget.as_dict()
        manifest["totals"] = {
            "cases": len(records),
            "prompts_built": len(records) * 3,
            "responses_recorded": len(responses),
            "ok": sum(1 for row in responses if row["status"] == "ok"),
            "parse_errors": sum(1 for row in responses if row["status"] == "parse_error"),
            "transport_errors": sum(
                1 for row in responses if row["status"] == "transport_error"
            ),
        }
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return manifest


def _call_cost(result: ChatResult, config: LiveConfig) -> Optional[float]:
    if config.input_price_per_1k is None or config.output_price_per_1k is None:
        return None
    if result.prompt_tokens is None or result.completion_tokens is None:
        return None
    return round(
        result.prompt_tokens / 1000.0 * config.input_price_per_1k
        + result.completion_tokens / 1000.0 * config.output_price_per_1k,
        6,
    )


def load_corpus(path: Path) -> Tuple[OpenTTDCorpus, dict]:
    corpus_meta = json.loads((ROOT / "audit" / "corpus.json").read_text(encoding="utf-8"))
    spec = CorpusSpec(
        project=corpus_meta["project"],
        version=corpus_meta["version"],
        commit=corpus_meta["commit"],
        license=corpus_meta["license"],
        repo_url=corpus_meta["repo_url"],
        archive_sha256=corpus_meta.get("archive_sha256"),
    )
    corpus = OpenTTDCorpus(path, spec)
    corpus.verify_spec()
    return corpus, corpus_meta


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--cases", default=str(ROOT / "audit" / "cases.json"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--target", default="zh-CN")
    parser.add_argument("--dry-run", action="store_true", help="explicit no-network mode (default)")
    parser.add_argument("--live", action="store_true", help="call the configured model endpoint")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--base-url", default=os.environ.get("SOURCEAWARE_LLM_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--api-key-env", default=API_KEY_ENV)
    parser.add_argument("--max-total-tokens", type=int, default=0)
    parser.add_argument("--max-calls", type=int, default=0)
    parser.add_argument("--max-context-chars", type=int, default=4000)
    parser.add_argument("--max-output-tokens", type=int, default=256)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--input-price-per-1k", type=float, default=None)
    parser.add_argument("--output-price-per-1k", type=float, default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    if args.live and args.dry_run:
        parser.error("choose either --dry-run or --live, not both")
    mode = "live" if args.live else "dry_run"
    corpus_path = Path(args.corpus).expanduser().resolve()
    cases_path = Path(args.cases).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    corpus, corpus_meta = load_corpus(corpus_path)
    dataset_sha = file_sha256(cases_path)
    records, data, locator_summary = prepare_records(
        corpus, cases_path, args.target, args.max_context_chars
    )

    if mode == "dry_run":
        manifest = write_dry_run(
            corpus,
            corpus_meta,
            cases_path,
            out_dir,
            records,
            dataset_sha,
            args.target,
            locator_summary,
            args.force,
        )
        print(
            f"dry run wrote {manifest['totals']['prompts_built']} prompts for "
            f"{manifest['totals']['cases']} cases to {out_dir}"
        )
        print("live model experiment NOT executed (no API request was made)")
        return 0

    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        print(
            "live model experiment NOT executed: no API key in "
            f"${args.api_key_env}. Nothing was called and nothing was written.",
            file=sys.stderr,
        )
        return 2
    if args.max_total_tokens <= 0:
        print(
            "live run requires --max-total-tokens > 0 so the run can be stopped",
            file=sys.stderr,
        )
        return 2
    max_calls = args.max_calls if args.max_calls > 0 else len(records) * 3
    try:
        config = LiveConfig(
            base_url=args.base_url,
            api_key=api_key,
            model=args.model,
            max_output_tokens=args.max_output_tokens,
            timeout=args.timeout,
            input_price_per_1k=args.input_price_per_1k,
            output_price_per_1k=args.output_price_per_1k,
        )
    except (ValueError, MissingApiKey) as exc:
        print(f"invalid live configuration: {exc}", file=sys.stderr)
        return 2
    budget = Budget(
        max_total_tokens=args.max_total_tokens,
        max_calls=max_calls,
        input_price_per_1k=args.input_price_per_1k,
        output_price_per_1k=args.output_price_per_1k,
    )
    manifest = run_live(
        corpus,
        corpus_meta,
        cases_path,
        out_dir,
        records,
        dataset_sha,
        args.target,
        locator_summary,
        args.force,
        config,
        budget,
    )
    print(
        f"live run wrote {manifest['totals']['responses_recorded']} responses to {out_dir}; "
        f"aborted={manifest['aborted']} tokens={manifest['budget']['total_tokens']}"
    )
    return 0 if not manifest["aborted"] else 3


if __name__ == "__main__":
    raise SystemExit(main())

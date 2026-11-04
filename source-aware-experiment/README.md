# Source-aware localization experiment (P0/P1)

This directory is the P0/P1 follow-up to the synthetic demo in
`../source-aware-demo/`. It uses a real, pinned open-source game corpus instead
of a hand-built demo, and separates two questions:

- **P0 (retrieval):** can a practical locator find the source evidence that
  explains a real string key, and where does it fail?
- **P1 (translation):** does adding that evidence to a model prompt improve
  translation over text-only (A) and text+key (B)?

The real model experiment is **not executed** in this checkout: no API key was
provided and no paid call was made. The dry run builds all three prompt arms,
validates the leakage guards and writes a manual review sheet. It never
fabricates a model answer, latency or cost.

## Quick start

```bash
cd source-aware-experiment
python3 scripts/fetch_corpus.py                 # download + verify + extract
python3 scripts/audit.py --corpus .corpus/openttd-15.3
python3 scripts/evaluate.py --corpus .corpus/openttd-15.3 --out runs/dryrun-1
python3 -m unittest discover -s tests -v
```

No third-party Python package is required. The test suite never downloads the
corpus and never calls a model. `scripts/fetch_corpus.py` is the only script
that fetches; it verifies the committed SHA-256 before extraction.

## Pinned corpus

| field | value |
|---|---|
| project | OpenTTD |
| version | 15.3 |
| commit | `14ec60f248547d4d062a1160f0fc26d742319888` |
| license | GPL-2.0 (`COPYING.md`) |
| string table | `src/lang/english.txt` (4721 StringIDs) |
| archive | `https://codeload.github.com/OpenTTD/OpenTTD/tar.gz/14ec60f...` |
| archive SHA-256 | `df5962cf5fc4938171607a40db69585e2fe3a2a8c8cfe2831862c9e61ff107d7` |

The corpus is not vendored. It is extracted into `.corpus/` (gitignored); this
repository stores only short evidence quotations with `path:line` attribution.
`audit/corpus.json` is the machine-readable manifest.

## What the locator does

`srcaware.corpus` reads only the English source table and allowlists C/C++
sources under `src/`, settings templates under `src/table/settings/*.ini` and
base-set metadata under `media/baseset/*.obg|.obs`. Every other `src/lang/`
table, `src/3rdparty/`, `.po/.mo`, documentation, regression data and
gold/reference directories are denied. `srcaware.openttd` then separates:

- **definition** rows (the string table; never treated as a use);
- **reference** sites (direct tokens, cargo token-pasting macros, settings
  dropdown ranges, verified computed-StringID families, `.obg/.obs` metadata);
- **unresolved** cases (`missing`, `dynamic_unresolved`, `unknown_key`).

Each bundle records the ``path:line``, enclosing scope, call arguments (when
visible), a short snippet and an evidence ID. Confidence is `high` only for a
direct/macro/settings/verified-range proof; a miss is reported as a miss.

## P0 results

33 hand-audited cases from the real corpus: `audit/cases.json`. The full
evidence is in `audit/results.json`; the human-readable report, including six
real failure samples and reproduction commands, is `audit/REPORT.md`.

| metric | practical locator | naive baseline (token + display-text scan) |
|---|---:|---:|
| expected use found | 28 / 33 | 15 / 33 |
| dead string correctly unresolved | 1 | — |
| human-verified use still missed | 4 | 18 |
| definition row returned as if usage | 0 | 33 / 33 |
| same-text confuser merged | 0* | 0* |
| dynamic / computed key found | 11 / 11 | 0 / 11 |

\* The curated cases use distinct keys, so direct-token retrieval cannot merge
two keys; the naive baseline's false-association failure is the definition row
and the same-text text search, not a key collision. This is discussed in the
report rather than hidden.

## P1 A/B/C design

| arm | prompt content |
|---|---|
| A | English source text only |
| B | string key + English source text |
| C | string key + English source text + retrieved source evidence |

Held constant: model, target locale (`zh-CN`), system prompt, temperature 0,
output limit, source text, prompt version `p1-v1`. The only difference is the
key and evidence blocks. Prompts are written to `runs/<id>/prompts.jsonl`.

The dry run writes `manifest.json`, `prompts.jsonl`, `results.jsonl` (all rows
`not_called`) and `review_template.csv`. The manifest contains the corpus
commit, dataset SHA-256, prompt version, retrieval status, leakage checks and
`"live_executed": false`.

### Live gate

A live run requires all of:

```bash
SOURCEAWARE_API_KEY=... python3 scripts/evaluate.py \
  --corpus .corpus/openttd-15.3 --out runs/live-1 --live \
  --model deepseek-chat --max-total-tokens 20000
```

`--live` without a key exits 2 and writes nothing. The key is read only from
the named environment variable; it is never written to a run directory, a
manifest, a result row or an error message.

For the OpenCode Console endpoint (`deepseek-v4.1-flash`), use a unique output
directory and a three-case smoke run first:

```bash
OUT="runs/live-opencode-$(date -u +%Y%m%dT%H%M%SZ)"
SOURCEAWARE_API_KEY=... python3 scripts/evaluate.py \
  --corpus .corpus/openttd-15.3 --out "$OUT" --live \
  --base-url https://opencode.ai/inference/openai/v1 \
  --model deepseek-v4.1-flash \
  --case-ids placeholder.plane_crash,same_text.cargo_plural,dynamic.colour_pale_green \
  --max-total-tokens 12000 --max-calls 9
```

Only after that smoke run reports real `usage` and no parse/transport error,
expand to the audited 33 cases with a larger explicit budget:

```bash
OUT="runs/live-opencode-full-$(date -u +%Y%m%dT%H%M%SZ)"
SOURCEAWARE_API_KEY=... python3 scripts/evaluate.py \
  --corpus .corpus/openttd-15.3 --out "$OUT" --live \
  --base-url https://opencode.ai/inference/openai/v1 \
  --model deepseek-v4.1-flash \
  --max-total-tokens 80000 --max-calls 99
```

The CLI prints `live_executed`, model, response/usage/parse/transport counts and
the first real response's `usage`, latency and cost. `--case-ids` and
`--limit-cases` are for smoke runs; they do not change system prompts or arm
content. The run is aborted on a
transport error or when the next request would exceed the token/call budget;
partial results and `aborted: true` are preserved. Prices are optional; without
them `cost_usd` is `null` rather than guessed. No live call was made here, so
there is **no A/B/C translation-quality result**.

The manual rubric is fixed before seeing outputs: `context_sense`,
`terminology`, `placeholders`, `fluency`, `overall` (1-5 each). Reviewers fill
`review_template.csv`; `scripts/review.py` only aggregates supplied scores and
does not impute empty cells.

## Leakage

Retrieval is allowlisted to English source files; translated tables cannot be
opened by the corpus reader. Prompts are additionally scanned for CJK text and
the tests cover `src/lang/german.txt` denial. The expected-context column in
`audit/cases.json` is human audit material; it is never placed in a prompt.
`audit/results.json` and the prompt files contain English source snippets only.

## Layout

```
audit/corpus.json    pinned project manifest
audit/cases.json     33 human-audited cases
audit/results.json   generated evidence + metrics
audit/REPORT.md      P0/P1 report, failures, commands, limitations
srcaware/            corpus, locator, prompts, dataset, live transport
scripts/             fetch, audit, evaluate, review
tests/               fixture corpus + unit tests (offline)
```

## License / attribution

OpenTTD is GPL-2.0; the pinned `COPYING.md` is part of the downloaded corpus.
Only short attributed excerpts are stored here. The synthetic fixture under
`tests/fixtures/tiny_openttd/` is test-only and not derived from a real game
build.

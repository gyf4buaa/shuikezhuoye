# OpenCode live smoke: blocked by HTTP 402 (2026-11-04)

## Outcome

A real request was made at 2026-11-04 19:37 China time to OpenCode Console Chat Completions, requesting `deepseek-v4.1-flash` for arm A of `placeholder.plane_crash`. The endpoint returned HTTP 402 after 1451.5 ms. No translation, provider model identifier, token usage or billable usage was returned. The run stopped after **one attempted request**. No A/B/C comparison and no quality improvement are established. The remaining eight smoke calls and all 99 full-run calls were not sent.

HTTP 402 is consistent with a workspace credit, billing or quota problem; it does not by itself establish the exact account condition. [OpenCode billing documentation](https://opencode.ai/v2/docs/console/billing/) says paid requests receive 402 when credits run out, and invoiced workspaces may also receive 402 for a reached credit limit or overdue invoice. Account access/credits must be checked by the owner. Do not substitute an unrequested model or purchase credits automatically.

The initial request from default Python urllib received Cloudflare 403/1010; a no-key POST with `User-Agent: opencode/1.0` reached the inference endpoint and returned the expected 401. The authenticated experiment used the same client identifier and received 402. The [official model documentation](https://opencode.ai/v2/docs/console/models/) lists this model and `/inference/openai/v1/chat/completions`. The live 402 does not establish that authorization, request parameters, model response format, or usage reporting are valid for a successful inference.

## Experiment record

- Fixed corpus: OpenTTD 15.3, commit `14ec60f248547d4d062a1160f0fc26d742319888`, archive SHA-256 verified.
- Smoke cases: `placeholder.plane_crash`, `same_text.cargo_plural`, `dynamic.colour_pale_green`; A = English text, B = text + key, C = text + key + automatically retrieved source evidence.
- Same system prompt, zh-CN target, temperature 0 and 256 output token cap for all arms; nine prompts were built, no target-language table or human expected context was included.
- Smoke limits: 9 requests, 12,000 total tokens. Full run was gated on nine successful responses with usage and no errors; it was not started.
- Official listed rates at the time: $0.30 per million input tokens, $1.20 per million output tokens, cached input $0.006 per million. No provider usage or billing record was returned, so actual cost is **unknown**, not established as zero.
- Original run records are in this directory: `prompts.jsonl`, `results.jsonl`, `manifest.json`, `review_template.csv`, and `execution.log`. The repository copy of the manifest has only its local dataset path normalized. The original raw local records are unchanged.
- The original manifest incorrectly says `budget.calls=0` and `cost_usd=0.0` on transport failure; `results.jsonl` and the 402 response show that one request was attempted. Those counters are not evidence of zero spending. The harness has since been corrected and tested; the original manifest is retained as historical evidence.

## Questions that remain unanswered

There are no model translations to compare: no conclusion is available about whether C improves on B, which keys alone suffice, whether evidence misleads, or incremental tokens, latency, or cost. No human scoring has been performed. See `../REPORT.md` for existing retrieval audits, not translation-quality outcomes.

Known retrieval gaps include runtime vehicle-tooltip offsets, sparse toolbar-widget mappings, month-abbreviation arithmetic, symbolic settings bounds and missing structure-field dataflow to the runtime call site. `missing` is not proof that a string is dead; one sample was genuinely unreferenced but four manually verified uses were missed. Sample selection is curated and not population-representative.

## Resume after billing is resolved

Use the configured `SOURCEAWARE_API_KEY` from the service environment, re-run the three-case smoke in a **new** output directory with `--max-total-tokens 12000 --max-calls 9`, then run 33 cases with `--max-total-tokens 80000 --max-calls 99` only if all smoke responses succeed with complete usage and valid, untruncated translations. Preserve evidence and request records; do not include reference translations in prompts. Conservative token reservation is not a formal guarantee against an opaque provider tokenizer or hidden template; actual billing and token usage require provider records.

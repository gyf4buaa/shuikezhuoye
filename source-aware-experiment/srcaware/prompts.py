"""Prompt construction for the A/B/C source-evidence experiment.

The only difference between the three arms is the evidence supplied to the
model.  System instruction, target locale, model, temperature, output limit and
source text are identical.  Prompt text is generated from the pinned corpus and
the English source string; it never reads a target-language table or a gold
translation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from .openttd import Bundle, Ref, placeholder_tokens

PROMPT_VERSION = "p1-v1"
TARGET_LOCALES: Dict[str, str] = {
    "zh-CN": "Simplified Chinese (China)",
    "ja-JP": "Japanese",
    "de-DE": "German",
    "pt-BR": "Brazilian Portuguese",
}
SYSTEM_PROMPT = (
    "You are a professional video-game localizer. Translate one English UI "
    "string into {locale}. Return exactly one JSON object with the single key "
    '"translation"; do not add explanations, notes or alternative variants.\n'
    "Rules:\n"
    "- Translate only the UI string shown by the user.\n"
    "- Preserve every placeholder exactly as written, including braces: "
    "for example {STRING}, {STRING1}, {NUM}, {COMMA}, {TOWN}, {RAW_STRING}, "
    "and doubled braces if present.\n"
    "- Preserve leading colour/font/control codes such as {BLACK}, {WHITE}, "
    "{BIG_FONT}, {TINY_FONT}, {NBSP}, {} and {P ...}.\n"
    "- Keep it concise and natural for a game interface; match the tone "
    "(news headline, tooltip, button, setting label) shown by the context.\n"
    "- Do not translate identifiers, key names, file paths or source code."
)
MAX_EVIDENCE_REFS = 4
SNIPPET_CHAR_LIMIT = 420


@dataclass(frozen=True)
class Prompt:
    arm: str
    system: str
    user: str
    evidence_ids: Sequence[str]

    def messages(self) -> List[Dict[str, str]]:
        return [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self.user},
        ]


def _source_block(bundle: Bundle) -> str:
    return f'Source text (English):\n"{bundle.text}"\n'


def _key_block(bundle: Bundle) -> str:
    return f"String key: {bundle.key}\n"


def _format_ref(ref: Ref, index: int) -> str:
    header = f"[E{index}] {ref.path}:{ref.line} | {ref.kind}"
    if ref.scope:
        header += f" | scope: {ref.scope}"
    lines = [header]
    if ref.call:
        args = ", ".join(ref.args)
        lines.append(f"call: {ref.call}({args})")
    if ref.relation:
        lines.append(f"relation: {ref.relation}")
    snippet = ref.snippet
    if len(snippet) > SNIPPET_CHAR_LIMIT:
        snippet = snippet[: SNIPPET_CHAR_LIMIT - 3] + "..."
    lines.append(snippet)
    return "\n".join(lines)


def evidence_block(bundle: Bundle, locales: str = "zh-CN") -> str:
    if not bundle.refs:
        return (
            "Retrieved source evidence: none. No verified source use was found "
            "for this key; translate from the key and text only, and do not "
            "invent context.\n"
        )
    parts = [
        "Retrieved source evidence (pinned OpenTTD corpus, English source "
        "only; may be incomplete):"
    ]
    for index, ref in enumerate(bundle.refs[:MAX_EVIDENCE_REFS], 1):
        parts.append(_format_ref(ref, index))
    data = [item["token"] for item in placeholder_tokens(bundle.text) if item["kind"] == "data"]
    if data:
        parts.append(
            "Placeholders that must survive translation: "
            + ", ".join("{" + token + "}" for token in data)
        )
    return "\n".join(parts) + "\n"


def build_prompts(bundle: Bundle, target_locale: str = "zh-CN") -> Dict[str, Prompt]:
    if target_locale not in TARGET_LOCALES:
        raise ValueError(f"unsupported target locale: {target_locale}")
    system = SYSTEM_PROMPT.replace("{locale}", TARGET_LOCALES[target_locale])
    base = _source_block(bundle)
    arm_a = base
    arm_b = _key_block(bundle) + base
    arm_c = _key_block(bundle) + base + evidence_block(bundle)
    if not (arm_a and arm_b and arm_c):
        raise ValueError("empty prompt")
    return {
        "A": Prompt(arm="A", system=system, user=arm_a, evidence_ids=()),
        "B": Prompt(arm="B", system=system, user=arm_b, evidence_ids=()),
        "C": Prompt(
            arm="C",
            system=system,
            user=arm_c,
            evidence_ids=tuple(
                ref.evidence_id for ref in bundle.refs[:MAX_EVIDENCE_REFS]
            ),
        ),
    }


def truncate_evidence_for_budget(prompt: Prompt, max_chars: int) -> Prompt:
    """Deterministic truncation used when a caller sets a context ceiling."""
    if max_chars < 200:
        raise ValueError("max context chars must be at least 200")
    if len(prompt.user) <= max_chars:
        return prompt
    marker = "\n[... evidence truncated ...]"
    user = prompt.user[: max_chars - len(marker)] + marker
    return Prompt(
        arm=prompt.arm,
        system=prompt.system,
        user=user,
        evidence_ids=prompt.evidence_ids,
    )


CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")


def assert_no_target_language(prompt: Prompt) -> None:
    """Refuse prompts containing CJK text for a zh-CN/ja-JP target.

    Evidence comes from English source files, so a CJK character here means a
    translated table leaked into retrieval.  This is a coarse but effective
    guard; the corpus allowlist is the primary defence.
    """
    combined = prompt.system + "\n" + prompt.user
    match = CJK_RE.search(combined)
    if match:
        # The system instruction names the target language in Latin script, so
        # any CJK character is unexpected input, not translation output.
        raise ValueError(
            f"prompt {prompt.arm} contains unexpected CJK text at offset {match.start()}"
        )


def check_arm_invariants(prompts: Dict[str, Prompt]) -> None:
    system = prompts["A"].system
    if prompts["B"].system != system or prompts["C"].system != system:
        raise ValueError("system prompt differs between arms")
    if "String key:" in prompts["A"].user:
        raise ValueError("arm A must not receive the key")
    if "String key:" not in prompts["B"].user or "String key:" not in prompts["C"].user:
        raise ValueError("arms B and C must receive the key")
    if "Retrieved source evidence" in prompts["B"].user:
        raise ValueError("arm B must not receive source evidence")
    if "Retrieved source evidence" not in prompts["C"].user:
        raise ValueError("arm C must receive source evidence")
    for arm, prompt in prompts.items():
        assert_no_target_language(prompt)

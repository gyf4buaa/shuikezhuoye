"""Optional LLM enhancement.

The default engine is deterministic. This module is only used for the
*experimental* register/idiom strategy suggestion, and only when both a key is
configured and the caller explicitly enables live mode. It never runs in tests
or in the demo without a key, and its output is labelled as live in the UI.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .models import StringUnit


def _timeout_from_env() -> float:
    try:
        value = float(os.environ.get("LLM_TIMEOUT", "20") or 20)
    except ValueError:
        return 20.0
    return max(1.0, min(value, 120.0))


@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    timeout: float = 20.0

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            base_url=os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            api_key=os.environ.get("LLM_API_KEY", "").strip(),
            model=os.environ.get("LLM_MODEL", "gpt-4o-mini").strip(),
            timeout=_timeout_from_env(),
        )

    def public(self) -> Dict[str, Any]:
        return {
            "configured": self.enabled,
            "base_url": self.base_url,
            "model": self.model,
            "api_key_present": bool(self.api_key),
        }


SYSTEM_PROMPT = (
    "You are a game localization reviewer. You receive ONE source string that "
    "has been flagged as sarcasm, a meme, slang or marketing language. "
    "Do not translate the whole game and do not invent context. Return strict "
    "JSON with keys: strategy (literal|idiomatic|rewrite|needs_human), "
    "candidate (a target-language candidate or empty string), rationale "
    "(short, in Chinese), confidence (0-1). If the context is insufficient, "
    "use strategy=needs_human and explain what is missing."
)


def suggest_strategy(
    unit: StringUnit,
    locale: str,
    issue_note: str,
    config: Optional[LLMConfig] = None,
) -> Dict[str, Any]:
    """Call an OpenAI-compatible chat endpoint. Errors are returned, not raised."""
    config = config or LLMConfig.from_env()
    if not config.enabled:
        return {"status": "disabled", "detail": "未配置 LLM_API_KEY，使用确定性模式"}
    payload = {
        "model": config.model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "source_locale": "auto",
                        "target_locale": locale,
                        "source": unit.source,
                        "existing_target": unit.target,
                        "issue": issue_note,
                        "key": unit.key,
                        "screen": unit.screen,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }
    request = urllib.request.Request(
        config.base_url + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + config.api_key,
        },
        method="POST",
    )
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            body = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"status": "error", "detail": "LLM 请求失败: %s" % exc, "elapsed_ms": int((time.time() - started) * 1000)}
    elapsed = int((time.time() - started) * 1000)
    try:
        data = json.loads(body)
        content = data["choices"][0]["message"]["content"]
        suggestion = _parse_json_content(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        return {
            "status": "error",
            "detail": "LLM 响应无法解析: %s" % exc,
            "elapsed_ms": elapsed,
        }
    return {
        "status": "ok",
        "suggestion": suggestion,
        "model": config.model,
        "elapsed_ms": elapsed,
        "live": True,
    }


def _parse_json_content(content: str) -> Dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("响应中没有 JSON 对象")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("响应 JSON 不是对象")
    return data

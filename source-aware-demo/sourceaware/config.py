"""Configuration for the source-aware localization PoC.

The API key is read from the server process environment only. It is never
accepted from the browser, never written to disk, and never included in an API
response. Without a key the demo runs in retrieval-only mode.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List
from urllib.parse import urlparse

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"

# The comparison endpoint only accepts these fixed locales. This keeps the
# prompt surface small and reproducible.
TARGET_LOCALES: List[Dict[str, str]] = [
    {"code": "pt-BR", "name": "Brazilian Portuguese"},
    {"code": "ru-RU", "name": "Russian"},
    {"code": "ja-JP", "name": "Japanese"},
    {"code": "de-DE", "name": "German"},
    {"code": "fr-FR", "name": "French"},
]
TARGET_LOCALE_NAMES = {item["code"]: item["name"] for item in TARGET_LOCALES}


def _bounded_float(name: str, default: float, low: float, high: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(low, min(high, value))


def _bounded_int(name: str, default: int, low: int, high: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(low, min(high, value))


@dataclass(frozen=True)
class LLMConfig:
    """OpenAI-compatible endpoint settings."""

    base_url: str
    api_key: str = field(repr=False)
    model: str
    timeout: float
    max_output_tokens: int
    max_context_chars: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", self.base_url.strip().rstrip("/"))

    @property
    def enabled(self) -> bool:
        parsed = urlparse(self.base_url)
        return bool(
            self.api_key
            and self.model
            and parsed.scheme in ("http", "https")
            and parsed.netloc
        )

    @property
    def base_host(self) -> str:
        parsed = urlparse(self.base_url)
        return parsed.netloc or "(invalid)"

    def public(self) -> Dict[str, Any]:
        """Return browser-safe settings; the key itself never appears."""
        return {
            "configured": self.enabled,
            "model": self.model,
            "base_host": self.base_host,
            "api_key_present": bool(self.api_key),
            "timeout_seconds": self.timeout,
            "max_output_tokens": self.max_output_tokens,
            "max_context_chars": self.max_context_chars,
        }

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            base_url=os.environ.get("SOURCEAWARE_LLM_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/"),
            api_key=os.environ.get("SOURCEAWARE_API_KEY", "").strip(),
            model=os.environ.get("SOURCEAWARE_LLM_MODEL", DEFAULT_MODEL).strip(),
            timeout=_bounded_float("SOURCEAWARE_TIMEOUT_SECONDS", 20.0, 1.0, 120.0),
            max_output_tokens=_bounded_int("SOURCEAWARE_MAX_OUTPUT_TOKENS", 240, 32, 1024),
            max_context_chars=_bounded_int("SOURCEAWARE_MAX_CONTEXT_CHARS", 4000, 500, 20000),
        )

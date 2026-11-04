"""OpenAI-compatible chat transport with hard budget accounting.

No network call is made by the dry-run path.  The live path is only reachable
through an explicit CLI flag, a key in an environment variable, and a positive
token budget.  Keys are never written to disk or included in an error string.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


class LiveError(Exception):
    def __init__(self, message: str, *, latency_ms: Optional[float] = None,
                 model: Optional[str] = None, usage: Optional[Dict[str, Any]] = None,
                 raw_response: Optional[str] = None) -> None:
        super().__init__(message)
        self.latency_ms = latency_ms
        self.model = model
        self.usage = usage
        self.raw_response = raw_response


class BudgetExceeded(LiveError):
    pass


class MissingApiKey(LiveError):
    pass


@dataclass(frozen=True)
class LiveConfig:
    base_url: str
    api_key: str = field(repr=False)
    model: str
    temperature: float = 0.0
    max_output_tokens: int = 256
    timeout: float = 60.0
    input_price_per_1k: Optional[float] = None
    output_price_per_1k: Optional[float] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", self.base_url.strip().rstrip("/"))
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must be http(s)")
        if not self.api_key:
            raise MissingApiKey("API key is empty")
        if not self.model:
            raise ValueError("model is required")
        if not (0.0 <= self.temperature <= 2.0):
            raise ValueError("temperature out of range")
        if self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")


@dataclass
class ChatResult:
    text: str
    usage: Dict[str, Any]
    latency_ms: float
    finish_reason: Optional[str]
    raw_id: Optional[str] = None
    model: Optional[str] = None

    @property
    def prompt_tokens(self) -> Optional[int]:
        value = self.usage.get("prompt_tokens")
        return int(value) if isinstance(value, (int, float)) and value >= 0 else None

    @property
    def completion_tokens(self) -> Optional[int]:
        value = self.usage.get("completion_tokens")
        return int(value) if isinstance(value, (int, float)) and value >= 0 else None

    @property
    def total_tokens(self) -> Optional[int]:
        value = self.usage.get("total_tokens")
        if isinstance(value, (int, float)):
            return int(value)
        prompt, completion = self.prompt_tokens, self.completion_tokens
        if prompt is not None and completion is not None:
            return prompt + completion
        return None


def estimate_tokens(text: str) -> int:
    """Conservative upper estimate: UTF-8 bytes plus chat framing overhead."""
    return max(1, len(text.encode("utf-8")))


def estimate_messages_tokens(messages: List[Dict[str, str]]) -> int:
    # Byte-level tokenization is the conservative content bound; reserve 32
    # tokens per message plus a final framing allowance for provider templates.
    return sum(estimate_tokens(m.get("role", "") + m.get("content", "")) + 32 for m in messages) + 16


def _redact(value: Any, secret: str) -> Any:
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    return value


def _default_transport(
    url: str, headers: Dict[str, str], payload: dict, timeout: float
) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        # Provider bodies can echo request headers or other sensitive data.
        raise LiveError(f"HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise LiveError("network error") from None
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise LiveError("endpoint returned non-JSON") from exc


Transport = Callable[[str, Dict[str, str], dict, float], dict]


def chat(
    messages: List[Dict[str, str]],
    config: LiveConfig,
    transport: Optional[Transport] = None,
) -> ChatResult:
    transport = transport or _default_transport
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": config.max_output_tokens,
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "opencode/1.0",
        "Authorization": f"Bearer {config.api_key}",
    }
    started = time.monotonic()
    try:
        data = transport(config.base_url + "/chat/completions", headers, payload, config.timeout)
    except LiveError as exc:
        latency = (time.monotonic() - started) * 1000.0
        # Keep only sanitized message text; never propagate a chained error
        # that might contain the Authorization header.
        raise LiveError(str(exc).replace(config.api_key, "[redacted]"), latency_ms=latency) from None
    except Exception as exc:
        latency = (time.monotonic() - started) * 1000.0
        raise LiveError(f"transport failed: {type(exc).__name__}", latency_ms=latency) from None
    latency_ms = (time.monotonic() - started) * 1000.0
    choices = data.get("choices") if isinstance(data, dict) else None
    if not choices:
        raise LiveError(
            "endpoint response has no choices", latency_ms=latency_ms,
            model=data.get("model") if isinstance(data, dict) and isinstance(data.get("model"), str) else None,
            usage=_redact(data.get("usage"), config.api_key) if isinstance(data, dict) and isinstance(data.get("usage"), dict) else None,
            raw_response=json.dumps(_redact(data, config.api_key), ensure_ascii=False)[:4000] if isinstance(data, dict) else None,
        )
    first = choices[0] or {}
    message = first.get("message") or {}
    content = message.get("content")
    if not isinstance(content, str):
        raise LiveError(
            "endpoint response has no text content", latency_ms=latency_ms,
            model=data.get("model") if isinstance(data, dict) and isinstance(data.get("model"), str) else None,
            usage=_redact(data.get("usage"), config.api_key) if isinstance(data, dict) and isinstance(data.get("usage"), dict) else None,
            raw_response=json.dumps(_redact(data, config.api_key), ensure_ascii=False)[:4000] if isinstance(data, dict) else None,
        )
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return ChatResult(
        text=content.replace(config.api_key, "[redacted]"),
        usage=_redact(usage, config.api_key),
        latency_ms=latency_ms,
        finish_reason=first.get("finish_reason"),
        raw_id=data.get("id") if isinstance(data.get("id"), str) else None,
        model=data.get("model") if isinstance(data.get("model"), str) else None,
    )


def parse_translation(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract ``translation`` from the required JSON object.

    Returns ``(translation, error)``.  A malformed answer is recorded as a
    failure rather than repaired by another model call.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:]
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc.msg}"
    if not isinstance(data, dict):
        return None, "response JSON is not an object"
    value = data.get("translation")
    if not isinstance(value, str) or not value.strip():
        return None, "response JSON has no non-empty 'translation'"
    return value.strip(), None


class Budget:
    """Hard token/call budget with preflight and post-call accounting."""

    def __init__(
        self,
        max_total_tokens: int,
        max_calls: int,
        input_price_per_1k: Optional[float] = None,
        output_price_per_1k: Optional[float] = None,
    ) -> None:
        if max_total_tokens <= 0:
            raise ValueError("max_total_tokens must be positive")
        if max_calls <= 0:
            raise ValueError("max_calls must be positive")
        self.max_total_tokens = max_total_tokens
        self.max_calls = max_calls
        self.input_price_per_1k = input_price_per_1k
        self.output_price_per_1k = output_price_per_1k
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.unknown_usage_calls = 0
        self.unknown_estimated_tokens = 0
        self._known_cost_usd = 0.0
        self._pending_calls = 0
        self._unknown_cost = False

    @property
    def cost_usd(self) -> Optional[float]:
        if not self._priced or self._unknown_cost or self._pending_calls:
            return None
        return self._known_cost_usd

    @property
    def _priced(self) -> bool:
        return self.input_price_per_1k is not None and self.output_price_per_1k is not None

    @property
    def total_tokens(self) -> int:
        # Unknown usage is charged at the preflight estimate so an endpoint
        # that omits usage cannot silently bypass the cap.
        return self.prompt_tokens + self.completion_tokens + self.unknown_estimated_tokens

    def preflight(self, estimated_prompt_tokens: int) -> None:
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"call budget reached ({self.max_calls})")
        projected = self.total_tokens + estimated_prompt_tokens
        if projected > self.max_total_tokens:
            raise BudgetExceeded(
                f"token budget would be exceeded: {projected} > {self.max_total_tokens}"
            )

    def start_call(self) -> None:
        """Count an attempted request before entering the transport."""
        self.calls += 1
        self._pending_calls += 1

    def record_failure(self, fallback_tokens: Optional[int] = None) -> None:
        if self._pending_calls:
            self._pending_calls -= 1
        self.unknown_usage_calls += 1
        self.unknown_estimated_tokens += int(fallback_tokens or 0)
        self._unknown_cost = True

    def record(self, result: ChatResult, fallback_tokens: Optional[int] = None) -> None:
        if self._pending_calls:
            self._pending_calls -= 1
        else:
            # Preserve compatibility for callers that record without an
            # explicit start_call().
            self.calls += 1
        prompt = result.prompt_tokens
        completion = result.completion_tokens
        if prompt is None or completion is None:
            self.unknown_usage_calls += 1
            self.unknown_estimated_tokens += int(fallback_tokens or 0)
            # A partial total would understate the bill; report it as unknown.
            self._unknown_cost = True
            return
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        if self._priced:
            self._known_cost_usd += (
                prompt / 1000.0 * float(self.input_price_per_1k)
                + completion / 1000.0 * float(self.output_price_per_1k)
            )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "max_total_tokens": self.max_total_tokens,
            "max_calls": self.max_calls,
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "unknown_usage_calls": self.unknown_usage_calls,
            "unknown_estimated_tokens": self.unknown_estimated_tokens,
            "input_price_per_1k": self.input_price_per_1k,
            "output_price_per_1k": self.output_price_per_1k,
            "cost_usd": round(self.cost_usd, 6) if self.cost_usd is not None else None,
        }

    def check_after_call(self) -> None:
        if self.total_tokens > self.max_total_tokens:
            raise BudgetExceeded(
                f"token budget exceeded after call: {self.total_tokens} > {self.max_total_tokens}"
            )

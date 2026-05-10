"""Anthropic API direct — без overhead'а Claude Code, дёшево через Haiku."""
from __future__ import annotations

import os
import time
from typing import Optional

from anthropic import Anthropic

from .types import LLMProvider, LLMResponse


# https://www.anthropic.com/pricing — per million tokens
PRICING = {
    "claude-haiku-4-5-20251001":   {"in": 1.0,  "out": 5.0,  "cache_read": 0.10, "cache_create": 1.25},
    "claude-sonnet-4-6-20251008":  {"in": 3.0,  "out": 15.0, "cache_read": 0.30, "cache_create": 3.75},
    "claude-opus-4-7":             {"in": 15.0, "out": 75.0, "cache_read": 1.50, "cache_create": 18.75},
}

DEFAULT_MODEL = "claude-haiku-4-5-20251001"


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def list_models(self) -> list[str]:
        return list(PRICING.keys())

    def model_for_tier(self, tier):
        return {
            "high": "claude-opus-4-7",
            "balanced": "claude-sonnet-4-6-20251008",
            "fast": "claude-haiku-4-5-20251001",
        }.get(tier, DEFAULT_MODEL)

    def generate(
        self, *, system: str, user: str,
        max_tokens: int = 2000, response_json: bool = False,
        model: Optional[str] = None,
    ) -> LLMResponse:
        if not self._api_key:
            raise RuntimeError("ANTHROPIC_API_KEY не задан")
        client = Anthropic(api_key=self._api_key)
        model_name = model or DEFAULT_MODEL
        sys_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        user_text = user
        if response_json:
            user_text += "\n\nВерни СТРОГО валидный JSON, без markdown."
        t0 = time.monotonic()
        msg = client.messages.create(
            model=model_name,
            max_tokens=max_tokens,
            system=sys_blocks,
            messages=[{"role": "user", "content": user_text}],
        )
        dt_ms = (time.monotonic() - t0) * 1000
        text = msg.content[0].text if msg.content else ""
        u = msg.usage
        in_t = getattr(u, "input_tokens", 0) or 0
        out_t = getattr(u, "output_tokens", 0) or 0
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        cache_create = getattr(u, "cache_creation_input_tokens", 0) or 0
        price = PRICING.get(model_name, PRICING[DEFAULT_MODEL])
        cost = (
            in_t * price["in"]
            + out_t * price["out"]
            + cache_read * price["cache_read"]
            + cache_create * price["cache_create"]
        ) / 1_000_000
        return LLMResponse(
            text=text,
            input_tokens=in_t, output_tokens=out_t,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_create,
            cost_usd=cost, duration_ms=dt_ms,
            model=model_name, provider=self.name,
        )

"""OpenAI API провайдер — gpt-4.1-mini как дефолт (дешёвый, быстрый, хорош в RU)."""
from __future__ import annotations

import os
import time
from typing import Optional

from openai import OpenAI

from .types import LLMProvider, LLMResponse


# https://openai.com/api/pricing/ — per million tokens (на 2026)
PRICING = {
    "gpt-4.1-mini":       {"in": 0.40,  "out": 1.60},
    "gpt-4.1":            {"in": 2.00,  "out": 8.00},
    "gpt-4.1-nano":       {"in": 0.10,  "out": 0.40},
    "o4-mini":            {"in": 1.10,  "out": 4.40},
    "gpt-5":              {"in": 5.00,  "out": 15.00},
}

DEFAULT_MODEL = "gpt-4.1-mini"


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def list_models(self) -> list[str]:
        return list(PRICING.keys())

    def model_for_tier(self, tier):
        return {
            "high": "gpt-5",
            "balanced": "gpt-4.1",
            "fast": "gpt-4.1-mini",
        }.get(tier, DEFAULT_MODEL)

    def generate(
        self, *, system: str, user: str,
        max_tokens: int = 2000, response_json: bool = False,
        model: Optional[str] = None,
    ) -> LLMResponse:
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY не задан")
        client = OpenAI(api_key=self._api_key)
        model_name = model or DEFAULT_MODEL
        kwargs: dict = {
            "model": model_name,
            "max_completion_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if response_json:
            kwargs["response_format"] = {"type": "json_object"}
        t0 = time.monotonic()
        resp = client.chat.completions.create(**kwargs)
        dt_ms = (time.monotonic() - t0) * 1000
        text = resp.choices[0].message.content or ""
        u = resp.usage
        in_t = getattr(u, "prompt_tokens", 0) or 0
        out_t = getattr(u, "completion_tokens", 0) or 0
        price = PRICING.get(model_name, PRICING[DEFAULT_MODEL])
        cost = (in_t * price["in"] + out_t * price["out"]) / 1_000_000
        return LLMResponse(
            text=text,
            input_tokens=in_t, output_tokens=out_t,
            cost_usd=cost, duration_ms=dt_ms,
            model=model_name, provider=self.name,
        )

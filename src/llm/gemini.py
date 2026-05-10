"""Google Gemini API — самый дешёвый на 2026, есть бесплатный tier (50 RPM на Flash)."""
from __future__ import annotations

import os
import time
from typing import Optional

from google import genai
from google.genai import types as gtypes

from .types import LLMProvider, LLMResponse


# https://ai.google.dev/pricing — per million tokens
PRICING = {
    "gemini-2.5-flash":      {"in": 0.30,  "out": 2.50},
    "gemini-2.5-flash-lite": {"in": 0.10,  "out": 0.40},
    "gemini-2.5-pro":        {"in": 1.25,  "out": 10.00},
}

DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def list_models(self) -> list[str]:
        return list(PRICING.keys())

    def model_for_tier(self, tier):
        return {
            "high": "gemini-2.5-pro",
            "balanced": "gemini-2.5-flash",
            "fast": "gemini-2.5-flash-lite",
        }.get(tier, DEFAULT_MODEL)

    def generate(
        self, *, system: str, user: str,
        max_tokens: int = 2000, response_json: bool = False,
        model: Optional[str] = None,
    ) -> LLMResponse:
        if not self._api_key:
            raise RuntimeError("GEMINI_API_KEY не задан")
        client = genai.Client(api_key=self._api_key)
        model_name = model or DEFAULT_MODEL

        config = gtypes.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            response_mime_type="application/json" if response_json else None,
        )
        t0 = time.monotonic()
        resp = client.models.generate_content(
            model=model_name, contents=user, config=config,
        )
        dt_ms = (time.monotonic() - t0) * 1000

        text = resp.text or ""
        usage = getattr(resp, "usage_metadata", None)
        in_t = getattr(usage, "prompt_token_count", 0) or 0
        out_t = getattr(usage, "candidates_token_count", 0) or 0
        price = PRICING.get(model_name, PRICING[DEFAULT_MODEL])
        cost = (in_t * price["in"] + out_t * price["out"]) / 1_000_000
        return LLMResponse(
            text=text,
            input_tokens=in_t, output_tokens=out_t,
            cost_usd=cost, duration_ms=dt_ms,
            model=model_name, provider=self.name,
        )

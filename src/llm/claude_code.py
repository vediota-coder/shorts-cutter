"""Claude Code CLI — без API-ключа, через подписку. Тащит ~24K overhead контекста."""
from __future__ import annotations

import json
import subprocess
from typing import Optional

from .types import LLMProvider, LLMResponse


class ClaudeCodeProvider(LLMProvider):
    name = "claude-code"

    def is_configured(self) -> bool:
        try:
            r = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=5)
            return r.returncode == 0
        except Exception:
            return False

    def list_models(self) -> list[str]:
        return ["default", "claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"]

    def model_for_tier(self, tier):
        return {
            "high": "claude-opus-4-7",
            "balanced": "claude-sonnet-4-6",
            "fast": "claude-haiku-4-5",
        }.get(tier, "default")

    def generate(
        self, *, system: str, user: str,
        max_tokens: int = 2000, response_json: bool = False,
        model: Optional[str] = None,
    ) -> LLMResponse:
        prompt = f"{system}\n\n---\n\n{user}"
        if response_json:
            prompt += "\n\nВажно: верни СТРОГО валидный JSON, без markdown и пояснений."
        # ⭐ маппинг устаревших имён моделей на актуальные (Anthropic регулярно
        # выводит старые из эксплуатации — старые UI/state могут хранить ".5"-имена).
        DEPRECATED_MAP = {
            "claude-opus-4.5":   "claude-opus-4-7",
            "claude-opus-4-5":   "claude-opus-4-7",
            "claude-sonnet-4.5": "claude-sonnet-4-6",
            "claude-sonnet-4-5": "claude-sonnet-4-6",
            "claude-haiku-4.5":  "claude-haiku-4-5",
            "claude-haiku-4-5":  "claude-haiku-4-5",
            "":                  "claude-haiku-4-5",
            "default":           "claude-haiku-4-5",
        }
        m = (model or "").strip()
        effective_model = DEPRECATED_MAP.get(m, m) if m else "claude-haiku-4-5"
        cmd = ["claude", "-p", prompt, "--output-format", "json", "--model", effective_model]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI failed: {proc.stderr.strip() or proc.stdout.strip()[:200]}")
        envelope = json.loads(proc.stdout)
        text = envelope.get("result") or envelope.get("text") or ""
        usage = envelope.get("usage") or {}
        return LLMResponse(
            text=text,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            cache_read_input_tokens=int(usage.get("cache_read_input_tokens", 0)),
            cache_creation_input_tokens=int(usage.get("cache_creation_input_tokens", 0)),
            cost_usd=float(envelope.get("total_cost_usd", 0)),
            duration_ms=float(envelope.get("duration_ms", 0)),
            model=envelope.get("model") or model or "default",
            provider=self.name,
        )

"""Google Gemini CLI — использует подписку Google AI / Gemini Advanced (бесплатный tier тоже).

Не нужен API-ключ при OAuth. Авторизация: `gemini` (откроется браузер при первом запуске).
Запуск: `gemini -p "prompt" -o json` — ответ в JSON.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .types import LLMProvider, LLMResponse


_AUTH_DIRS = [
    Path.home() / ".gemini",
    Path.home() / ".config" / "gemini",
]


class GeminiCLIProvider(LLMProvider):
    name = "gemini-cli"

    def is_configured(self) -> bool:
        if shutil.which("gemini") is None:
            return False
        # любой признак авторизации
        return any(d.exists() for d in _AUTH_DIRS)

    def list_models(self) -> list[str]:
        return ["default", "gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite"]

    def model_for_tier(self, tier):
        return {
            "high": "gemini-2.5-pro",
            "balanced": "gemini-2.5-flash",
            "fast": "gemini-2.5-flash-lite",
        }.get(tier, "default")

    def generate(
        self, *, system: str, user: str,
        max_tokens: int = 2000, response_json: bool = False,
        model: Optional[str] = None,
    ) -> LLMResponse:
        if shutil.which("gemini") is None:
            raise RuntimeError("gemini CLI не установлен (npm i -g @google/gemini-cli)")
        prompt = f"{system}\n\n---\n\n{user}"
        if response_json:
            prompt += "\n\nКрайне важно: верни СТРОГО валидный JSON без markdown и комментариев."

        cmd = [
            "gemini", "-p", prompt,
            "--output-format", "json",
            "--approval-mode", "yolo",  # без интерактивных запросов
            "--skip-trust",
        ]
        if model and model != "default":
            cmd += ["-m", model]

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(f"gemini failed: {proc.stderr.strip()[:300] or proc.stdout.strip()[:300]}")

        text = ""
        usage_in = usage_out = 0
        model_name = model or "default"
        try:
            envelope = json.loads(proc.stdout)
            text = (
                envelope.get("response")
                or envelope.get("text")
                or envelope.get("result")
                or ""
            )
            u = envelope.get("usage") or envelope.get("usage_metadata") or {}
            usage_in = int(u.get("prompt_token_count") or u.get("input_tokens") or u.get("prompt_tokens") or 0)
            usage_out = int(u.get("candidates_token_count") or u.get("output_tokens") or 0)
            model_name = envelope.get("model") or model_name
        except json.JSONDecodeError:
            text = proc.stdout

        return LLMResponse(
            text=text.strip(),
            input_tokens=usage_in, output_tokens=usage_out,
            cost_usd=0.0,  # подписка — не считаем
            duration_ms=0,
            model=model_name, provider=self.name,
        )

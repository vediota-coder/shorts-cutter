"""OpenAI Codex CLI — использует подписку ChatGPT Plus/Pro/Business.

Не нужен API-ключ. Авторизация: `codex login` (открывает браузер).
Запуск: `codex exec --skip-git-repo-check "prompt"` пишет ответ в stdout.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .types import LLMProvider, LLMResponse


# Codex auth токен по умолчанию лежит в ~/.codex/auth.json
_AUTH_PATH = Path.home() / ".codex" / "auth.json"


class CodexCLIProvider(LLMProvider):
    name = "codex"

    def is_configured(self) -> bool:
        return shutil.which("codex") is not None and _AUTH_PATH.exists()

    def list_models(self) -> list[str]:
        return ["default", "gpt-5", "gpt-5.3-codex", "o4-mini"]

    def model_for_tier(self, tier):
        return {
            "high": "gpt-5",
            "balanced": "gpt-5",
            "fast": "o4-mini",
        }.get(tier, "default")

    def generate(
        self, *, system: str, user: str,
        max_tokens: int = 2000, response_json: bool = False,
        model: Optional[str] = None,
    ) -> LLMResponse:
        if shutil.which("codex") is None:
            raise RuntimeError("codex CLI не установлен (npm i -g @openai/codex)")

        prompt = f"{system}\n\n---\n\n{user}"
        if response_json:
            prompt += "\n\nКрайне важно: верни СТРОГО валидный JSON без markdown и комментариев."

        cmd = [
            "codex", "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--ignore-user-config",  # чтобы кастомные tools/permissions не тянули контекст
            "--output-format", "json",
        ]
        if model and model != "default":
            cmd += ["-m", model]
        cmd += [prompt]

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(f"codex exec failed: {proc.stderr.strip()[:300] or proc.stdout.strip()[:300]}")

        # пробуем JSON envelope; если formatter поменяется — фолбэк на текст
        text = ""
        usage_in = usage_out = 0
        cost = 0.0
        model_name = model or "default"
        try:
            envelope = json.loads(proc.stdout)
            text = envelope.get("result") or envelope.get("output") or envelope.get("text") or ""
            u = envelope.get("usage") or {}
            usage_in = int(u.get("input_tokens") or u.get("prompt_tokens") or 0)
            usage_out = int(u.get("output_tokens") or u.get("completion_tokens") or 0)
            cost = float(envelope.get("total_cost_usd") or 0)
            model_name = envelope.get("model") or model_name
        except json.JSONDecodeError:
            # fallback: stdout — это сам ответ
            text = proc.stdout

        # если завернули в markdown — отчистим
        text = re.sub(r"^```(?:json|text)?\n", "", text)
        text = re.sub(r"\n```$", "", text)

        return LLMResponse(
            text=text.strip(),
            input_tokens=usage_in, output_tokens=usage_out,
            cost_usd=cost, duration_ms=0,
            model=model_name, provider=self.name,
        )

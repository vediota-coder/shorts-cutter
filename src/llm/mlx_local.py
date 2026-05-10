"""F5: Локальный LLM-провайдер через Apple MLX.

Работает офлайн на Apple Silicon (M1+). Используется для лёгких задач
(accent-detection, emoji-выбор), которые не требуют топовой модели.
Picker остаётся cloud — там качество критично.

Установка:
    pip install mlx-lm

Скачать рекомендованную модель (~2 GB, один раз):
    python -c "from mlx_lm import load; load('mlx-community/Qwen2.5-3B-Instruct-4bit')"

Активация через .env:
    LLM_DEFAULT_PROVIDER=mlx-local

Или для конкретного места:
    plan_effects(provider="mlx-local")
"""
from __future__ import annotations

import os
import time
from typing import Optional

from .types import LLMProvider, LLMResponse


DEFAULT_MODEL = "mlx-community/Qwen2.5-3B-Instruct-4bit"
TIER_MAP = {
    "high": DEFAULT_MODEL,
    "low": DEFAULT_MODEL,
}


def _try_import_mlx():
    try:
        from mlx_lm import generate, load  # noqa
        return generate, load
    except ImportError:
        return None, None


class MLXLocalProvider(LLMProvider):
    name = "mlx-local"

    def __init__(self) -> None:
        self._model = None
        self._tokenizer = None
        self._loaded_model_name: Optional[str] = None

    def is_configured(self) -> bool:
        """Готов если можем импортировать mlx_lm. Модель скачается лениво."""
        gen, load = _try_import_mlx()
        return gen is not None and load is not None

    def list_models(self) -> list[str]:
        return [
            "mlx-community/Qwen2.5-3B-Instruct-4bit",
            "mlx-community/Llama-3.2-3B-Instruct-4bit",
            "mlx-community/Llama-3.1-8B-Instruct-4bit",
        ]

    def model_for_tier(self, tier: str) -> str:
        return TIER_MAP.get(tier, DEFAULT_MODEL)

    def _ensure_loaded(self, model_name: str):
        """Lazy-load модели при первом запросе. Кэшируется в self._model."""
        if self._loaded_model_name == model_name and self._model is not None:
            return
        gen, load = _try_import_mlx()
        if load is None:
            raise RuntimeError(
                "mlx_lm не установлен. Установите: pip install mlx-lm"
            )
        # load возвращает (model, tokenizer)
        self._model, self._tokenizer = load(model_name)
        self._loaded_model_name = model_name

    def generate(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 2000,
        response_json: bool = False,
        model: Optional[str] = None,
    ) -> LLMResponse:
        gen, _ = _try_import_mlx()
        if gen is None:
            raise RuntimeError(
                "mlx_lm не установлен. Установите: pip install mlx-lm"
            )

        model_name = model or os.environ.get("MLX_MODEL", DEFAULT_MODEL)
        self._ensure_loaded(model_name)

        # Используем chat-template токенизатора, если есть
        prompt_text = ""
        try:
            messages = [{"role": "system", "content": system},
                       {"role": "user", "content": user}]
            prompt_text = self._tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True,
            )
        except Exception:
            prompt_text = f"{system}\n\n{user}\n\n"

        if response_json:
            prompt_text += "\nReturn ONLY valid JSON, no markdown, no explanations.\n"

        t0 = time.monotonic()
        # mlx_lm.generate сигнатура: generate(model, tokenizer, prompt, max_tokens=...)
        text = gen(
            self._model, self._tokenizer,
            prompt=prompt_text,
            max_tokens=max_tokens,
            verbose=False,
        )
        dur_ms = (time.monotonic() - t0) * 1000

        # mlx-lm в новых версиях возвращает строку без префикса prompt'а.
        # Очищаем на всякий случай:
        if text.startswith(prompt_text):
            text = text[len(prompt_text):]

        in_tokens = len(self._tokenizer.encode(prompt_text))
        out_tokens = len(self._tokenizer.encode(text))
        return LLMResponse(
            text=text.strip(),
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cost_usd=0.0,  # локально → бесплатно
            duration_ms=dur_ms,
            model=model_name,
            provider=self.name,
        )

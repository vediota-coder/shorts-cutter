"""Общий тип ответа от LLM-провайдера и абстрактный интерфейс."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    model: str = ""
    provider: str = ""

    def to_usage_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "duration_ms": int(self.duration_ms),
        }


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def is_configured(self) -> bool:
        """Возвращает True если провайдер готов к использованию (есть ключ/доступ)."""

    @abstractmethod
    def generate(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 2000,
        response_json: bool = False,
        model: Optional[str] = None,
    ) -> LLMResponse:
        """Генерирует ответ. response_json=True — просим JSON-only output."""

    @abstractmethod
    def list_models(self) -> list[str]:
        """Список доступных моделей (для UI)."""

    def model_for_tier(self, tier: "Tier") -> str:
        """Возвращает имя модели для данного tier'а. Переопределяется провайдерами."""
        return ""

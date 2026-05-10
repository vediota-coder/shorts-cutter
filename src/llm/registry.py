"""Реестр LLM-провайдеров: получение по имени + список доступных."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from .anthropic_api import AnthropicProvider
from .claude_code import ClaudeCodeProvider
from .codex_cli import CodexCLIProvider
from .gemini import GeminiProvider
from .gemini_cli import GeminiCLIProvider
from .mlx_local import MLXLocalProvider
from .openai_api import OpenAIProvider
from .types import LLMProvider


# подгружаем .env при первом импорте, чтобы провайдеры видели ключи
_ENV_PATH = Path(__file__).parent.parent.parent / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)


_REGISTRY: dict[str, type[LLMProvider]] = {
    # CLI-провайдеры (по подписке, без API-ключа)
    "claude-code": ClaudeCodeProvider,
    "codex": CodexCLIProvider,
    "gemini-cli": GeminiCLIProvider,
    # API-провайдеры (нужен ключ)
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    # Локальная (offline, через MLX на Apple Silicon)
    "mlx-local": MLXLocalProvider,
}


PROVIDER_META: dict[str, dict] = {
    "claude-code": {"label": "Claude Code (подписка Pro/Max)", "kind": "subscription",
                    "install": "npm i -g @anthropic-ai/claude-code", "auth": "claude login"},
    "codex": {"label": "OpenAI Codex CLI (подписка ChatGPT Plus/Pro)", "kind": "subscription",
              "install": "npm i -g @openai/codex", "auth": "codex login"},
    "gemini-cli": {"label": "Gemini CLI (Google аккаунт / Gemini Advanced)", "kind": "subscription",
                   "install": "npm i -g @google/gemini-cli", "auth": "gemini (затем выбрать Google login)"},
    "anthropic": {"label": "Anthropic API (платно по токенам)", "kind": "api",
                  "install": "—", "auth": "ANTHROPIC_API_KEY в .env"},
    "openai": {"label": "OpenAI API (платно по токенам)", "kind": "api",
               "install": "—", "auth": "OPENAI_API_KEY в .env"},
    "gemini": {"label": "Google Gemini API (есть free tier)", "kind": "api",
               "install": "—", "auth": "GEMINI_API_KEY в .env"},
    "mlx-local": {"label": "MLX Local (offline, Apple Silicon)", "kind": "local",
                  "install": "pip install mlx-lm",
                  "auth": "—, модель скачается при первом запросе (~2GB)"},
}


def get_provider(name: str) -> LLMProvider:
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Неизвестный LLM-провайдер: {name}. Доступны: {list(_REGISTRY)}")
    return cls()


def list_providers_status() -> list[dict]:
    """Список всех провайдеров со статусом готовности (есть ли ключ)."""
    out = []
    for name, cls in _REGISTRY.items():
        prov = cls()
        meta = PROVIDER_META.get(name, {})
        out.append({
            "name": name,
            "label": meta.get("label", name),
            "kind": meta.get("kind", "api"),
            "install": meta.get("install", ""),
            "auth": meta.get("auth", ""),
            "configured": prov.is_configured(),
            "models": prov.list_models(),
        })
    return out


def default_provider() -> str:
    """Имя дефолтного провайдера: первый сконфигурированный, иначе claude-code."""
    pref = os.environ.get("LLM_DEFAULT_PROVIDER", "")
    if pref and pref in _REGISTRY:
        prov = get_provider(pref)
        if prov.is_configured():
            return pref
    # фолбэк: subscription-провайдеры предпочтительнее (бесплатные при наличии подписки)
    for name in ("claude-code", "codex", "gemini-cli", "gemini", "openai", "anthropic"):
        prov = get_provider(name)
        if prov.is_configured():
            return name
    return "claude-code"

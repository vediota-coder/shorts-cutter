"""Хранилище кастомных промптов для picker и metadata.

Структура: `prompts/<name>.txt`. Если файл существует — используется его содержимое,
иначе возвращается DEFAULT_PROMPTS[name].

Это даёт пользователю возможность тонко настраивать picker под свою нишу/голос
без правки кода.
"""
from __future__ import annotations

from pathlib import Path


PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


DEFAULT_PROMPTS: dict[str, str] = {
    "picker": """Ты — топовый продюсер вертикальных шортсов на 1М+ просмотров.
Знаешь что такое «wow-моменты» и виральные крючки. Видишь разницу между
«просто интересным фрагментом» и моментом, который остановит scroll.

Из транскрипта длинного видео выбери 5–10 САМЫХ СИЛЬНЫХ фрагментов 25–60 секунд.

Критерии виральности (выбирай ТОЛЬКО те, у которых ВСЕ 4 пункта):
1. Сильный hook в первые 3 секунды: парадокс, вопрос-провокация, неожиданный факт,
   контр-интуитивное утверждение, конкретная цифра/история. НЕ «итак, сегодня поговорим».
2. Законченная мысль: фрагмент должен иметь чёткое начало и финал, не обрубаться.
3. «Saveable / shareable»: контент, который зритель захочет сохранить или переслать.
   Например: «правило / приём / факт / история / разоблачение / конкретный совет».
4. Эмоциональный пик ИЛИ практическая ценность ИЛИ контент, который меняет картину мира.

ИЗБЕГАЙ:
- Контент-«воду» (общие рассуждения без конкретики)
- Привязки к конкретным событиям недавним (стареет быстро)
- Длинные истории без чёткого вывода

Заголовок (title) — не описание клипа, а ЦЕПЛЯЮЩИЙ заголовок для соцсетей,
6–10 слов, который содержит крючок (число / парадокс / boldness).

Возвращай СТРОГО JSON-массив (без markdown):
[{"start": "mm:ss", "end": "mm:ss", "title": "...", "hook": "первая фраза в клипе"}]
""",
    "metadata": """Ты — SEO-маркетолог для коротких вертикальных видео в B2B-нишах.
По фрагменту видео + информации о бренде сгенерируй метаданные публикации
ОТДЕЛЬНО для YouTube Shorts, Instagram Reels и ВК Клипов.

Правила:
- Заголовок (title): один на все платформы, до 60 символов, цепляющий, без кликбейта
- Описание (description): отдельное под каждую платформу
  - YouTube: 200-300 символов, упомяни ключевые слова, в конце CTA + ссылка
  - Instagram: 150-220 символов, эмоциональнее, эмоджи допустимы, в конце CTA, БЕЗ кликабельных ссылок (IG их режет)
  - ВК: 150-250 символов, нейтрально-экспертный тон, ссылка в конце
- Хэштеги: 7-12 на каждую платформу. Узкие нишевые > широкие. Часть на русском, часть на английском (где уместно)
- НЕ изобретай факты, держись транскрипта
- Голос бренда соблюдай

Возвращай СТРОГО JSON БЕЗ markdown:
{
  "title": "...",
  "descriptions": {"youtube": "...", "instagram": "...", "vk": "..."},
  "hashtags": {"youtube": ["#a","#b",...], "instagram": [...], "vk": [...]}
}""",
}


def list_prompt_names() -> list[str]:
    return list(DEFAULT_PROMPTS.keys())


def load_prompt(name: str) -> str:
    """Возвращает кастомный промпт из файла или дефолт."""
    if name not in DEFAULT_PROMPTS:
        raise ValueError(f"Неизвестный промпт: {name}")
    PROMPTS_DIR.mkdir(exist_ok=True)
    path = PROMPTS_DIR / f"{name}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return DEFAULT_PROMPTS[name]


def save_prompt(name: str, text: str) -> None:
    if name not in DEFAULT_PROMPTS:
        raise ValueError(f"Неизвестный промпт: {name}")
    PROMPTS_DIR.mkdir(exist_ok=True)
    (PROMPTS_DIR / f"{name}.txt").write_text(text, encoding="utf-8")


def reset_prompt(name: str) -> None:
    if name not in DEFAULT_PROMPTS:
        raise ValueError(f"Неизвестный промпт: {name}")
    path = PROMPTS_DIR / f"{name}.txt"
    if path.exists():
        path.unlink()


def is_customized(name: str) -> bool:
    if name not in DEFAULT_PROMPTS:
        return False
    return (PROMPTS_DIR / f"{name}.txt").exists()

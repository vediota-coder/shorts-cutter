"""FastAPI бэкенд для shorts-cutter: загрузка URL или файла, прогресс по WebSocket."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.branding import (
    BRAND_DIR,
    apply_brand, create_brand, delete_brand, list_brands,
    load_brand, save_brand, update_brand_partial,
)
from src.pipeline import ClipResult, run as run_pipeline
from src.subtitles import PRESETS as SUB_PRESETS
from src.transcribe import detect_backend


load_dotenv()
# дублируем под имя, которое использует huggingface_hub
if os.environ.get("HF_TOKEN") and not os.environ.get("HUGGING_FACE_HUB_TOKEN"):
    os.environ["HUGGING_FACE_HUB_TOKEN"] = os.environ["HF_TOKEN"]

ROOT = Path(__file__).parent.parent
WEB_DIR = Path(__file__).parent
WORK_DIR = ROOT / "jobs"
WORK_DIR.mkdir(exist_ok=True)
ENV_FILE = ROOT / ".env"


def _mask_token(t: str) -> str:
    if not t:
        return ""
    if len(t) < 12:
        return "***"
    return f"{t[:4]}…{t[-4:]}"


def _read_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    out = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _write_env(updates: dict[str, str]) -> None:
    current = _read_env()
    current.update(updates)
    ENV_FILE.write_text("\n".join(f"{k}={v}" for k, v in current.items()) + "\n", encoding="utf-8")
    try:
        ENV_FILE.chmod(0o600)
    except OSError:
        pass


@dataclass
class JobState:
    id: str
    status: str = "pending"  # pending | running | done | error
    stage: str = "pending"
    progress: float = 0.0
    log: list[dict] = field(default_factory=list)
    clips: list[dict] = field(default_factory=list)
    error: Optional[str] = None
    title: str = ""        # для отображения в списке
    source_url: str = ""   # URL источника


JOBS: dict[str, JobState] = {}
QUEUES: dict[str, asyncio.Queue] = {}

# Лимит одновременно выполняющихся pipeline'ов: всё что сверх — ждёт в очереди.
# Дефолт 2 — на M4 16 GB реалистичный потолок без OOM. Override через env.
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "2"))
JOB_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_JOBS)


_RES_LABEL_RE = re.compile(r"^(\d+)p$")


def _pick_master_from_files(files: dict) -> tuple[int, str, str]:
    """Возвращает (height, label, filename) самого крупного варианта.

    Используется вместо хардкода 'files["1080p"]', потому что в native-режиме
    мастер может быть 720p / 480p / меньше — зависит от исходника.
    Игнорирует platform-tagged варианты типа 'youtube-1080p'.
    """
    candidates: list[tuple[int, str, str]] = []
    for label, fn in (files or {}).items():
        m = _RES_LABEL_RE.match(label)
        if m:
            candidates.append((int(m.group(1)), label, fn))
    if not candidates:
        raise HTTPException(409, "мастер видео не найдено")
    candidates.sort(reverse=True)
    return candidates[0]


def _save_job_state(job: JobState) -> None:
    """Сохраняет JobState в jobs/<id>/state.json. Вызывается после каждого важного апдейта."""
    job_dir = WORK_DIR / job.id
    if not job_dir.exists():
        return
    try:
        # лог обрезаем до последних 200 записей чтобы не пухло
        snapshot = asdict(job)
        snapshot["log"] = snapshot["log"][-200:]
        (job_dir / "state.json").write_text(
            json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


def _reconstruct_legacy_job(job_dir: Path) -> Optional[JobState]:
    """Для job'ов БЕЗ state.json пытаемся собрать state из output/ + segments.json."""
    out_dir = job_dir / "output"
    if not out_dir.exists():
        return None
    masters = sorted(out_dir.glob("*-1080p.mp4"))
    if not masters:
        return None
    # читаем slug, формируем clips
    clips: list[dict] = []
    for i, master in enumerate(masters, 1):
        # имя файла: NN-slug-1080p.mp4 → slug
        stem = master.stem.replace("-1080p", "")
        # title: восстанавливаем slug → читабельный текст
        title = stem
        if "-" in stem:
            parts = stem.split("-", 1)
            if parts[0].isdigit():
                title = parts[1].replace("-", " ").capitalize()
        files = {"1080p": master.name}
        for label in ("720p", "480p"):
            v = out_dir / f"{stem}-{label}.mp4"
            if v.exists():
                files[label] = v.name
        clips.append({
            "index": i, "title": title, "start": 0.0, "end": 0.0,
            "files": files, "slug": stem, "sub_template": "block",
            "src_basename": "", "brand": "excella", "cta": "demo",
            "meta_title": "", "meta_descriptions": {}, "meta_hashtags": {},
            "meta_lead_links": {},
        })
    return JobState(
        id=job_dir.name, status="done", stage="done", progress=100.0,
        clips=clips, title=clips[0]["title"] if clips else job_dir.name,
    )


def _load_jobs_from_disk() -> None:
    """При старте сервера восстанавливаем job'ы из jobs/*/state.json (или output/ для legacy)."""
    if not WORK_DIR.exists():
        return
    for job_dir in WORK_DIR.iterdir():
        if not job_dir.is_dir():
            continue
        state_path = job_dir / "state.json"
        if state_path.exists():
            try:
                data = json.loads(state_path.read_text(encoding="utf-8"))
                if data.get("status") == "running":
                    data["status"] = "error"
                    data["error"] = (data.get("error") or "") + " (server restart)"
                job = JobState(**{k: v for k, v in data.items() if k in JobState.__dataclass_fields__})
                JOBS[job.id] = job
                continue
            except Exception:
                pass
        # legacy fallback
        legacy = _reconstruct_legacy_job(job_dir)
        if legacy:
            JOBS[legacy.id] = legacy
            _save_job_state(legacy)  # пишем state.json для следующего раза


_load_jobs_from_disk()


app = FastAPI(title="shorts-cutter")
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
# отдаём ассеты брендов (watermark.png, face.mp4) — нужно для UI-превью
(BRAND_DIR / "_assets").mkdir(parents=True, exist_ok=True)
app.mount("/brand-assets", StaticFiles(directory=str(BRAND_DIR / "_assets")), name="brand-assets")


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse((WEB_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/preview", response_class=HTMLResponse)
@app.get("/preview/", response_class=HTMLResponse)
async def preview_index() -> HTMLResponse:
    return HTMLResponse((WEB_DIR / "preview" / "ShortsAI Prototype.html").read_text(encoding="utf-8"))


@app.get("/legacy", response_class=HTMLResponse)
async def legacy_index() -> HTMLResponse:
    """Старый UI (vanilla+Tailwind v3). Доступен на случай отката."""
    return HTMLResponse((WEB_DIR / "index.legacy.html").read_text(encoding="utf-8"))


# mount после маршрута /preview, иначе StaticFiles перехватит index-запросы
app.mount("/preview", StaticFiles(directory=str(WEB_DIR / "preview"), html=False), name="preview")


@app.middleware("http")
async def _no_cache_for_preview(request, call_next):
    """В дев-режиме отключаем кеш для /preview/* — иначе после правки JSX/CSS
    приходится делать hard-reload в браузере."""
    response = await call_next(request)
    if request.url.path.startswith("/preview/") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.get("/backend")
async def backend_info():
    b = detect_backend()
    return {"name": b.name, "device": b.device, "model": b.suggested_model, "note": b.note}


@app.get("/prompts")
async def list_prompts():
    from src.prompts import DEFAULT_PROMPTS, list_prompt_names, load_prompt, is_customized
    return [
        {
            "name": n,
            "label": {"picker": "🎯 Picker (выбор моментов)",
                      "metadata": "📝 Metadata (SEO-описания и хэштеги)"}.get(n, n),
            "text": load_prompt(n),
            "customized": is_customized(n),
        }
        for n in list_prompt_names()
    ]


class PromptUpdate(BaseModel):
    text: str


@app.post("/prompts/{name}")
async def save_prompt_endpoint(name: str, req: PromptUpdate):
    from src.prompts import save_prompt, DEFAULT_PROMPTS
    if name not in DEFAULT_PROMPTS:
        raise HTTPException(404, f"Промпт {name} не найден")
    save_prompt(name, req.text)
    return {"ok": True}


@app.post("/prompts/{name}/reset")
async def reset_prompt_endpoint(name: str):
    from src.prompts import reset_prompt, DEFAULT_PROMPTS, load_prompt
    if name not in DEFAULT_PROMPTS:
        raise HTTPException(404)
    reset_prompt(name)
    return {"ok": True, "text": load_prompt(name)}


@app.get("/llm/providers")
async def llm_providers():
    from src.llm import list_providers_status, default_provider
    return {"default": default_provider(), "providers": list_providers_status()}


@app.get("/subtitle-templates")
async def subtitle_templates():
    """Полные параметры всех стилей субтитров (для редактирования в UI)."""
    return [
        {"key": k, **asdict(t)}
        for k, t in SUB_PRESETS.items()
    ]


_SUB_STYLES_OVERRIDES = BRAND_DIR / "_subtitle_overrides.json"


def _load_sub_overrides() -> dict:
    """Юзерские правки стилей — пережили рестарт через JSON на диске."""
    if not _SUB_STYLES_OVERRIDES.exists():
        return {}
    try:
        return json.loads(_SUB_STYLES_OVERRIDES.read_text())
    except Exception:
        return {}


def _apply_sub_overrides() -> None:
    """Применяет сохранённые правки к SUB_PRESETS in-memory.
    Если в overrides есть полностью новый key (custom-стиль) — создаёт его."""
    from src.subtitles import SubTemplate
    overrides = _load_sub_overrides()
    block_default = asdict(SUB_PRESETS["block"]) if "block" in SUB_PRESETS else {}
    for key, patch in overrides.items():
        if key in SUB_PRESETS:
            cur = asdict(SUB_PRESETS[key])
        else:
            # новый custom стиль — стартуем с block-дефолта
            cur = dict(block_default)
        cur.update(patch or {})
        try:
            SUB_PRESETS[key] = SubTemplate(**cur)
        except TypeError:
            pass  # неполная запись — пропускаем


# встроенные ключи фиксируем ДО применения overrides (иначе после них в SUB_PRESETS могут
# появиться custom-стили, и distinguish'ить будет сложнее).
# Так же сохраняем deep-copy дефолтов чтобы reset реально возвращал к коду, а не к
# уже мутированному объекту.
_BUILTIN_SUB_KEYS = {"karaoke", "block", "minimal", "neon", "telegram", "big_white"}
import copy as _copy
_ORIGINAL_DEFAULTS = {k: _copy.deepcopy(SUB_PRESETS[k]) for k in _BUILTIN_SUB_KEYS if k in SUB_PRESETS}
_apply_sub_overrides()


class SubTemplatePatch(BaseModel):
    # допустимые поля для патча — все из SubTemplate dataclass
    name: Optional[str] = None
    font: Optional[str] = None
    size: Optional[int] = None
    bold: Optional[bool] = None
    color: Optional[str] = None
    highlight: Optional[str] = None
    outline_color: Optional[str] = None
    outline: Optional[int] = None
    shadow: Optional[int] = None
    margin_v: Optional[int] = None
    words_per_chunk: Optional[int] = None
    chunk_advance: Optional[int] = None
    max_chars_per_line: Optional[int] = None
    use_highlight: Optional[bool] = None
    min_chunk_duration: Optional[float] = None
    highlight_scale: Optional[int] = None


@app.patch("/subtitle-templates/{key}")
async def patch_subtitle_template(key: str, patch: SubTemplatePatch):
    """Изменить параметры существующего стиля. Правки сохраняются на диск."""
    from src.subtitles import SubTemplate
    if key not in SUB_PRESETS:
        raise HTTPException(404, f"стиль {key} не найден")
    cur = asdict(SUB_PRESETS[key])
    upd = {k: v for k, v in patch.dict().items() if v is not None}
    cur.update(upd)
    SUB_PRESETS[key] = SubTemplate(**cur)

    # сохраняем все юзерские правки в один файл (мердж с уже сохранёнными)
    overrides = _load_sub_overrides()
    overrides[key] = {**overrides.get(key, {}), **upd}
    _SUB_STYLES_OVERRIDES.parent.mkdir(parents=True, exist_ok=True)
    _SUB_STYLES_OVERRIDES.write_text(json.dumps(overrides, ensure_ascii=False, indent=2))
    return {"key": key, **asdict(SUB_PRESETS[key])}


@app.post("/subtitle-templates/{key}/reset")
async def reset_subtitle_template(key: str):
    """Сбросить кастомные правки стиля — вернуть к дефолту из кода (только для встроенных)."""
    if key not in _BUILTIN_SUB_KEYS:
        raise HTTPException(400, "сбросить можно только встроенный стиль; кастомный — удалите целиком")
    # реимпорт исходных дефолтов из кода (но осторожно — это тот же объект, что SUB_PRESETS!)
    # лучше сохраняем дефолты копиями при первом старте.
    SUB_PRESETS[key] = _ORIGINAL_DEFAULTS[key]
    overrides = _load_sub_overrides()
    overrides.pop(key, None)
    if overrides:
        _SUB_STYLES_OVERRIDES.write_text(json.dumps(overrides, ensure_ascii=False, indent=2))
    elif _SUB_STYLES_OVERRIDES.exists():
        _SUB_STYLES_OVERRIDES.unlink()
    return {"key": key, **asdict(SUB_PRESETS[key])}


class SubTemplateCreate(BaseModel):
    key: str  # уникальный латинский ключ
    copy_from: Optional[str] = "block"  # старт с какого пресета
    name: Optional[str] = None


@app.post("/subtitle-templates")
async def create_subtitle_template(req: SubTemplateCreate):
    """Создать новый стиль субтитров на основе существующего пресета.
    Сохраняется в _subtitle_overrides.json (с ключом-новичком)."""
    from src.subtitles import SubTemplate, PRESETS as DEFAULT_PRESETS
    import re as _re
    if not _re.match(r"^[a-z][a-z0-9_]{1,30}$", req.key):
        raise HTTPException(400, "ключ — латиница/цифры/подчёркивания, 2-31 символ, начинается с буквы")
    if req.key in SUB_PRESETS:
        raise HTTPException(400, f"стиль {req.key} уже существует")
    base_key = req.copy_from or "block"
    if base_key not in DEFAULT_PRESETS and base_key not in SUB_PRESETS:
        base_key = "block"
    base = SUB_PRESETS.get(base_key) or DEFAULT_PRESETS.get(base_key) or DEFAULT_PRESETS["block"]
    cur = asdict(base)
    cur["name"] = req.name or f"✨ {req.key}"
    SUB_PRESETS[req.key] = SubTemplate(**cur)
    overrides = _load_sub_overrides()
    overrides[req.key] = cur
    _SUB_STYLES_OVERRIDES.parent.mkdir(parents=True, exist_ok=True)
    _SUB_STYLES_OVERRIDES.write_text(json.dumps(overrides, ensure_ascii=False, indent=2))
    return {"key": req.key, **asdict(SUB_PRESETS[req.key])}


@app.delete("/subtitle-templates/{key}")
async def delete_subtitle_template(key: str):
    """Удалить кастомный стиль (но не дефолтный из кода)."""
    if key in _BUILTIN_SUB_KEYS:
        raise HTTPException(400, f"{key} — встроенный стиль, его нельзя удалить (только сбросить)")
    if key not in SUB_PRESETS:
        raise HTTPException(404)
    SUB_PRESETS.pop(key)
    overrides = _load_sub_overrides()
    overrides.pop(key, None)
    if overrides:
        _SUB_STYLES_OVERRIDES.write_text(json.dumps(overrides, ensure_ascii=False, indent=2))
    elif _SUB_STYLES_OVERRIDES.exists():
        _SUB_STYLES_OVERRIDES.unlink()
    return {"ok": True}


@app.get("/brands")
async def brands_list():
    names = list_brands() or ["excella"]
    out = []
    for n in names:
        try:
            b = load_brand(n)
            out.append({
                "name": b.name,
                "cta_presets": [
                    {"key": k, "text": v.text, "sub_text": v.sub_text}
                    for k, v in b.cta_presets.items()
                ],
                "cta_default": b.cta_default,
                "bottom_strip_text": b.bottom_strip.text if b.bottom_strip else None,
            })
        except Exception:
            pass
    return out


@app.get("/brands/{name}")
async def brand_detail(name: str):
    try:
        b = load_brand(name)
    except FileNotFoundError:
        raise HTTPException(404)
    return asdict(b)


class BrandCreate(BaseModel):
    name: str
    copy_from: Optional[str] = None


@app.post("/brands")
async def brand_create(req: BrandCreate):
    try:
        b = create_brand(req.name, copy_from=req.copy_from)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return asdict(b)


@app.patch("/brands/{name}")
async def brand_update(name: str, patch: dict):
    try:
        b = update_brand_partial(name, patch)
    except FileNotFoundError:
        raise HTTPException(404)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return asdict(b)


@app.delete("/brands/{name}")
async def brand_delete(name: str):
    try:
        delete_brand(name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/brands/{name}/watermark")
async def brand_upload_watermark(name: str, file: UploadFile = File(...)):
    try:
        tpl = load_brand(name)
    except FileNotFoundError:
        raise HTTPException(404)
    if not file.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        raise HTTPException(400, "Поддерживается PNG/JPG/WEBP")
    asset_dir = BRAND_DIR / "_assets"
    asset_dir.mkdir(exist_ok=True)
    suffix = Path(file.filename).suffix.lower()
    out_path = asset_dir / f"{name}{suffix}"
    with out_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    tpl.watermark_path = str(out_path)
    save_brand(tpl)
    return {"watermark_path": tpl.watermark_path}


@app.delete("/brands/{name}/watermark")
async def brand_delete_watermark(name: str):
    try:
        tpl = load_brand(name)
    except FileNotFoundError:
        raise HTTPException(404)
    if tpl.watermark_path and Path(tpl.watermark_path).exists():
        Path(tpl.watermark_path).unlink()
    tpl.watermark_path = None
    save_brand(tpl)
    return {"ok": True}


@app.post("/brands/{name}/face-overlay")
async def brand_upload_face(name: str, file: UploadFile = File(...)):
    try:
        tpl = load_brand(name)
    except FileNotFoundError:
        raise HTTPException(404)
    if not file.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov")):
        raise HTTPException(400, "PNG/JPG/WEBP (фото) или MP4/MOV (видео-цикл)")
    asset_dir = BRAND_DIR / "_assets"
    asset_dir.mkdir(exist_ok=True)
    suffix = Path(file.filename).suffix.lower()
    out_path = asset_dir / f"{name}.face{suffix}"
    # удаляем старые фото/видео если расширение другое
    for old in asset_dir.glob(f"{name}.face.*"):
        if old != out_path:
            old.unlink(missing_ok=True)
    with out_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    tpl.face_overlay_path = str(out_path)
    save_brand(tpl)
    return {"face_overlay_path": tpl.face_overlay_path}


@app.delete("/brands/{name}/face-overlay")
async def brand_delete_face(name: str):
    try:
        tpl = load_brand(name)
    except FileNotFoundError:
        raise HTTPException(404)
    if tpl.face_overlay_path and Path(tpl.face_overlay_path).exists():
        Path(tpl.face_overlay_path).unlink()
    tpl.face_overlay_path = None
    save_brand(tpl)
    return {"ok": True}


@app.get("/settings")
async def get_settings():
    env = _read_env()
    hf = env.get("HF_TOKEN", "") or os.environ.get("HF_TOKEN", "")
    pex = env.get("PEXELS_API_KEY", "") or os.environ.get("PEXELS_API_KEY", "")
    el = env.get("ELEVENLABS_API_KEY", "") or os.environ.get("ELEVENLABS_API_KEY", "")
    return {
        "hf_token_set": bool(hf), "hf_token_masked": _mask_token(hf),
        "pexels_set": bool(pex), "pexels_masked": _mask_token(pex),
        "elevenlabs_set": bool(el), "elevenlabs_masked": _mask_token(el),
    }


class SettingsUpdate(BaseModel):
    hf_token: Optional[str] = None
    pexels_api_key: Optional[str] = None
    elevenlabs_api_key: Optional[str] = None


@app.post("/settings")
async def set_settings(s: SettingsUpdate):
    if s.hf_token is not None:
        token = s.hf_token.strip()
        if token and not re.match(r"^hf_[A-Za-z0-9]{20,}$", token):
            raise HTTPException(400, "Похоже на невалидный HF токен (должен начинаться с hf_)")
        _write_env({"HF_TOKEN": token})
        if token:
            os.environ["HF_TOKEN"] = token
            os.environ["HUGGING_FACE_HUB_TOKEN"] = token
        else:
            os.environ.pop("HF_TOKEN", None)
            os.environ.pop("HUGGING_FACE_HUB_TOKEN", None)
    if s.pexels_api_key is not None:
        key = s.pexels_api_key.strip()
        _write_env({"PEXELS_API_KEY": key})
        if key:
            os.environ["PEXELS_API_KEY"] = key
        else:
            os.environ.pop("PEXELS_API_KEY", None)
    if s.elevenlabs_api_key is not None:
        key = s.elevenlabs_api_key.strip()
        if key and not re.match(r"^(sk_|xi-)[A-Za-z0-9_]{20,}$", key):
            raise HTTPException(400, "Похоже на невалидный ElevenLabs ключ (должен начинаться с sk_)")
        _write_env({"ELEVENLABS_API_KEY": key})
        if key:
            os.environ["ELEVENLABS_API_KEY"] = key
        else:
            os.environ.pop("ELEVENLABS_API_KEY", None)
    return await get_settings()


@app.get("/elevenlabs/voices")
async def elevenlabs_voices():
    """Passthrough к ElevenLabs /v1/voices: возвращает все доступные голоса
    с preview_url'ами и labels (gender/age/accent/use_case/language).
    """
    import urllib.error
    import urllib.request
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise HTTPException(401, "ELEVENLABS_API_KEY не задан")
    req = urllib.request.Request(
        "https://api.elevenlabs.io/v1/voices",
        headers={"xi-api-key": key, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        raise HTTPException(e.code, f"ElevenLabs: {body}")
    # упростим до того что нужно UI
    voices = []
    for v in (data.get("voices") or []):
        voices.append({
            "voice_id": v.get("voice_id"),
            "name": v.get("name"),
            "category": v.get("category"),  # premade / cloned / professional
            "preview_url": v.get("preview_url"),
            "labels": v.get("labels") or {},
            "description": v.get("description") or "",
        })
    return {"voices": voices, "total": len(voices)}


@app.get("/settings/elevenlabs/check")
async def elevenlabs_check():
    """Probe-запрос к ElevenLabs: проверяет ключ и доступы по эндпоинтам.

    Толерантен к scoped API keys: ключ может не иметь `user_read` — тогда
    план/баланс не покажем, но валидность и доступ к TTS/Dubbing проверим
    через дешёвые независимые эндпоинты.
    """
    import urllib.error
    import urllib.request
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        return {"ok": False, "error": "ключ не задан"}

    def _get(path: str):
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1{path}",
            headers={"xi-api-key": key, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode("utf-8", errors="replace"))
            except Exception:
                return e.code, ""
        except Exception as e:
            return -1, str(e)

    def _missing_perm(data) -> bool:
        if isinstance(data, dict):
            d = data.get("detail")
            if isinstance(d, dict) and d.get("status") == "missing_permissions":
                return True
        return False

    # 1) /models — обычно публичный, но scoped ключ может не иметь и его.
    code, data = _get("/models")
    if code < 0:
        return {"ok": False, "error": f"нет связи с ElevenLabs: {data}"}
    # Ключ принят сервером: либо 200, либо явный 401/403 с missing_permissions
    # (это значит сервер ключ узнал, но scope не выдан).
    accepted = (code == 200) or _missing_perm(data)

    # 2) /user — нужен scope user_read. Опционально.
    code_u, data_u = _get("/user")
    if not accepted:
        accepted = (code_u == 200) or _missing_perm(data_u)
    if not accepted and code_u in (401, 403):
        return {"ok": False, "error": "ключ не принят (HTTP 401) — невалидный или удалён"}
    user_scope = code_u == 200
    tier = "?"
    used = 0
    cap = 0
    if user_scope and isinstance(data_u, dict):
        sub = data_u.get("subscription", {}) or {}
        tier = sub.get("tier", "?")
        used = int(sub.get("character_count", 0) or 0)
        cap = int(sub.get("character_limit", 0) or 0)

    # 3) /dubbing — нужен scope dubbing_read. Probe несуществующего id:
    #    404/422 → scope есть; 401 missing_permissions → scope не выдан.
    code_d, data_d = _get("/dubbing/_probe_nonexistent_")
    if code_d in (404, 422):
        dubbing = "available"
    elif _missing_perm(data_d):
        dubbing = "no_scope"
    elif code_d in (401, 403):
        dubbing = "no_plan"
    else:
        dubbing = "unknown"

    return {
        "ok": accepted,
        "user_scope": user_scope,
        "tier": tier,
        "characters_used": used,
        "characters_limit": cap,
        "dubbing": dubbing,
        "dubbing_available": dubbing == "available",
    }


@app.post("/jobs")
async def create_job(
    url: Optional[str] = Form(None),
    max_clips: int = Form(8),
    whisper_model: str = Form("medium"),
    sub_template: str = Form("block"),
    brand: str = Form("excella"),
    cta: str = Form("demo"),
    llm_provider: str = Form(""),
    llm_model: str = Form(""),
    download_max_height: int = Form(1080),
    download_cookies_browser: str = Form(""),
    output_size: str = Form("native"),
    voiceover: bool = Form(False),
    voiceover_engine: str = Form("library"),
    voiceover_mode: str = Form("duck"),
    voiceover_voice: str = Form("EXAVITQu4vr4xnSDxMaL"),
    voiceover_model: str = Form("eleven_v3"),
    voiceover_target_lang: str = Form("ru"),
    picker_extra: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    if not url and not file:
        raise HTTPException(400, "Нужен URL или файл")

    job_id = uuid.uuid4().hex[:12]
    job = JobState(id=job_id, source_url=url or "", title=(file.filename if file else "") or "")
    JOBS[job_id] = job
    QUEUES[job_id] = asyncio.Queue()

    job_dir = WORK_DIR / job_id
    out_dir = job_dir / "output"
    dl_dir = job_dir / "downloads"
    out_dir.mkdir(parents=True)
    dl_dir.mkdir(parents=True)

    file_path: Optional[Path] = None
    if file is not None:
        file_path = dl_dir / file.filename
        with file_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)

    asyncio.create_task(_run_job(
        job_id, url, file_path, out_dir, dl_dir,
        max_clips, whisper_model, sub_template, brand, cta,
        llm_provider, llm_model,
        download_max_height, download_cookies_browser, output_size,
        voiceover, voiceover_engine, voiceover_mode,
        voiceover_voice, voiceover_model, voiceover_target_lang,
        picker_extra,
    ))
    return {"job_id": job_id}


async def _run_job(
    job_id: str, url: Optional[str], file_path: Optional[Path],
    out_dir: Path, dl_dir: Path,
    max_clips: int, whisper_model: str, sub_template: str,
    brand: str, cta: str,
    llm_provider: str = "", llm_model: str = "",
    download_max_height: int = 1080, download_cookies_browser: str = "",
    output_size: str = "native",
    voiceover: bool = False, voiceover_engine: str = "library",
    voiceover_mode: str = "duck",
    voiceover_voice: str = "EXAVITQu4vr4xnSDxMaL",
    voiceover_model: str = "eleven_v3",
    voiceover_target_lang: str = "ru",
    picker_extra: str = "",
):
    job = JOBS[job_id]
    queue = QUEUES[job_id]
    loop = asyncio.get_running_loop()

    # Если все слоты заняты — встаём в очередь и сообщаем фронту.
    if JOB_SEMAPHORE.locked():
        job.status = "queued"
        await queue.put({
            "stage": "queued", "progress": 0,
            "msg": f"ожидание слота (лимит {MAX_CONCURRENT_JOBS})", "eta_s": None,
        })
        _save_job_state(job)

    async with JOB_SEMAPHORE:
        job.status = "running"
        await _run_job_inner(
            job, queue, loop, job_id, url, file_path, out_dir, dl_dir,
            max_clips, whisper_model, sub_template, brand, cta,
            llm_provider, llm_model,
            download_max_height, download_cookies_browser, output_size,
            voiceover, voiceover_engine, voiceover_mode,
            voiceover_voice, voiceover_model, voiceover_target_lang,
            picker_extra,
        )


async def _run_job_inner(
    job, queue, loop, job_id, url, file_path, out_dir, dl_dir,
    max_clips, whisper_model, sub_template, brand, cta,
    llm_provider, llm_model,
    download_max_height, download_cookies_browser, output_size,
    voiceover, voiceover_engine, voiceover_mode,
    voiceover_voice, voiceover_model, voiceover_target_lang,
    picker_extra,
):

    save_counter = [0]
    def on_progress(stage: str, pct: float, msg: str, eta_s: float | None = None) -> None:
        job.stage = stage
        job.progress = pct
        entry = {"stage": stage, "progress": pct, "msg": msg, "eta_s": eta_s}
        job.log.append(entry)
        asyncio.run_coroutine_threadsafe(queue.put(entry), loop)
        # сохраняем state на диск раз в 20 апдейтов + при смене этапа
        save_counter[0] += 1
        if save_counter[0] % 20 == 0 or stage != getattr(on_progress, "_last_stage", None):
            _save_job_state(job)
            on_progress._last_stage = stage  # type: ignore[attr-defined]

    try:
        results: list[ClipResult] = await asyncio.to_thread(
            run_pipeline,
            url=url,
            file_path=file_path,
            out_dir=out_dir,
            downloads_dir=dl_dir,
            max_clips=max_clips,
            model_size=whisper_model,
            sub_template=sub_template,
            brand=brand,
            cta=cta,
            llm_provider=llm_provider,
            llm_model=llm_model,
            download_max_height=download_max_height,
            download_cookies_browser=download_cookies_browser,
            output_size=output_size,
            voiceover=voiceover,
            voiceover_engine=voiceover_engine,
            voiceover_mode=voiceover_mode,
            voiceover_voice=voiceover_voice,
            voiceover_model=voiceover_model,
            voiceover_target_lang=voiceover_target_lang,
            picker_extra=picker_extra,
            on_progress=on_progress,
        )
        job.clips = [asdict(c) for c in results]
        job.status = "done"
        job.title = (results[0].title if results else "") or job.title
        await queue.put({"stage": "done", "progress": 100, "msg": "готово", "clips": job.clips})
        _save_job_state(job)
    except Exception as e:
        job.status = "error"
        job.error = str(e)
        await queue.put({"stage": "error", "progress": job.progress, "msg": str(e)})
        _save_job_state(job)
    finally:
        await queue.put(None)  # сигнал закрытия


@app.get("/jobs")
async def list_jobs(limit: int = 30):
    """Список всех job'ов (новые сверху). Используется для UI «Последние задания»."""
    items = []
    for jid, job in JOBS.items():
        items.append({
            "id": jid,
            "status": job.status,
            "stage": job.stage,
            "progress": job.progress,
            "n_clips": len(job.clips),
            "title": job.title or job.source_url[:60] or jid,
            "source_url": job.source_url,
            "error": job.error,
        })
    # сортируем по времени появления в JOBS (последние сверху)
    items.reverse()
    return items[:limit]


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404)
    return asdict(job)


@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    """Удаляет job из памяти и с диска."""
    job_dir = WORK_DIR / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir)
    JOBS.pop(job_id, None)
    QUEUES.pop(job_id, None)
    return {"ok": True}


@app.websocket("/ws/{job_id}")
async def ws(websocket: WebSocket, job_id: str):
    await websocket.accept()
    job = JOBS.get(job_id)
    queue = QUEUES.get(job_id)
    if not job or not queue:
        await websocket.send_json({"error": "job not found"})
        await websocket.close()
        return

    # отдаём накопленный лог
    for entry in job.log:
        await websocket.send_json(entry)
    if job.status == "done":
        await websocket.send_json({"stage": "done", "progress": 100, "msg": "готово", "clips": job.clips})
        await websocket.close()
        return

    try:
        while True:
            entry = await queue.get()
            if entry is None:
                break
            await websocket.send_json(entry)
    except WebSocketDisconnect:
        pass
    finally:
        await websocket.close()


@app.get("/publish/youtube/status/{brand}")
async def yt_status(brand: str):
    from src.publish import youtube as yt
    s = yt.get_status(brand)
    return asdict(s)


@app.post("/publish/youtube/upload-secrets/{brand}")
async def yt_upload_secrets(brand: str, file: UploadFile = File(...)):
    from src.publish import youtube as yt
    data = await file.read()
    try:
        yt.save_client_secrets(brand, data)
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/publish/youtube/connect/{brand}")
async def yt_connect(brand: str):
    """Запускает OAuth flow в фоне (открывает браузер для согласия).

    Блокирующий, может занимать секунды-минуты пока пользователь даёт согласие.
    """
    from src.publish import youtube as yt
    try:
        await asyncio.to_thread(yt.start_oauth, brand)
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"OAuth failed: {e}")
    s = yt.get_status(brand)
    return asdict(s)


@app.post("/publish/youtube/disconnect/{brand}")
async def yt_disconnect(brand: str):
    from src.publish import youtube as yt
    yt.disconnect(brand)
    return {"ok": True}


class YTUploadRequest(BaseModel):
    privacy: str = "public"  # public | unlisted | private
    use_meta_for: Optional[str] = "youtube"  # ключ платформы из meta_descriptions


@app.post("/jobs/{job_id}/clips/{clip_index}/publish/youtube")
async def yt_publish_clip(job_id: str, clip_index: int, req: YTUploadRequest):
    from src.publish import youtube as yt
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404)
    if clip_index < 1 or clip_index > len(job.clips):
        raise HTTPException(404)
    clip = job.clips[clip_index - 1]
    brand = clip.get("brand", "excella")

    plat = req.use_meta_for or "youtube"
    title = clip.get("meta_title") or clip.get("title", "")
    description = (clip.get("meta_descriptions") or {}).get(plat, "")
    tags = (clip.get("meta_hashtags") or {}).get(plat, [])

    video_path = WORK_DIR / job_id / "output" / _pick_master_from_files(clip["files"])[2]
    if not video_path.exists():
        raise HTTPException(409, "видео не найдено")

    try:
        result = await asyncio.to_thread(
            yt.upload_video,
            brand=brand, video_path=video_path,
            title=title, description=description, tags=tags,
            privacy=req.privacy,
        )
    except Exception as e:
        raise HTTPException(500, f"upload failed: {e}")

    # сохраняем url в clip state — и на диск, чтобы не потерять при рестарте
    clip.setdefault("publications", {})["youtube"] = {
        "url": result.get("url"), "video_id": result.get("video_id"),
        "privacy": req.privacy,
    }
    _save_job_state(job)
    return result


@app.get("/publish/vk/status/{brand}")
async def vk_status(brand: str):
    from src.publish import vk
    return asdict(vk.get_status(brand))


class VKConnect(BaseModel):
    access_token: str
    target_owner_id: int = 0  # 0 = личная страница, отрицательное = группа (id со знаком -)
    target_name: str = ""


@app.post("/publish/vk/connect/{brand}")
async def vk_connect(brand: str, req: VKConnect):
    from src.publish import vk
    if not req.access_token.strip():
        raise HTTPException(400, "access_token обязателен")
    vk.save_token(brand, req.access_token, req.target_owner_id, req.target_name)
    return asdict(vk.get_status(brand))


@app.post("/publish/vk/disconnect/{brand}")
async def vk_disconnect(brand: str):
    from src.publish import vk
    vk.disconnect(brand)
    return {"ok": True}


class VKUploadRequest(BaseModel):
    privacy: str = "all"


@app.post("/jobs/{job_id}/clips/{clip_index}/publish/vk")
async def vk_publish_clip(job_id: str, clip_index: int, req: VKUploadRequest):
    from src.publish import vk
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404)
    if clip_index < 1 or clip_index > len(job.clips):
        raise HTTPException(404)
    clip = job.clips[clip_index - 1]
    brand = clip.get("brand", "excella")

    title = clip.get("meta_title") or clip.get("title", "")
    description = (clip.get("meta_descriptions") or {}).get("vk", "")
    tags = (clip.get("meta_hashtags") or {}).get("vk", [])
    if tags:
        description = description.rstrip() + "\n\n" + " ".join(tags)

    video_path = WORK_DIR / job_id / "output" / _pick_master_from_files(clip["files"])[2]
    if not video_path.exists():
        raise HTTPException(409, "видео не найдено")

    try:
        result = await asyncio.to_thread(
            vk.upload_video,
            brand=brand, video_path=video_path,
            title=title, description=description,
            privacy=req.privacy,
        )
    except Exception as e:
        raise HTTPException(500, f"upload failed: {e}")

    clip.setdefault("publications", {})["vk"] = {
        "url": result.get("url"), "video_id": result.get("video_id"),
        "privacy": req.privacy,
    }
    _save_job_state(job)
    return result


@app.get("/publish/instagram/status/{brand}")
async def ig_status(brand: str):
    from src.publish import instagram as ig
    return asdict(ig.get_status(brand))


class IGConnect(BaseModel):
    access_token: str
    ig_user_id: str
    public_base_url: str = ""


@app.post("/publish/instagram/connect/{brand}")
async def ig_connect(brand: str, req: IGConnect):
    from src.publish import instagram as ig
    if not req.access_token.strip() or not req.ig_user_id.strip():
        raise HTTPException(400, "access_token и ig_user_id обязательны")
    ig.save_token(brand, req.access_token, req.ig_user_id, req.public_base_url)
    return asdict(ig.get_status(brand))


@app.post("/publish/instagram/disconnect/{brand}")
async def ig_disconnect(brand: str):
    from src.publish import instagram as ig
    ig.disconnect(brand)
    return {"ok": True}


class IGUploadRequest(BaseModel):
    share_to_feed: bool = True
    public_video_url: Optional[str] = None  # явное переопределение URL


@app.post("/jobs/{job_id}/clips/{clip_index}/publish/instagram")
async def ig_publish_clip(job_id: str, clip_index: int, req: IGUploadRequest):
    from src.publish import instagram as ig
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404)
    if clip_index < 1 or clip_index > len(job.clips):
        raise HTTPException(404)
    clip = job.clips[clip_index - 1]
    brand = clip.get("brand", "excella")

    title = clip.get("meta_title") or clip.get("title", "")
    description = (clip.get("meta_descriptions") or {}).get("instagram", "")
    tags = (clip.get("meta_hashtags") or {}).get("instagram", [])
    caption = description.rstrip()
    if tags:
        caption = caption + "\n\n" + " ".join(tags)
    if title and title not in caption:
        caption = title + "\n\n" + caption

    # формируем публичный URL
    if req.public_video_url:
        video_url = req.public_video_url
    else:
        status = ig.get_status(brand)
        base = status.public_base_url
        if not base:
            raise HTTPException(
                400,
                "Instagram требует публичный URL видео. Укажи public_base_url в настройках "
                "бренда (например через cloudflared/ngrok тоннель).",
            )
        filename = _pick_master_from_files(clip["files"])[2]
        video_url = f"{base.rstrip('/')}/clips/{job_id}/{filename}"

    try:
        result = await asyncio.to_thread(
            ig.upload_reel,
            brand=brand, video_url=video_url, caption=caption,
            share_to_feed=req.share_to_feed,
        )
    except Exception as e:
        raise HTTPException(500, f"upload failed: {e}")

    clip.setdefault("publications", {})["instagram"] = {
        "url": result.get("url"), "media_id": result.get("media_id"),
    }
    _save_job_state(job)
    return result


@app.get("/uniqueness/presets")
async def uniqueness_presets():
    from src.uniqueness import PRESETS
    return {k: asdict(v) for k, v in PRESETS.items()}


class UniquenessRequest(BaseModel):
    platform: str  # youtube | instagram | vk | tiktok
    save_as_alt: bool = True  # сохранить как отдельный файл, не перезаписывать мастер


@app.post("/jobs/{job_id}/clips/{clip_index}/uniquify")
async def uniquify_clip(job_id: str, clip_index: int, req: UniquenessRequest):
    from src.uniqueness import apply_preset, PRESETS
    from src.render import transcode, variants_below

    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404)
    if clip_index < 1 or clip_index > len(job.clips):
        raise HTTPException(404)
    if req.platform not in PRESETS:
        raise HTTPException(400, f"неизвестная платформа: {req.platform}")
    clip = job.clips[clip_index - 1]
    out_dir = WORK_DIR / job_id / "output"
    master_h, master_label, master_name = _pick_master_from_files(clip["files"])
    master = out_dir / master_name
    if not master.exists():
        raise HTTPException(409, "мастер видео не найдено")

    slug = clip.get("slug", str(clip_index))
    alt_master = out_dir / f"{slug}-{req.platform}-{master_label}.mp4"
    await asyncio.to_thread(apply_preset, master, alt_master, req.platform)

    files = {f"{req.platform}-{master_label}": alt_master.name}
    # варианты — только МЕНЬШЕ master_h, никакого upscale
    for label, (w, h) in variants_below(master_h).items():
        variant = out_dir / f"{slug}-{req.platform}-{label}.mp4"
        await asyncio.to_thread(transcode, alt_master, variant, w, h)
        files[f"{req.platform}-{label}"] = variant.name

    clip.setdefault("uniquified", {})[req.platform] = files
    # объединяем в общий files-dict для скачивания
    clip["files"].update(files)
    return {"ok": True, "clip": clip}


@app.post("/jobs/{job_id}/clips/{clip_index}/thumbnails/generate")
async def generate_thumbnails(job_id: str, clip_index: int):
    from src.thumbnails import extract_thumbnails
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404)
    if clip_index < 1 or clip_index > len(job.clips):
        raise HTTPException(404)
    clip = job.clips[clip_index - 1]
    job_dir = WORK_DIR / job_id
    out_dir = job_dir / "output"
    master = out_dir / _pick_master_from_files(clip["files"])[2]
    if not master.exists():
        raise HTTPException(409, "мастер видео не найдено")
    thumbs_dir = out_dir / "thumbs" / clip.get("slug", str(clip_index))
    paths = await asyncio.to_thread(
        extract_thumbnails, master, thumbs_dir, 3,
    )
    rel = [str(p.relative_to(out_dir)) for p in paths]
    clip["thumbnails"] = rel
    return {"thumbnails": rel}


@app.get("/audio-library")
async def audio_library_list():
    from src.music import list_tracks
    return list_tracks()


@app.post("/audio-library/upload")
async def audio_library_upload(file: UploadFile = File(...)):
    from src.music import AUDIO_LIB
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".mp3", ".m4a", ".wav", ".ogg"):
        raise HTTPException(400, "Только MP3 / M4A / WAV / OGG")
    AUDIO_LIB.mkdir(exist_ok=True)
    safe_name = re.sub(r"[^\w.\- ]", "_", file.filename)
    out = AUDIO_LIB / safe_name
    with out.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"name": safe_name, "size_kb": out.stat().st_size // 1024}


@app.delete("/audio-library/{name}")
async def audio_library_delete(name: str):
    from src.music import AUDIO_LIB
    p = AUDIO_LIB / name
    if not p.exists() or ".." in name:
        raise HTTPException(404)
    p.unlink()
    return {"ok": True}


class MusicRequest(BaseModel):
    track: str
    volume: float = 0.15
    duck: bool = True


@app.post("/jobs/{job_id}/clips/{clip_index}/add-music")
async def add_music_endpoint(job_id: str, clip_index: int, req: MusicRequest):
    from src.music import AUDIO_LIB, add_music
    from src.render import RESOLUTIONS, transcode

    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404)
    if clip_index < 1 or clip_index > len(job.clips):
        raise HTTPException(404)
    clip = job.clips[clip_index - 1]

    track_path = AUDIO_LIB / req.track
    if not track_path.exists():
        raise HTTPException(404, "трек не найден в библиотеке")

    job_dir = WORK_DIR / job_id
    out_dir = job_dir / "output"
    master = out_dir / _pick_master_from_files(clip["files"])[2]
    if not master.exists():
        raise HTTPException(409, "мастер видео не найдено")

    tmp = out_dir / (master.stem + ".music.mp4")
    await asyncio.to_thread(
        add_music, master, track_path, tmp,
        music_volume=req.volume, duck=req.duck,
    )
    tmp.replace(master)

    for label, (w, h) in RESOLUTIONS.items():
        if label == "1080p":
            continue
        slug = clip.get("slug")
        if not slug:
            continue
        variant = out_dir / f"{slug}-{label}.mp4"
        await asyncio.to_thread(transcode, master, variant, w, h)

    clip["music"] = {"track": req.track, "volume": req.volume, "duck": req.duck}
    return {"ok": True, "clip": clip}


class BRollSearchRequest(BaseModel):
    keyword: str
    per_page: int = 5


@app.post("/broll/search")
async def broll_search(req: BRollSearchRequest):
    from src.broll import search_pexels, load_pexels_key
    key = load_pexels_key()
    if not key:
        raise HTTPException(400, "PEXELS_API_KEY не задан в .env (получи на pexels.com/api)")
    try:
        results = await asyncio.to_thread(search_pexels, key, req.keyword, req.per_page)
    except Exception as e:
        raise HTTPException(500, str(e))
    return [asdict(r) for r in results]


class BRollApplyRequest(BaseModel):
    pexels_url: str
    insert_at: float       # секунда от начала клипа
    duration: float = 2.0


@app.post("/jobs/{job_id}/clips/{clip_index}/add-broll")
async def add_broll(job_id: str, clip_index: int, req: BRollApplyRequest):
    from src.broll import download, insert_broll_overlay
    from src.render import RESOLUTIONS, transcode

    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404)
    if clip_index < 1 or clip_index > len(job.clips):
        raise HTTPException(404)
    clip = job.clips[clip_index - 1]
    job_dir = WORK_DIR / job_id
    out_dir = job_dir / "output"
    broll_dir = job_dir / "_broll"
    broll_dir.mkdir(exist_ok=True)

    master = out_dir / _pick_master_from_files(clip["files"])[2]
    if not master.exists():
        raise HTTPException(409, "мастер видео не найдено")

    # скачиваем broll
    broll_path = broll_dir / f"clip{clip_index}_{int(req.insert_at)}.mp4"
    await asyncio.to_thread(download, req.pexels_url, broll_path)

    # вставляем оверлей в master (перезаписываем)
    tmp = out_dir / (master.stem + ".broll.mp4")
    await asyncio.to_thread(
        insert_broll_overlay, master, broll_path, tmp,
        req.insert_at, req.duration,
    )
    tmp.replace(master)

    # пересоздаём 720p / 480p
    for label, (w, h) in RESOLUTIONS.items():
        if label == "1080p":
            continue
        slug = clip.get("slug")
        if not slug:
            continue
        variant = out_dir / f"{slug}-{label}.mp4"
        await asyncio.to_thread(transcode, master, variant, w, h)

    clip.setdefault("broll", []).append({
        "url": req.pexels_url, "insert_at": req.insert_at,
        "duration": req.duration,
    })
    return {"ok": True, "clip": clip}


@app.post("/jobs/{job_id}/metrics/refresh")
async def metrics_refresh(job_id: str):
    """Обновляет метрики всех опубликованных клипов в job'е."""
    from src.publish import metrics
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404)
    out: dict[int, dict] = {}
    for clip in job.clips:
        if not clip.get("publications"):
            continue
        m = await asyncio.to_thread(
            metrics.fetch_clip_metrics, clip, clip.get("brand", "excella"),
        )
        if m:
            clip["metrics"] = m
            out[clip["index"]] = m
    # сохраняем в jobs/<id>/metrics.json
    (WORK_DIR / job_id / "metrics.json").write_text(json.dumps(out, ensure_ascii=False))
    return {"per_clip": out, **metrics.aggregate_totals(out)}


@app.get("/dashboard/all")
async def dashboard_all():
    """Сводка по всем job'ам: список клипов с публикациями + кешированные метрики."""
    from src.publish import metrics as m_mod
    rows: list[dict] = []
    totals_per_clip: dict[int, dict] = {}
    for job_id, job in JOBS.items():
        for clip in job.clips:
            if not clip.get("publications"):
                continue
            row = {
                "job_id": job_id,
                "clip_index": clip["index"],
                "title": clip.get("meta_title") or clip.get("title", ""),
                "brand": clip.get("brand", "excella"),
                "publications": clip.get("publications", {}),
                "metrics": clip.get("metrics", {}),
            }
            rows.append(row)
            totals_per_clip[len(rows)] = clip.get("metrics", {})
    agg = m_mod.aggregate_totals(totals_per_clip)
    return {"rows": rows, **agg}


@app.get("/improvement/stats")
async def improvement_stats():
    from src.improvement import compute_stats
    s = compute_stats(WORK_DIR)
    return asdict(s)


@app.get("/clips/{job_id}/{filename}")
async def download_clip(job_id: str, filename: str):
    path = WORK_DIR / job_id / "output" / filename
    if not path.exists() or ".." in filename:
        raise HTTPException(404)
    return FileResponse(path, media_type="video/mp4", filename=filename)


@app.get("/clips/{job_id}/thumbs/{rest:path}")
async def download_thumbnail(job_id: str, rest: str):
    path = WORK_DIR / job_id / "output" / "thumbs" / rest
    if ".." in rest or not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/png")


class RestyleRequest(BaseModel):
    template: str


class RegenMetaRequest(BaseModel):
    pass


class EffectsRegenRequest(BaseModel):
    enable_zoom: bool = True
    enable_emoji: bool = True
    enable_hook: bool = True
    enable_sfx: bool = False
    hook_text_override: str | None = None  # если задан — заменит сгенерированный hook
    provider: str | None = None  # напр. "mlx-local" для офлайна; None = дефолт


class RetrimRequest(BaseModel):
    start: float
    end: float


class RegenerateRequest(BaseModel):
    """Унифицированная регенерация клипа с новыми настройками.

    Все поля опциональны. Если не задано — берём текущее значение из clip_data.
    Бэкенд считает минимальный уровень инвалидации:
      trim    → silent + ass + preeffects + fx + master
      template → ass + preeffects + fx + master
      effects → fx + master
      brand/cta → master
    """
    start: Optional[float] = None
    end: Optional[float] = None
    template: Optional[str] = None        # ключ шаблона субтитров
    brand: Optional[str] = None           # имя бренда
    cta: Optional[str] = None             # ключ CTA-пресета
    # эффекты — если ничего из enable_* не задано и нет hook_text_override → НЕ трогаем эффекты
    enable_zoom: Optional[bool] = None
    enable_emoji: Optional[bool] = None
    enable_hook: Optional[bool] = None
    enable_sfx: Optional[bool] = None
    hook_text_override: Optional[str] = None  # пустая строка → стереть hook
    provider: Optional[str] = None        # LLM-провайдер для эффектов (mlx-local и т.д.)
    apply_effects: Optional[bool] = None  # True → применять эффекты по toggles, False → отключить (без fx)


class CorrectionItem(BaseModel):
    start: float  # clip-relative
    end: float
    layout: str
    primary_face_id: Optional[int] = None
    primary_screen_idx: Optional[int] = None


class CorrectionsRequest(BaseModel):
    corrections: list[CorrectionItem]


@app.get("/jobs/{job_id}/clips/{clip_index}/scenes")
async def get_clip_scenes(job_id: str, clip_index: int):
    """Сегменты сцен для клипа в clip-relative time + доступные face_id."""
    from src.pipeline import _shift_segments_to_clip
    from src.smart_reframe import SceneSegment
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404)
    if clip_index < 1 or clip_index > len(job.clips):
        raise HTTPException(404)
    clip = job.clips[clip_index - 1]

    job_dir = WORK_DIR / job_id
    scenes_path = job_dir / "scenes.json"
    if not scenes_path.exists():
        raise HTTPException(409, "сцены не найдены — нужен повторный прогон")
    raw = json.loads(scenes_path.read_text())
    full = [SceneSegment(**s) for s in raw]
    clip_segments = _shift_segments_to_clip(full, clip["start"], clip["end"])

    # доступные face IDs из analysis.pkl (опционально)
    face_ids: list[int] = []
    analysis_path = job_dir / "analysis.pkl"
    if analysis_path.exists():
        import pickle
        a = pickle.loads(analysis_path.read_bytes())
        # отбираем треки, активные в окне [clip.start, clip.end] (в src-time)
        clip_s_f = int(clip["start"] * a.meta.fps)
        clip_e_f = int(clip["end"] * a.meta.fps)
        for t in a.tracks:
            if any(clip_s_f <= d.frame_idx <= clip_e_f for d in t.detections):
                face_ids.append(t.track_id)

    return {
        "clip_start": clip["start"],
        "clip_end": clip["end"],
        "clip_duration": clip["end"] - clip["start"],
        "segments": [
            {
                "start": s.start, "end": s.end,
                "layout": s.layout,
                "primary_face_id": s.primary_face_id,
                "primary_screen_idx": s.primary_screen_idx,
                "overridden": s.overridden,
            } for s in clip_segments
        ],
        "available_face_ids": sorted(set(face_ids)),
        "available_layouts": [
            "speaker_close", "active_speaker_close", "screen_full",
            "pip_speaker_screen", "wide_group", "wide_default", "split_screen",
        ],
    }


@app.post("/jobs/{job_id}/clips/{clip_index}/corrections")
async def apply_corrections_endpoint(
    job_id: str, clip_index: int, req: CorrectionsRequest,
):
    """Применяет коррекции (clip-relative) к клипу: re-render + mux + brand."""
    import pickle
    from src.smart_reframe import (
        SceneSegment, FrameCorrection,
        apply_corrections, render_smart,
    )
    from src.pipeline import _shift_segments_to_clip, slugify
    from src.subtitles import write_ass
    from src.render import RESOLUTIONS, mux_audio_and_subs, transcode
    from src.branding import load_brand
    from src.transcribe import Segment, Word

    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404)
    if clip_index < 1 or clip_index > len(job.clips):
        raise HTTPException(404)
    clip_data = job.clips[clip_index - 1]

    job_dir = WORK_DIR / job_id
    out_dir = job_dir / "output"
    dl_dir = job_dir / "downloads"
    src_path = dl_dir / clip_data.get("src_basename", "")
    if not src_path.exists():
        raise HTTPException(409, "исходник не найден")
    analysis_path = job_dir / "analysis.pkl"
    scenes_path = job_dir / "scenes.json"
    segments_path = job_dir / "segments.json"
    if not (analysis_path.exists() and scenes_path.exists() and segments_path.exists()):
        raise HTTPException(409, "кеш analyze отсутствует — нужен повторный прогон")

    analysis = pickle.loads(analysis_path.read_bytes())
    full_scenes = [SceneSegment(**s) for s in json.loads(scenes_path.read_text())]
    seg_raw = json.loads(segments_path.read_text())
    segments = [
        Segment(s["start"], s["end"], s["text"],
                [Word(w["start"], w["end"], w["text"]) for w in s.get("words", [])])
        for s in seg_raw
    ]

    fps = analysis.meta.fps
    # коррекции в clip-relative time → переводим в frame_range src-time
    src_corrections: list[FrameCorrection] = []
    for c in req.corrections:
        src_start = clip_data["start"] + c.start
        src_end = clip_data["start"] + c.end
        src_corrections.append(FrameCorrection(
            frame_range=(int(src_start * fps), int(src_end * fps)),
            layout=c.layout,
            primary_face_id=c.primary_face_id,
            primary_screen_idx=c.primary_screen_idx,
            note="user-correction",
        ))

    corrected_scenes = apply_corrections(full_scenes, src_corrections, fps=fps)

    # сохраняем коррекции на диск (для self-improvement loop)
    corrections_path = out_dir / f"{clip_data.get('slug', f'{clip_index:02d}')}.corrections.json"
    corrections_path.write_text(json.dumps([c.model_dump() for c in req.corrections], ensure_ascii=False))

    slug = clip_data.get("slug") or f"{clip_index:02d}-{slugify(clip_data['title'])}"
    (out_dir / "_cache").mkdir(exist_ok=True)
    silent = out_dir / "_cache" / f"{slug}.silent.mp4"
    subs = out_dir / "_cache" / f"{slug}.ass"
    master = out_dir / f"{slug}-1080p.mp4"

    clip_segments = _shift_segments_to_clip(corrected_scenes, clip_data["start"], clip_data["end"])
    # подбираем размер выхода под исходник (no upscale)
    from src.render import pick_master_size as _pms
    m_w, m_h = _pms(analysis.meta.src_w, analysis.meta.src_h, mode="native")
    await asyncio.to_thread(
        render_smart,
        video_path=src_path, analysis=analysis,
        segments=clip_segments, out_path=silent,
        start=clip_data["start"], end=clip_data["end"],
        target_w=m_w, target_h=m_h,
    )
    write_ass(segments, clip_data["start"], clip_data["end"], subs,
              target_w=m_w, target_h=m_h,
              template=clip_data.get("sub_template", "block"))
    with_subs = out_dir / f"{slug}.subs.mp4"
    await asyncio.to_thread(
        mux_audio_and_subs, silent, src_path, subs,
        clip_data["start"], clip_data["end"], with_subs,
    )
    try:
        brand_tpl = load_brand(clip_data.get("brand", "excella"))
        await asyncio.to_thread(apply_brand, with_subs, master, brand_tpl, cta_key=clip_data.get("cta", "demo"))
        with_subs.unlink(missing_ok=True)
    except Exception:
        with_subs.replace(master)
    files = {"1080p": master.name}
    for label, (w, h) in RESOLUTIONS.items():
        if label == "1080p":
            continue
        variant = out_dir / f"{slug}-{label}.mp4"
        await asyncio.to_thread(transcode, master, variant, w, h)
        files[label] = variant.name
    clip_data["files"] = files
    return {"ok": True, "clip": clip_data, "applied": len(src_corrections)}


@app.post("/jobs/{job_id}/clips/{clip_index}/retrim")
async def retrim_clip(job_id: str, clip_index: int, req: RetrimRequest):
    """Меняет границы клипа: re-render reframe + subs + brand + transcode."""
    import pickle
    from src.smart_reframe import SceneSegment, render_smart
    from src.subtitles import write_ass
    from src.render import RESOLUTIONS, mux_audio_and_subs, transcode
    from src.branding import load_brand
    from src.pipeline import _shift_segments_to_clip, slugify
    from src.transcribe import Segment, Word

    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404)
    if clip_index < 1 or clip_index > len(job.clips):
        raise HTTPException(404)
    clip_data = job.clips[clip_index - 1]

    new_start = max(0.0, float(req.start))
    new_end = float(req.end)
    if new_end - new_start < 5.0:
        raise HTTPException(400, "клип не может быть короче 5 секунд")
    if new_end - new_start > 120.0:
        raise HTTPException(400, "клип не может быть длиннее 120 секунд")

    job_dir = WORK_DIR / job_id
    out_dir = job_dir / "output"
    dl_dir = job_dir / "downloads"

    src_path = dl_dir / clip_data.get("src_basename", "")
    if not src_path.exists():
        raise HTTPException(409, "исходник не найден — нужен повторный полный прогон")

    analysis_path = job_dir / "analysis.pkl"
    scenes_path = job_dir / "scenes.json"
    segments_path = job_dir / "segments.json"
    if not (analysis_path.exists() and scenes_path.exists() and segments_path.exists()):
        raise HTTPException(409, "кеш analyze отсутствует — нужен повторный прогон")

    analysis = pickle.loads(analysis_path.read_bytes())
    scenes_raw = json.loads(scenes_path.read_text())
    full_scenes = [SceneSegment(**s) for s in scenes_raw]
    seg_raw = json.loads(segments_path.read_text())
    segments = [
        Segment(s["start"], s["end"], s["text"],
                [Word(w["start"], w["end"], w["text"]) for w in s.get("words", [])])
        for s in seg_raw
    ]

    slug = clip_data.get("slug") or f"{clip_index:02d}-{slugify(clip_data['title'])}"
    (out_dir / "_cache").mkdir(exist_ok=True)
    silent = out_dir / "_cache" / f"{slug}.silent.mp4"
    subs = out_dir / "_cache" / f"{slug}.ass"
    master = out_dir / f"{slug}-1080p.mp4"

    clip_segments = _shift_segments_to_clip(full_scenes, new_start, new_end)
    from src.render import pick_master_size as _pms
    m_w, m_h = _pms(analysis.meta.src_w, analysis.meta.src_h, mode="native")
    await asyncio.to_thread(
        render_smart,
        video_path=src_path, analysis=analysis,
        segments=clip_segments, out_path=silent,
        start=new_start, end=new_end,
        target_w=m_w, target_h=m_h,
    )
    write_ass(segments, new_start, new_end, subs,
              target_w=m_w, target_h=m_h,
              template=clip_data.get("sub_template", "block"))

    with_subs = out_dir / f"{slug}.subs.mp4"
    await asyncio.to_thread(
        mux_audio_and_subs, silent, src_path, subs,
        new_start, new_end, with_subs,
    )
    try:
        brand_tpl = load_brand(clip_data.get("brand", "excella"))
        await asyncio.to_thread(
            apply_brand, with_subs, master, brand_tpl,
            cta_key=clip_data.get("cta", "demo"),
        )
        with_subs.unlink(missing_ok=True)
    except Exception:
        with_subs.replace(master)

    files = {"1080p": master.name}
    for label, (w, h) in RESOLUTIONS.items():
        if label == "1080p":
            continue
        variant = out_dir / f"{slug}-{label}.mp4"
        await asyncio.to_thread(transcode, master, variant, w, h)
        files[label] = variant.name

    clip_data["start"] = new_start
    clip_data["end"] = new_end
    clip_data["files"] = files
    return {"ok": True, "clip": clip_data}


@app.post("/jobs/{job_id}/clips/{clip_index}/regen-meta")
async def regen_meta(job_id: str, clip_index: int):
    """Регенерация SEO-метаданных для клипа через Claude."""
    from src.metadata import collect_transcript_for_clip, generate_clip_meta
    from src.transcribe import Segment, Word
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404)
    if clip_index < 1 or clip_index > len(job.clips):
        raise HTTPException(404)
    clip_data = job.clips[clip_index - 1]
    job_dir = WORK_DIR / job_id
    segments_cache = job_dir / "segments.json"
    if not segments_cache.exists():
        raise HTTPException(409, "segments.json не найден — сначала сделай restyle или новый прогон")
    raw = json.loads(segments_cache.read_text())
    segments = [
        Segment(s["start"], s["end"], s["text"],
                [Word(w["start"], w["end"], w["text"]) for w in s.get("words", [])])
        for s in raw
    ]
    transcript_chunk = collect_transcript_for_clip(segments, clip_data["start"], clip_data["end"])

    brand = load_brand(clip_data.get("brand", "excella"))
    cta_obj = brand.cta_presets.get(clip_data.get("cta", brand.cta_default))
    cta_text = f"{cta_obj.text} {cta_obj.sub_text}".strip() if cta_obj else ""

    m = await asyncio.to_thread(
        generate_clip_meta,
        clip_title=clip_data["title"],
        clip_transcript=transcript_chunk,
        brand_name=brand.name,
        brand_lead_url=brand.lead_url,
        brand_niche=brand.niche,
        brand_audience=brand.target_audience,
        brand_voice=brand.brand_voice,
        cta_text=cta_text,
        clip_slug=clip_data.get("slug", ""),
    )
    clip_data["meta_title"] = m.title
    clip_data["meta_descriptions"] = m.descriptions
    clip_data["meta_hashtags"] = m.hashtags
    clip_data["meta_lead_links"] = m.lead_links
    return {"ok": True, "clip": clip_data, "usage": m.usage}


@app.post("/jobs/{job_id}/clips/{clip_index}/restyle")
async def restyle_clip(job_id: str, clip_index: int, req: RestyleRequest):
    """Перегенерация субтитров для существующего клипа БЕЗ перерендера reframe.

    Использует сохранённый <slug>.silent.mp4 + новый ASS по выбранному шаблону.
    Время: ~30 сек на клип (mux + transcode 720p/480p).
    """
    if req.template not in SUB_PRESETS:
        raise HTTPException(400, f"неизвестный шаблон: {req.template}")

    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job не найден")

    if clip_index < 1 or clip_index > len(job.clips):
        raise HTTPException(404, "клип не найден")
    clip_data = job.clips[clip_index - 1]

    job_dir = WORK_DIR / job_id
    out_dir = job_dir / "output"
    dl_dir = job_dir / "downloads"

    slug = clip_data.get("slug", "")
    src_basename = clip_data.get("src_basename", "")
    if not slug or not src_basename:
        raise HTTPException(409, "клип создан старым кодом, restyle недоступен — нужен повторный запуск")

    silent = out_dir / "_cache" / f"{slug}.silent.mp4"
    src_path = dl_dir / src_basename
    if not silent.exists() or not src_path.exists():
        raise HTTPException(409, "исходники не найдены — нужен повторный запуск")

    from src.transcribe import transcribe
    from src.subtitles import write_ass
    from src.render import RESOLUTIONS, mux_audio_and_subs, transcode

    # перетранскрибировать ради word-timestamps дорого; вместо этого
    # можно кешировать segments на диск. Пока — транскрипция per-restyle.
    # TODO: cache segments в jobs/<id>/segments.json
    segments_cache = job_dir / "segments.json"

    if segments_cache.exists():
        import json
        from src.transcribe import Segment, Word
        raw = json.loads(segments_cache.read_text())
        segments = [
            Segment(s["start"], s["end"], s["text"],
                    [Word(w["start"], w["end"], w["text"]) for w in s.get("words", [])])
            for s in raw
        ]
    else:
        segments = await asyncio.to_thread(transcribe, src_path, model_size="auto")
        import json
        segments_cache.write_text(json.dumps([
            {"start": s.start, "end": s.end, "text": s.text,
             "words": [{"start": w.start, "end": w.end, "text": w.text} for w in s.words]}
            for s in segments
        ], ensure_ascii=False))

    subs_path = out_dir / "_cache" / f"{slug}.ass"
    # ⭐ ищем мастер по высоте (не по file size!): парсим суффикс <N>p из имени файла
    candidates = []
    pattern = re.compile(rf"^{re.escape(slug)}-(\d+)p\.mp4$")
    for p in out_dir.glob(f"{slug}-*.mp4"):
        # пропускаем uniquify-варианты под платформы
        if any(plat in p.name for plat in ("youtube", "instagram", "vk", "tiktok")):
            continue
        if "silent" in p.name or "subs" in p.name:
            continue
        m = pattern.match(p.name)
        if not m:
            continue
        h = int(m.group(1))
        candidates.append((h, f"{h}p", p))
    if not candidates:
        raise HTTPException(409, "мастер-файл клипа не найден")
    candidates.sort(reverse=True)
    master_h_real, master_label, master = candidates[0]

    # узнаём размер мастера для правильного scale субтитров
    import subprocess as _sp
    probe = _sp.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(silent)],
        capture_output=True, text=True,
    )
    try:
        m_w, m_h = map(int, probe.stdout.strip().split(","))
    except Exception:
        m_w, m_h = 1080, 1920

    write_ass(segments, clip_data["start"], clip_data["end"], subs_path,
              target_w=m_w, target_h=m_h, template=req.template)
    await asyncio.to_thread(
        mux_audio_and_subs, silent, src_path, subs_path,
        clip_data["start"], clip_data["end"], master,
    )
    # ⭐ варианты только меньше ФАКТИЧЕСКОГО разрешения мастера (m_h из ffprobe silent.mp4)
    files = {master_label: master.name}
    from src.render import variants_below as _vb
    for label, (w, h) in _vb(m_h).items():
        if label == master_label or h >= m_h:
            continue
        variant = out_dir / f"{slug}-{label}.mp4"
        if variant.resolve() == master.resolve():
            continue
        await asyncio.to_thread(transcode, master, variant, w, h)
        files[label] = variant.name

    # обновляем in-memory job state
    clip_data["files"] = files
    clip_data["sub_template"] = req.template
    return {"ok": True, "clip": clip_data}


@app.post("/jobs/{job_id}/clips/{clip_index}/regenerate-effects")
async def regenerate_effects_endpoint(job_id: str, clip_index: int, req: EffectsRegenRequest):
    """Перегенерация эффектов поверх pre-effects кэша БЕЗ полного re-render.

    Pipeline сохраняет <slug>.preeffects.mp4 (subs + audio + face overlay, без brand
    и без эффектов). Здесь мы:
      1) читаем segments.json для LLM-планировщика;
      2) plan_effects(...) → новый план;
      3) если задан hook_text_override — переписываем plan.hook.text;
      4) apply_effects(preeffects → with_fx);
      5) apply_brand(with_fx → master);
      6) transcode на варианты.

    Время: ~5-15 сек на клип (один LLM-запрос + один ffmpeg-pass + brand).
    """
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job не найден")
    if clip_index < 1 or clip_index > len(job.clips):
        raise HTTPException(404, "клип не найден")
    clip_data = job.clips[clip_index - 1]

    job_dir = WORK_DIR / job_id
    out_dir = job_dir / "output"
    cache_dir = out_dir / "_cache"

    slug = clip_data.get("slug", "")
    if not slug:
        raise HTTPException(409, "клип без slug — нужен повторный запуск")

    preeffects = cache_dir / f"{slug}.preeffects.mp4"
    if not preeffects.exists():
        raise HTTPException(409,
            "preeffects.mp4 не найден — клип создан до фичи. Сначала пересоздай клип "
            "(restyle или новый прогон) — после этого regenerate-effects будет работать.")

    segments_cache = job_dir / "segments.json"
    if not segments_cache.exists():
        raise HTTPException(409, "segments.json не найден — нужен повторный прогон")

    import json as _json
    from src.transcribe import Segment, Word
    raw = _json.loads(segments_cache.read_text())
    segments = [
        Segment(s["start"], s["end"], s["text"],
                [Word(w["start"], w["end"], w["text"]) for w in s.get("words", [])])
        for s in raw
    ]

    # ffprobe preeffects.mp4 → размеры
    import subprocess as _sp
    probe = _sp.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(preeffects)],
        capture_output=True, text=True,
    )
    try:
        m_w, m_h = map(int, probe.stdout.strip().split(","))
    except Exception:
        m_w, m_h = 1080, 1920

    # план через LLM
    from src.effects import apply_effects, plan_effects, write_plan_json

    try:
        plan = await asyncio.to_thread(
            plan_effects,
            segments=segments,
            clip_start=clip_data["start"], clip_end=clip_data["end"],
            clip_title=clip_data.get("title", ""),
            enable_zoom=req.enable_zoom,
            enable_emoji=req.enable_emoji,
            enable_sfx=req.enable_sfx,
            enable_hook=req.enable_hook,
            provider=req.provider,
        )
    except Exception as e:
        raise HTTPException(500, f"LLM не выдал план: {e}")

    # переопределение hook
    if req.hook_text_override is not None:
        if not req.hook_text_override.strip():
            plan.hook = None  # стереть hook
        else:
            from src.effects import HookOverlay
            if plan.hook:
                plan.hook.text = req.hook_text_override.strip()
            else:
                plan.hook = HookOverlay(text=req.hook_text_override.strip())

    write_plan_json(plan, cache_dir / f"{slug}.effects.json")

    # применяем эффекты поверх preeffects
    with_fx = cache_dir / f"{slug}.fx.mp4"
    with_fx.unlink(missing_ok=True)
    if plan.is_empty():
        # ничего не применяем — просто копируем preeffects → with_fx, дальше brand
        shutil.copy2(preeffects, with_fx)
    else:
        try:
            await asyncio.to_thread(
                apply_effects,
                input_video=preeffects, output_video=with_fx,
                plan=plan, target_w=m_w, target_h=m_h,
                elevenlabs_api_key=os.environ.get("ELEVENLABS_API_KEY", "").strip() or None,
            )
        except Exception as e:
            raise HTTPException(500, f"apply_effects упал: {e}")

    if not with_fx.exists() or with_fx.stat().st_size == 0:
        raise HTTPException(500, "with_fx не создан")

    # ── brand (CTA + watermark + bottom strip) поверх with_fx → master ──
    from src.branding import apply_brand, load_brand
    from src.render import transcode, variants_below

    brand_name = clip_data.get("brand", "excella")
    cta_key = clip_data.get("cta", "demo")
    try:
        brand_tpl = load_brand(brand_name)
    except Exception:
        brand_tpl = None

    # ищем имя текущего мастера, чтобы перезаписать его
    master_h_real, master_label, master_name = _pick_master_from_files(clip_data["files"])
    master = out_dir / master_name

    if brand_tpl is not None:
        try:
            # face overlay уже наложен в pre-effects цепочке, поэтому skip_face_overlay=True
            await asyncio.to_thread(
                lambda: apply_brand(with_fx, master, brand_tpl,
                                   cta_key=cta_key, target_w=m_w, target_h=m_h,
                                   skip_face_overlay=True),
            )
        except Exception:
            # если brand не применился — просто копируем with_fx → master
            shutil.copy2(with_fx, master)
    else:
        shutil.copy2(with_fx, master)

    # перегенерим только meньшие варианты (никакого upscale)
    files = {master_label: master.name}
    for label, (w, h) in variants_below(master_h_real).items():
        if h >= master_h_real:
            continue
        variant = out_dir / f"{slug}-{label}.mp4"
        await asyncio.to_thread(transcode, master, variant, w, h)
        files[label] = variant.name

    clip_data["files"].update(files)
    clip_data["effects_applied"] = {
        "accents": len(plan.accents),
        "emojis": len(plan.emojis),
        "sfx": len(plan.sfx),
        "hook": plan.hook.text if plan.hook else None,
    }
    _save_job_state(job)
    return {"ok": True, "clip": clip_data, "plan": plan.to_dict()}


@app.post("/jobs/{job_id}/clips/{clip_index}/regenerate")
async def regenerate_clip(job_id: str, clip_index: int, req: RegenerateRequest):
    """Унифицированная регенерация клипа с новыми настройками.

    Реализует минимальную инвалидацию кеша:
    - trim (start/end меняется > 0.05с) → пере-render reframe (silent.mp4)
    - template меняется → пере-генерация subs (ASS) + face overlay + mux → preeffects.mp4
    - effects меняются → пере-генерация плана + apply_effects → fx.mp4
    - brand/cta меняются → apply_brand → master + transcode variants

    Все шаги идут вниз каскадом — если изменился trim, всё пересчитывается заново.
    Возвращает обновлённое clip_data + флаг what_changed для UI.
    """
    import pickle
    from src.smart_reframe import SceneSegment, render_smart
    from src.subtitles import write_ass
    from src.render import (
        RESOLUTIONS, mux_audio_and_subs, transcode, variants_below, pick_master_size,
    )
    from src.branding import apply_brand, apply_face_overlay_only, load_brand
    from src.pipeline import _shift_segments_to_clip, slugify
    from src.transcribe import Segment, Word
    from src.effects import apply_effects, plan_effects, write_plan_json

    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job не найден")
    if clip_index < 1 or clip_index > len(job.clips):
        raise HTTPException(404, "клип не найден")
    clip_data = job.clips[clip_index - 1]

    job_dir = WORK_DIR / job_id
    out_dir = job_dir / "output"
    dl_dir = job_dir / "downloads"
    cache_dir = out_dir / "_cache"
    cache_dir.mkdir(exist_ok=True)

    slug = clip_data.get("slug", "")
    src_basename = clip_data.get("src_basename", "")
    if not slug or not src_basename:
        raise HTTPException(409, "клип создан старым кодом — нужен повторный полный запуск")

    src_path = dl_dir / src_basename
    if not src_path.exists():
        raise HTTPException(409, "исходник не найден — нужен повторный полный запуск")

    # ── вычисляем что изменилось ──
    cur_start = float(clip_data.get("start", 0.0))
    cur_end = float(clip_data.get("end", 0.0))
    cur_template = clip_data.get("sub_template", "block")
    cur_brand = clip_data.get("brand", "excella")
    cur_cta = clip_data.get("cta", "demo")

    new_start = float(req.start) if req.start is not None else cur_start
    new_end = float(req.end) if req.end is not None else cur_end
    new_template = req.template or cur_template
    new_brand = req.brand or cur_brand
    new_cta = req.cta or cur_cta

    # валидация template
    if req.template is not None and req.template not in SUB_PRESETS:
        raise HTTPException(400, f"неизвестный шаблон субтитров: {req.template}")

    # валидация trim
    if new_end - new_start < 5.0:
        raise HTTPException(400, "клип не может быть короче 5 секунд")
    if new_end - new_start > 120.0:
        raise HTTPException(400, "клип не может быть длиннее 120 секунд")
    if new_start < 0:
        raise HTTPException(400, "start не может быть отрицательным")

    trim_changed = abs(new_start - cur_start) > 0.05 or abs(new_end - cur_end) > 0.05
    template_changed = new_template != cur_template
    brand_changed = new_brand != cur_brand
    cta_changed = new_cta != cur_cta

    # эффекты: если есть любой из enable_* флагов или hook_text_override или apply_effects — применяем
    effects_requested = (
        req.enable_zoom is not None or req.enable_emoji is not None or
        req.enable_hook is not None or req.enable_sfx is not None or
        req.hook_text_override is not None or req.apply_effects is not None
    )

    # ── читаем кеш analysis + scenes + segments ──
    analysis_path = job_dir / "analysis.pkl"
    scenes_path = job_dir / "scenes.json"
    segments_path = job_dir / "segments.json"
    if not (analysis_path.exists() and scenes_path.exists() and segments_path.exists()):
        raise HTTPException(409,
            "кеш analyze/scenes/segments отсутствует — нужен повторный полный запуск")

    analysis = pickle.loads(analysis_path.read_bytes())
    scenes_raw = json.loads(scenes_path.read_text())
    full_scenes = [SceneSegment(**s) for s in scenes_raw]
    seg_raw = json.loads(segments_path.read_text())
    segments = [
        Segment(s["start"], s["end"], s["text"],
                [Word(w["start"], w["end"], w["text"]) for w in s.get("words", [])])
        for s in seg_raw
    ]

    # размеры мастера
    m_w, m_h = pick_master_size(analysis.meta.src_w, analysis.meta.src_h, mode="native")
    master_label = f"{m_h}p"

    # ── загрузка brand'а (нужен и для face_overlay, и для apply_brand) ──
    try:
        brand_tpl = load_brand(new_brand)
    except Exception as e:
        raise HTTPException(400, f"бренд '{new_brand}' не найден: {e}")

    silent = cache_dir / f"{slug}.silent.mp4"
    silent_face = cache_dir / f"{slug}.silent_face.mp4"
    subs_path = cache_dir / f"{slug}.ass"
    preeffects = cache_dir / f"{slug}.preeffects.mp4"
    fx_path = cache_dir / f"{slug}.fx.mp4"

    what_changed: list[str] = []

    # ── 1. silent (reframe) — если trim изменился ──
    if trim_changed or not silent.exists():
        what_changed.append("silent" if trim_changed else "silent_recovered")
        clip_segments = _shift_segments_to_clip(full_scenes, new_start, new_end)
        await asyncio.to_thread(
            render_smart,
            video_path=src_path, analysis=analysis,
            segments=clip_segments, out_path=silent,
            start=new_start, end=new_end,
            target_w=m_w, target_h=m_h,
        )

    # ── 2. ass + face overlay + mux → preeffects.mp4 ──
    # инвалидация: trim или template или brand_changed (face overlay меняется при смене бренда)
    rebuild_preeffects = (
        trim_changed or template_changed or brand_changed or not preeffects.exists()
    )
    if rebuild_preeffects:
        what_changed.append("preeffects")
        # 2a. ass
        write_ass(segments, new_start, new_end, subs_path,
                  target_w=m_w, target_h=m_h, template=new_template)

        # 2b. face overlay (наносится на silent → silent_face). Зависит от brand_tpl
        silent_for_subs = silent
        if brand_tpl is not None:
            try:
                result_path = await asyncio.to_thread(
                    apply_face_overlay_only, silent, silent_face, brand_tpl,
                )
                if result_path == silent_face and silent_face.exists():
                    silent_for_subs = silent_face
            except Exception:
                silent_for_subs = silent

        # 2c. mux subs + audio → preeffects
        await asyncio.to_thread(
            mux_audio_and_subs, silent_for_subs, src_path, subs_path,
            new_start, new_end, preeffects,
        )

    # ── 3. эффекты (опц.) → fx.mp4 ──
    # инвалидация: всё, что выше + effects_requested
    rebuild_fx = effects_requested or rebuild_preeffects

    # текущее состояние эффектов из state — чтобы не сбрасывать toggles при изменении только бренда
    cur_effects = clip_data.get("effects_applied") or {}
    use_effects = (
        req.apply_effects
        if req.apply_effects is not None
        # если пользователь не указал apply_effects, но есть toggles — считаем что хочет эффекты
        else (effects_requested or bool(cur_effects))
    )

    plan_dict_for_response: Optional[dict] = None
    fx_input = preeffects  # input для apply_brand на следующем шаге
    if use_effects and rebuild_fx:
        what_changed.append("fx")
        # дефолты для toggles — из cur_effects если есть, иначе True
        zoom_on = req.enable_zoom if req.enable_zoom is not None else bool(cur_effects.get("accents", 1))
        emoji_on = req.enable_emoji if req.enable_emoji is not None else bool(cur_effects.get("emojis", 1))
        hook_on = req.enable_hook if req.enable_hook is not None else bool(cur_effects.get("hook"))
        sfx_on = req.enable_sfx if req.enable_sfx is not None else bool(cur_effects.get("sfx", 0))

        try:
            plan = await asyncio.to_thread(
                plan_effects,
                segments=segments,
                clip_start=new_start, clip_end=new_end,
                clip_title=clip_data.get("title", ""),
                enable_zoom=zoom_on,
                enable_emoji=emoji_on,
                enable_sfx=sfx_on,
                enable_hook=hook_on,
                provider=req.provider,
            )
        except Exception as e:
            raise HTTPException(500, f"LLM не выдал план эффектов: {e}")

        # переопределение hook
        if req.hook_text_override is not None:
            text = req.hook_text_override.strip()
            if not text:
                plan.hook = None
            else:
                from src.effects import HookOverlay
                if plan.hook:
                    plan.hook.text = text
                else:
                    plan.hook = HookOverlay(text=text)

        write_plan_json(plan, cache_dir / f"{slug}.effects.json")

        if plan.is_empty():
            shutil.copy2(preeffects, fx_path)
        else:
            try:
                await asyncio.to_thread(
                    apply_effects,
                    input_video=preeffects, output_video=fx_path,
                    plan=plan, target_w=m_w, target_h=m_h,
                    elevenlabs_api_key=os.environ.get("ELEVENLABS_API_KEY", "").strip() or None,
                )
            except Exception as e:
                raise HTTPException(500, f"apply_effects упал: {e}")
        if not fx_path.exists() or fx_path.stat().st_size == 0:
            raise HTTPException(500, "fx не создан")
        fx_input = fx_path
        plan_dict_for_response = plan.to_dict()
        clip_data["effects_applied"] = {
            "accents": len(plan.accents),
            "emojis": len(plan.emojis),
            "sfx": len(plan.sfx),
            "hook": plan.hook.text if plan.hook else None,
        }
    elif use_effects and fx_path.exists():
        # эффекты не пересчитывались, но fx есть — используем его
        fx_input = fx_path
    elif not use_effects and req.apply_effects is False:
        # пользователь явно выключил эффекты
        what_changed.append("effects_off")
        fx_path.unlink(missing_ok=True)
        clip_data["effects_applied"] = None
        fx_input = preeffects

    # ── 4. apply_brand → master + transcode variants ──
    # инвалидация: что-то выше менялось ИЛИ brand/cta поменялись.
    # Если ничего не изменилось вообще — возвращаемся с пустым what_changed.
    master_h_real, master_label_real, master_name = _pick_master_from_files(clip_data.get("files", {}))
    master = out_dir / master_name
    # если фактическое разрешение отличается от рассчитанного (редко) — переименуем
    if master_h_real != m_h:
        master = out_dir / f"{slug}-{m_h}p.mp4"

    needs_master_rebuild = bool(what_changed) or brand_changed or cta_changed
    files = clip_data.get("files", {}) or {}

    if needs_master_rebuild:
        if brand_tpl is not None:
            try:
                await asyncio.to_thread(
                    apply_brand, fx_input, master, brand_tpl,
                    cta_key=new_cta, target_w=m_w, target_h=m_h,
                    skip_face_overlay=True,
                )
            except Exception as e:
                shutil.copy2(fx_input, master)
                raise HTTPException(500, f"apply_brand упал: {e}")
        else:
            shutil.copy2(fx_input, master)

        what_changed.append("brand_master")

        # ── 5. transcode варианты только МЕНЬШЕ master ──
        files = {f"{m_h}p": master.name}
        for label, (w, h) in variants_below(m_h).items():
            if h >= m_h:
                continue
            variant = out_dir / f"{slug}-{label}.mp4"
            if variant.resolve() == master.resolve():
                continue
            await asyncio.to_thread(transcode, master, variant, w, h)
            files[label] = variant.name

        # удаляем старые варианты других master_label (если master_h поменялся)
        for old_label, old_name in (clip_data.get("files") or {}).items():
            if old_label not in files and not any(plat in old_name for plat in ("youtube", "instagram", "vk", "tiktok")):
                old_p = out_dir / old_name
                if old_p.resolve() != master.resolve() and old_p.exists():
                    try:
                        old_p.unlink()
                    except Exception:
                        pass

    # ── 6. update clip_data ──
    clip_data["start"] = new_start
    clip_data["end"] = new_end
    clip_data["sub_template"] = new_template
    clip_data["brand"] = new_brand
    clip_data["cta"] = new_cta
    clip_data["files"] = files
    _save_job_state(job)

    return {
        "ok": True,
        "clip": clip_data,
        "what_changed": what_changed,
        "plan": plan_dict_for_response,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

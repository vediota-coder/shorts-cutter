"""Instagram Reels автопубликация через Meta Graph API.

Требования (это серьёзно — Meta так устроила):
1. Instagram Business или Creator аккаунт.
2. Связанный Facebook Page.
3. Зарегистрированное приложение на developers.facebook.com.
4. Long-lived User Access Token со scope:
   - instagram_basic
   - instagram_content_publish
   - pages_read_engagement
   - pages_show_list
   - business_management
5. **Видео должно быть доступно по ПУБЛИЧНОМУ URL** — Meta скачивает его сама.
   На localhost не работает — нужен ngrok/cloudflared/публичный домен.

Получить токен: developers.facebook.com → Tools → Graph API Explorer → User Token →
обменять на long-lived через debug_token endpoint (живёт ~60 дней).
В прод — обновлять.

Upload pipeline:
1. POST /{ig-user-id}/media   media_type=REELS, video_url=..., caption=...
   → возвращает creation_id (container_id)
2. POLL /{container_id}?fields=status_code   пока не FINISHED (или ERROR)
3. POST /{ig-user-id}/media_publish?creation_id=...
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests


GRAPH_API = "https://graph.facebook.com/v21.0"
OAUTH_DIR = Path(__file__).parent.parent.parent / "branding" / "_oauth"


def _token_path(brand: str) -> Path:
    return OAUTH_DIR / f"{brand}.instagram.json"


@dataclass
class IGStatus:
    connected: bool
    ig_user_id: str = ""
    username: str = ""
    public_base_url: str = ""
    error: str = ""


def get_status(brand: str) -> IGStatus:
    OAUTH_DIR.mkdir(parents=True, exist_ok=True)
    p = _token_path(brand)
    if not p.exists():
        return IGStatus(connected=False)
    cfg = json.loads(p.read_text())
    token = cfg.get("access_token")
    ig_user = cfg.get("ig_user_id")
    public_base = cfg.get("public_base_url", "")
    if not token or not ig_user:
        return IGStatus(connected=False, public_base_url=public_base, error="нет токена или ig_user_id")
    try:
        r = requests.get(
            f"{GRAPH_API}/{ig_user}",
            params={"fields": "username", "access_token": token},
            timeout=15,
        ).json()
        if "error" in r:
            return IGStatus(connected=False, public_base_url=public_base,
                           error=r["error"].get("message", "?"))
        return IGStatus(
            connected=True, ig_user_id=ig_user,
            username=r.get("username", ""), public_base_url=public_base,
        )
    except Exception as e:
        return IGStatus(connected=False, public_base_url=public_base, error=str(e))


def save_token(brand: str, access_token: str, ig_user_id: str, public_base_url: str = "") -> None:
    OAUTH_DIR.mkdir(parents=True, exist_ok=True)
    p = _token_path(brand)
    p.write_text(json.dumps({
        "access_token": access_token.strip(),
        "ig_user_id": str(ig_user_id).strip(),
        "public_base_url": public_base_url.rstrip("/"),
    }, ensure_ascii=False))
    p.chmod(0o600)


def disconnect(brand: str) -> None:
    p = _token_path(brand)
    if p.exists():
        p.unlink()


def upload_reel(
    *,
    brand: str,
    video_url: str,             # ПУБЛИЧНЫЙ url, по которому Meta скачает файл
    caption: str,
    cover_url: Optional[str] = None,
    share_to_feed: bool = True,
    poll_interval: float = 4.0,
    max_wait: float = 300.0,
) -> dict:
    cfg = json.loads(_token_path(brand).read_text())
    token = cfg["access_token"]
    ig_user = cfg["ig_user_id"]

    # шаг 1: контейнер
    create = requests.post(
        f"{GRAPH_API}/{ig_user}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": (caption or "")[:2200],
            "share_to_feed": "true" if share_to_feed else "false",
            **({"cover_url": cover_url} if cover_url else {}),
            "access_token": token,
        },
        timeout=30,
    ).json()
    if "error" in create:
        raise RuntimeError(f"IG /media: {create['error'].get('message', '?')}")
    container_id = create["id"]

    # шаг 2: ждём FINISHED
    deadline = time.time() + max_wait
    while time.time() < deadline:
        s = requests.get(
            f"{GRAPH_API}/{container_id}",
            params={"fields": "status_code,status", "access_token": token},
            timeout=15,
        ).json()
        code = s.get("status_code")
        if code == "FINISHED":
            break
        if code == "ERROR":
            raise RuntimeError(f"IG container ERROR: {s.get('status', '')}")
        time.sleep(poll_interval)
    else:
        raise TimeoutError("IG не успел обработать видео за отведённое время")

    # шаг 3: публикуем
    pub = requests.post(
        f"{GRAPH_API}/{ig_user}/media_publish",
        data={"creation_id": container_id, "access_token": token},
        timeout=30,
    ).json()
    if "error" in pub:
        raise RuntimeError(f"IG /media_publish: {pub['error'].get('message', '?')}")
    media_id = pub["id"]
    return {
        "media_id": media_id,
        "url": f"https://www.instagram.com/p/{media_id}/",
        "container_id": container_id,
    }


def fetch_stats(brand: str, media_id: str) -> dict:
    """Метрики Reels через /insights."""
    cfg = json.loads(_token_path(brand).read_text())
    token = cfg["access_token"]
    metrics = "views,reach,likes,comments,saved,shares"
    r = requests.get(
        f"{GRAPH_API}/{media_id}/insights",
        params={"metric": metrics, "access_token": token},
        timeout=15,
    ).json()
    if "error" in r:
        raise RuntimeError(r["error"].get("message", "?"))
    out: dict[str, int] = {}
    for item in r.get("data", []):
        name = item.get("name")
        values = item.get("values", [])
        if values:
            out[name] = int(values[0].get("value", 0) or 0)
    return out

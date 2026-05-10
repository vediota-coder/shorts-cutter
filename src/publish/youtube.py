"""YouTube Shorts автопубликация через Google Data API v3.

Поток:
1. Пользователь регистрирует OAuth-приложение в Google Cloud Console:
   - APIs → YouTube Data API v3 (включить)
   - Credentials → OAuth 2.0 Client ID → Desktop app → скачать JSON
2. JSON помещается в branding/_oauth/<brand>.client.json
3. start_oauth(brand) — открывает браузер для согласия, сохраняет токен в
   branding/_oauth/<brand>.youtube_token.json
4. upload_video(brand, video_path, ...) — загружает с тегом #Shorts

Для шортсов важно:
- Видео ≤ 60 сек, вертикальное 9:16 → YouTube автоматически распознаёт как Short
- Title до 100 симв., description до 5000
- Тег #Shorts в начале title или в description ускоряет распознавание
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",  # для channels.list?mine=true
    "https://www.googleapis.com/auth/youtube",  # videos.update (правка description/tags)
]
OAUTH_DIR = Path(__file__).parent.parent.parent / "branding" / "_oauth"


def _client_secrets_path(brand: str) -> Path:
    return OAUTH_DIR / f"{brand}.client.json"


def _token_path(brand: str) -> Path:
    return OAUTH_DIR / f"{brand}.youtube_token.json"


@dataclass
class YouTubeStatus:
    connected: bool
    has_client_secrets: bool
    channel_title: str = ""
    channel_id: str = ""
    error: str = ""


def get_status(brand: str) -> YouTubeStatus:
    OAUTH_DIR.mkdir(parents=True, exist_ok=True)
    has_client = _client_secrets_path(brand).exists()
    tok = _token_path(brand)
    if not tok.exists():
        return YouTubeStatus(connected=False, has_client_secrets=has_client)
    try:
        creds = Credentials.from_authorized_user_file(str(tok), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            tok.write_text(creds.to_json())
        yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
        ch = yt.channels().list(part="snippet", mine=True).execute()
        items = ch.get("items", [])
        if not items:
            return YouTubeStatus(connected=False, has_client_secrets=has_client,
                                 error="канал не найден")
        snip = items[0]["snippet"]
        return YouTubeStatus(
            connected=True, has_client_secrets=has_client,
            channel_title=snip.get("title", ""), channel_id=items[0]["id"],
        )
    except Exception as e:
        return YouTubeStatus(connected=False, has_client_secrets=has_client, error=str(e))


def save_client_secrets(brand: str, json_data: bytes) -> None:
    OAUTH_DIR.mkdir(parents=True, exist_ok=True)
    parsed = json.loads(json_data)
    if "installed" not in parsed and "web" not in parsed:
        raise ValueError("Не похоже на client_secrets.json — нужен Desktop OAuth тип")
    p = _client_secrets_path(brand)
    p.write_bytes(json_data)
    p.chmod(0o600)


def disconnect(brand: str) -> None:
    p = _token_path(brand)
    if p.exists():
        p.unlink()


def start_oauth(brand: str) -> Credentials:
    """Запускает OAuth flow в локальном браузере. Блокирующий — нужно вызывать в thread."""
    cs = _client_secrets_path(brand)
    if not cs.exists():
        raise FileNotFoundError(
            f"Нет client_secrets для бренда {brand}. "
            "Загрузите его в настройках бренда (Подключить YouTube)."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(cs), SCOPES)
    creds = flow.run_local_server(
        port=0,
        prompt="consent",
        authorization_prompt_message="Откройте браузер для авторизации YouTube",
        success_message="Готово! Можете закрыть эту вкладку.",
    )
    tok = _token_path(brand)
    tok.write_text(creds.to_json())
    tok.chmod(0o600)
    return creds


def inject_hashtags(description: str, tags: list[str], limit: int = 4900) -> str:
    """Дописывает хештеги в description, если их там ещё нет.

    YouTube Shorts использует хештеги из description (не из snippet.tags) для
    кликабельных линков под видео и сигналов алгоритму. snippet.tags невидимо
    для зрителя и работает только на поисковый индекс.
    """
    desc = (description or "").rstrip()
    desc_lower = desc.lower()
    extras = []
    for t in tags or []:
        h = t if t.startswith("#") else f"#{t}"
        if h.lower() in desc_lower:
            continue
        extras.append(h)
    if not extras:
        return desc
    suffix = "\n\n" + " ".join(extras)
    combined = (desc + suffix)[:limit]
    return combined


def _credentials(brand: str) -> Credentials:
    tok = _token_path(brand)
    if not tok.exists():
        raise RuntimeError(f"YouTube не подключён для бренда {brand}")
    creds = Credentials.from_authorized_user_file(str(tok), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        tok.write_text(creds.to_json())
    return creds


def upload_video(
    *,
    brand: str,
    video_path: Path,
    title: str,
    description: str,
    tags: list[str],
    privacy: str = "public",  # public | unlisted | private
    category_id: str = "22",  # People & Blogs (универсально для шортсов)
) -> dict:
    creds = _credentials(brand)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)

    title_clean = (title or "")[:95]
    if "#shorts" not in title_clean.lower() and "#shorts" not in (description or "").lower():
        title_clean = (title_clean + " #Shorts")[:100]

    description_with_tags = inject_hashtags(description or "", tags or [])

    body = {
        "snippet": {
            "title": title_clean,
            "description": description_with_tags[:4900],
            "tags": [t.lstrip("#") for t in tags[:30]],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = req.next_chunk()
        # status.progress() можно показывать наружу; пока просто крутим до конца
    video_id = response.get("id")
    return {
        "video_id": video_id,
        "url": f"https://youtube.com/shorts/{video_id}" if video_id else None,
        "title": title_clean,
    }


def get_snippet(brand: str, video_id: str) -> dict:
    """Возвращает snippet (title, description, tags, categoryId) видео."""
    creds = _credentials(brand)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    r = yt.videos().list(part="snippet", id=video_id).execute()
    items = r.get("items", [])
    if not items:
        return {}
    return items[0].get("snippet", {})


def update_description(*, brand: str, video_id: str, description: str,
                      tags: list[str] | None = None) -> dict:
    """Обновляет description (и опционально tags) уже опубликованного видео.

    videos.update требует полный snippet с title и categoryId — иначе они
    стираются. Поэтому читаем текущий snippet и патчим только нужные поля.
    """
    creds = _credentials(brand)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    cur = yt.videos().list(part="snippet", id=video_id).execute()
    items = cur.get("items", [])
    if not items:
        raise RuntimeError(f"видео {video_id} не найдено / нет доступа")
    snippet = items[0]["snippet"]
    snippet["description"] = description[:4900]
    if tags is not None:
        snippet["tags"] = [t.lstrip("#") for t in tags[:30]]
    body = {"id": video_id, "snippet": snippet}
    return yt.videos().update(part="snippet", body=body).execute()


def fetch_stats(brand: str, video_id: str) -> dict:
    """Возвращает базовую статистику видео: views/likes/comments."""
    creds = _credentials(brand)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    r = yt.videos().list(part="statistics", id=video_id).execute()
    items = r.get("items", [])
    if not items:
        return {}
    s = items[0].get("statistics", {})
    return {
        "views": int(s.get("viewCount", 0)),
        "likes": int(s.get("likeCount", 0)),
        "comments": int(s.get("commentCount", 0)),
    }

"""ВК Клипы автопубликация через VK API.

Аутентификация: пользователь получает access_token через Implicit Flow
(https://oauth.vk.com/authorize?client_id=...&display=page&scope=video,offline&...).
Это даёт долгоживущий токен, который мы сохраняем.

Загрузка через shortVideo.create — НАТИВНЫЙ Klips-эндпоинт:
1. shortVideo.create(name, description, group_id) → upload_url
2. multipart POST upload_url с файлом → video_id
Видео попадает в раздел «Клипы», а не «Видео», и не получает фолбэк-метку
«дуэт с DELETED», которую VK вешает при загрузке через video.save (старый
desktop-эндпоинт).
"""
from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import requests


API_VERSION = "5.199"
OAUTH_DIR = Path(__file__).parent.parent.parent / "branding" / "_oauth"


def _token_path(brand: str) -> Path:
    return OAUTH_DIR / f"{brand}.vk.json"


@dataclass
class VKStatus:
    connected: bool
    user_name: str = ""
    user_id: int = 0
    target_owner_id: int = 0   # куда публикуем: положительное = пользователь, отрицательное = группа
    target_name: str = ""
    error: str = ""


def get_status(brand: str) -> VKStatus:
    OAUTH_DIR.mkdir(parents=True, exist_ok=True)
    p = _token_path(brand)
    if not p.exists():
        return VKStatus(connected=False)
    try:
        cfg = json.loads(p.read_text())
        token = cfg.get("access_token")
        if not token:
            return VKStatus(connected=False, error="нет access_token в конфиге")
        # проверяем токен через users.get
        r = requests.get(
            "https://api.vk.com/method/users.get",
            params={"access_token": token, "v": API_VERSION},
            timeout=10,
        ).json()
        if "error" in r:
            return VKStatus(connected=False, error=r["error"].get("error_msg", "?"))
        user = r["response"][0]
        target_owner = cfg.get("target_owner_id") or user["id"]
        target_name = cfg.get("target_name") or f"{user['first_name']} {user['last_name']}"
        return VKStatus(
            connected=True,
            user_name=f"{user['first_name']} {user['last_name']}",
            user_id=user["id"],
            target_owner_id=target_owner,
            target_name=target_name,
        )
    except Exception as e:
        return VKStatus(connected=False, error=str(e))


def save_token(brand: str, access_token: str, target_owner_id: int = 0, target_name: str = "") -> None:
    OAUTH_DIR.mkdir(parents=True, exist_ok=True)
    p = _token_path(brand)
    cfg = {"access_token": access_token.strip()}
    if target_owner_id:
        cfg["target_owner_id"] = int(target_owner_id)
    if target_name:
        cfg["target_name"] = target_name
    p.write_text(json.dumps(cfg, ensure_ascii=False))
    p.chmod(0o600)


def disconnect(brand: str) -> None:
    p = _token_path(brand)
    if p.exists():
        p.unlink()


def build_oauth_url(client_id: str, redirect_uri: str = "https://oauth.vk.com/blank.html") -> str:
    """Возвращает URL для Implicit Flow.

    Юзер открывает, авторизуется, копирует access_token из URL после redirect.
    """
    params = {
        "client_id": client_id,
        "display": "page",
        "redirect_uri": redirect_uri,
        "scope": "video,offline,groups",
        "response_type": "token",
        "v": API_VERSION,
    }
    return "https://oauth.vk.com/authorize?" + urllib.parse.urlencode(params)


def _probe_duration(video_path: Path) -> float:
    import subprocess
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(video_path)],
            capture_output=True, text=True, check=True, timeout=10,
        )
        return float(r.stdout.strip() or 0.0)
    except Exception:
        return 0.0


def upload_video(
    *,
    brand: str,
    video_path: Path,
    title: str,
    description: str,
    privacy: str = "all",   # all | friends | nobody (для совместимости — shortVideo не использует)
) -> dict:
    """Загружает в VK. Если видео ≤60с → Клипы (shortVideo.create), иначе → Видео (video.save).

    VK Klips отбрасывает всё что длиннее 60 секунд — поэтому если ролик длиннее,
    идём через legacy video.save сразу, без попытки shortVideo (она отказывается
    с 'video is too long' и в итоге даёт фолбэк-метку «дуэт с DELETED»).
    """
    cfg = json.loads(_token_path(brand).read_text())
    token = cfg["access_token"]
    target_owner = cfg.get("target_owner_id", 0)

    duration = _probe_duration(video_path)
    if duration > 60.5:  # 0.5с допуска на округление
        return _upload_video_legacy(
            token=token, target_owner=target_owner,
            video_path=video_path, title=title, description=description,
            error_msg=f"длительность {duration:.1f}с > 60с (Klips не примет)",
        )

    # ── шаг 1: shortVideo.create → upload_url (нативный Klips-эндпоинт) ──
    # У Клипов лимит названия 60 символов (vs 128 у video.save).
    create_params = {
        "access_token": token, "v": API_VERSION,
        "name": (title or "")[:60],
        "description": (description or "")[:5000],
        "wallpost": 0,
        "publish": 1,  # сразу публиковать (без черновика)
    }
    if target_owner < 0:  # публикация в группу/паблик — group_id положительный
        create_params["group_id"] = abs(target_owner)

    r = requests.post(
        "https://api.vk.com/method/shortVideo.create",
        params=create_params, timeout=30,
    ).json()
    if "error" in r:
        # фолбэк на video.save — если в группе отключены клипы или scope не позволяет
        return _upload_video_legacy(
            token=token, target_owner=target_owner,
            video_path=video_path, title=title, description=description,
            error_msg=r["error"].get("error_msg", "?"),
        )

    saved = r["response"]
    upload_url = saved["upload_url"]

    # ── шаг 2: multipart upload файла. Поле может быть "file" или "video_file" ──
    with open(video_path, "rb") as f:
        upload = requests.post(
            upload_url, files={"file": (video_path.name, f, "video/mp4")},
            timeout=600,
        )
    upload.raise_for_status()
    try:
        up_resp = upload.json()
    except ValueError:
        up_resp = {}
    if isinstance(up_resp.get("response"), dict):
        up_resp = up_resp["response"]

    video_id = up_resp.get("video_id") or saved.get("video_id")
    owner_id = up_resp.get("owner_id") or saved.get("owner_id") or target_owner
    if owner_id is None:
        raise RuntimeError("VK shortVideo: upload вернул пустой owner_id")

    return {
        "video_id": f"{owner_id}_{video_id}",
        # Klips-URL: vk.com/clip{owner}_{id} (а не /video для Klips видна вкладка «Клипы»)
        "url": f"https://vk.com/clip{owner_id}_{video_id}",
        "owner_id": owner_id,
        "kind": "clip",
    }


def _upload_video_legacy(
    *,
    token: str, target_owner: int, video_path: Path,
    title: str, description: str, error_msg: str,
) -> dict:
    """Резервный путь через video.save — если shortVideo.create отказал."""
    save_params = {
        "access_token": token, "v": API_VERSION,
        "name": (title or "")[:128],
        "description": (description or "")[:5000],
        "no_comments": 0,
        "wallpost": 0,
    }
    if target_owner < 0:
        save_params["group_id"] = abs(target_owner)

    r = requests.post(
        "https://api.vk.com/method/video.save",
        params=save_params, timeout=30,
    ).json()
    if "error" in r:
        raise RuntimeError(
            f"VK shortVideo.create отказал ({error_msg}); "
            f"video.save тоже: {r['error'].get('error_msg', '?')}"
        )
    saved = r["response"]
    with open(video_path, "rb") as f:
        upload = requests.post(
            saved["upload_url"],
            files={"video_file": (video_path.name, f, "video/mp4")},
            timeout=600,
        )
    upload.raise_for_status()
    owner_id, video_id = saved["owner_id"], saved["video_id"]
    return {
        "video_id": f"{owner_id}_{video_id}",
        "url": f"https://vk.com/video{owner_id}_{video_id}",
        "owner_id": owner_id,
        "kind": "video_legacy",
    }


def fetch_stats(brand: str, video_id: str) -> dict:
    """video_id формата 'owner_video' (например '-12345_67890')."""
    cfg = json.loads(_token_path(brand).read_text())
    token = cfg["access_token"]
    r = requests.get(
        "https://api.vk.com/method/video.get",
        params={"videos": video_id, "access_token": token, "v": API_VERSION},
        timeout=15,
    ).json()
    if "error" in r:
        raise RuntimeError(r["error"].get("error_msg", "?"))
    items = r.get("response", {}).get("items", [])
    if not items:
        return {}
    v = items[0]
    return {
        "views": int(v.get("views", 0)),
        "likes": int((v.get("likes") or {}).get("count", 0) or 0),
        "comments": int((v.get("comments") or {}).get("count", 0) or 0),
    }

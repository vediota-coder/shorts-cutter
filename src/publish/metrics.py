"""Агрегатор метрик из YouTube / VK / Instagram.

Для каждого опубликованного клипа подтягивает свежую статистику и сохраняет
в jobs/<id>/metrics.json чтобы не упираться в rate limits API.
"""
from __future__ import annotations


from . import youtube as yt_mod
from . import vk as vk_mod
from . import instagram as ig_mod


def fetch_clip_metrics(clip: dict, brand: str) -> dict:
    """Возвращает метрики по платформам для клипа: {youtube: {...}, vk: {...}, instagram: {...}}."""
    out: dict[str, dict] = {}
    pubs = clip.get("publications", {}) or {}

    if "youtube" in pubs and pubs["youtube"].get("video_id"):
        try:
            out["youtube"] = yt_mod.fetch_stats(brand, pubs["youtube"]["video_id"])
        except Exception as e:
            out["youtube"] = {"error": str(e)}

    if "vk" in pubs and pubs["vk"].get("video_id"):
        try:
            out["vk"] = vk_mod.fetch_stats(brand, pubs["vk"]["video_id"])
        except Exception as e:
            out["vk"] = {"error": str(e)}

    if "instagram" in pubs and pubs["instagram"].get("media_id"):
        try:
            out["instagram"] = ig_mod.fetch_stats(brand, pubs["instagram"]["media_id"])
        except Exception as e:
            out["instagram"] = {"error": str(e)}

    return out


def aggregate_totals(per_clip: dict[int, dict]) -> dict:
    """Суммирует views/likes/comments по всем клипам и платформам."""
    sums = {"views": 0, "likes": 0, "comments": 0}
    by_platform: dict[str, dict[str, int]] = {}
    for clip_idx, platforms in per_clip.items():
        for plat, m in platforms.items():
            if "error" in m:
                continue
            slot = by_platform.setdefault(plat, {"views": 0, "likes": 0, "comments": 0})
            for k in ("views", "likes", "comments"):
                v = int(m.get(k, 0) or 0)
                slot[k] += v
                sums[k] += v
    return {"totals": sums, "by_platform": by_platform}

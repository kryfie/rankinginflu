from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import Candidate


PL_TEXT_MARKERS = (
    "polska",
    "polski",
    "polskie",
    "poland",
    "polish",
    "warszawa",
    "warsaw",
    "kraków",
    "krakow",
    "wrocław",
    "wroclaw",
    "poznań",
    "poznan",
    "gdańsk",
    "gdansk",
    "szczecin",
    "łódź",
    "lodz",
)

PL_HASHTAG_MARKERS = {
    "polska",
    "polski",
    "polish",
    "poland",
    "polskatiktok",
    "tiktokpolska",
    "polandtiktok",
    "polishtiktok",
    "polishtiktoker",
}

PL_FLAG = "🇵🇱"


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _normalize_username(value: Any) -> str:
    return str(value or "").strip().lstrip("@").lower()


def _first_pl_subtitle(post: dict[str, Any]) -> bool:
    subtitles = post.get("subtitleInformation")
    if not isinstance(subtitles, list):
        return False

    for subtitle in subtitles:
        if not isinstance(subtitle, dict):
            continue
        code = str(subtitle.get("language_code") or "").lower()
        lang = str(subtitle.get("lang") or "").lower()
        if code == "pl" or lang.startswith("pol-") or lang == "pl":
            return True
    return False


def _polish_signals(post: dict[str, Any]) -> list[str]:
    signals: list[str] = []

    title = str(post.get("title") or "")
    title_lower = title.lower()
    if PL_FLAG in title or any(marker in title_lower for marker in PL_TEXT_MARKERS):
        signals.append("title")

    hashtags = {
        str(tag).strip().lower()
        for tag in (post.get("hashtags") or [])
        if tag is not None
    }
    if hashtags & PL_HASHTAG_MARKERS:
        signals.append("hashtag")

    if _first_pl_subtitle(post):
        signals.append("subtitle_pl")

    poi = post.get("poi")
    if isinstance(poi, dict):
        poi_text = " ".join(
            str(poi.get(k) or "")
            for k in ("poiName", "address", "cityName")
        ).lower()
        if "poland" in poi_text or "polska" in poi_text:
            signals.append("poi_pl")

    channel = post.get("channel")
    if isinstance(channel, dict):
        channel_text = " ".join(
            str(channel.get(k) or "")
            for k in ("name", "username")
        ).lower()
        if PL_FLAG in channel_text or any(marker in channel_text for marker in PL_TEXT_MARKERS):
            signals.append("channel")

    return sorted(set(signals))


def deduplicate_candidates(
    posts: Iterable[dict[str, Any]],
    *,
    min_followers: int,
) -> tuple[list[Candidate], dict[str, int]]:
    buckets: dict[str, dict[str, Any]] = {}
    stats = defaultdict(int)

    for post in posts:
        stats["posts_in"] += 1
        channel = post.get("channel")
        if not isinstance(channel, dict):
            stats["missing_channel"] += 1
            continue

        username = _normalize_username(channel.get("username"))
        tiktok_id = str(channel.get("id") or "").strip()

        # Stable TikTok user id is preferred. Username is fallback.
        dedupe_key = tiktok_id or username
        if not dedupe_key or not username:
            stats["missing_identity"] += 1
            continue

        followers = _safe_int(channel.get("followers"))
        source = str(post.get("keyword") or post.get("inputSource") or "").strip()
        signals = _polish_signals(post)

        if dedupe_key not in buckets:
            buckets[dedupe_key] = {
                "tiktok_id": tiktok_id,
                "username": username,
                "display_name": str(channel.get("name") or username).strip(),
                "profile_url": str(channel.get("url") or f"https://www.tiktok.com/@{username}"),
                "avatar_url": channel.get("avatar"),
                "followers": followers,
                # Important: this provider field is preserved only for diagnostics.
                # It MUST NOT be treated as authoritative verification.
                "provider_verified": channel.get("verified")
                    if isinstance(channel.get("verified"), bool)
                    else None,
                "found_by": set(),
                "posts_seen": 0,
                "max_views_seen": 0,
                "max_likes_seen": 0,
                "latest_post_at": None,
                "polish_signals": set(),
            }

        row = buckets[dedupe_key]
        row["followers"] = max(row["followers"], followers)
        row["posts_seen"] += 1
        row["max_views_seen"] = max(row["max_views_seen"], _safe_int(post.get("views")))
        row["max_likes_seen"] = max(row["max_likes_seen"], _safe_int(post.get("likes")))
        if source:
            row["found_by"].add(source)
        row["polish_signals"].update(signals)

        post_at = post.get("uploadedAtFormatted")
        if isinstance(post_at, str) and post_at:
            if row["latest_post_at"] is None or post_at > row["latest_post_at"]:
                row["latest_post_at"] = post_at

    stats["unique_creators"] = len(buckets)

    candidates: list[Candidate] = []
    for row in buckets.values():
        if row["followers"] < min_followers:
            stats["below_min_followers"] += 1
            continue

        candidate = Candidate(
            tiktok_id=row["tiktok_id"],
            username=row["username"],
            display_name=row["display_name"],
            profile_url=row["profile_url"],
            avatar_url=row["avatar_url"],
            followers=row["followers"],
            provider_verified=row["provider_verified"],
            found_by=sorted(row["found_by"]),
            posts_seen=row["posts_seen"],
            max_views_seen=row["max_views_seen"],
            max_likes_seen=row["max_likes_seen"],
            latest_post_at=row["latest_post_at"],
            polish_signal_count=len(row["polish_signals"]),
            polish_signals=sorted(row["polish_signals"]),
        )
        candidates.append(candidate)

    # Discovery ranking only. This is NOT the final Influence Score.
    candidates.sort(
        key=lambda c: (
            c.polish_signal_count,
            c.followers,
            c.max_views_seen,
        ),
        reverse=True,
    )

    stats["accepted_candidates"] = len(candidates)
    return candidates, dict(stats)


def build_scanner_queue(candidates: list[Candidate]) -> list[dict[str, Any]]:
    """
    Creates a provider-agnostic queue for the existing profile scanner.

    We intentionally do not trust provider_verified. The profile scanner should
    establish authoritative profile fields (including verified status).
    """
    return [
        {
            "username": candidate.username,
            "tiktok_id": candidate.tiktok_id,
            "priority": index + 1,
            "discovery_followers": candidate.followers,
            "polish_signals": candidate.polish_signals,
            "status": "pending_profile_scan",
        }
        for index, candidate in enumerate(candidates)
    ]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

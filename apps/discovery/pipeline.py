from __future__ import annotations

import json
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


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _normalize_username(value: Any) -> str:
    return str(value or "").strip().lstrip("@").lower()


def _pl_subtitle_languages(post: dict[str, Any]) -> list[str]:
    out: list[str] = []
    subtitles = post.get("subtitleInformation")
    if not isinstance(subtitles, list):
        return out

    for subtitle in subtitles:
        if not isinstance(subtitle, dict):
            continue
        code = str(subtitle.get("language_code") or "").strip().lower()
        lang = str(subtitle.get("lang") or "").strip()
        value = code or lang
        if value and value not in out:
            out.append(value)
    return out


def _has_pl_subtitle(post: dict[str, Any]) -> bool:
    for value in _pl_subtitle_languages(post):
        low = value.lower()
        if low == "pl" or low.startswith("pol-"):
            return True
    return False


def polish_signals(post: dict[str, Any]) -> list[str]:
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
    # handle variants such as polskitiktok🇵🇱
    if any(
        tag in PL_HASHTAG_MARKERS
        or any(marker in tag for marker in PL_HASHTAG_MARKERS)
        for tag in hashtags
    ):
        signals.append("hashtag")

    if _has_pl_subtitle(post):
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
    min_pl_signals: int,
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
        dedupe_key = tiktok_id or username

        if not dedupe_key or not username:
            stats["missing_identity"] += 1
            continue

        followers = _safe_int(channel.get("followers"))
        source = str(
            post.get("_discovery_seed")
            or post.get("keyword")
            or post.get("inputSource")
            or ""
        ).strip()
        signals = polish_signals(post)

        if dedupe_key not in buckets:
            buckets[dedupe_key] = {
                "tiktok_id": tiktok_id,
                "username": username,
                "display_name": str(channel.get("name") or username).strip(),
                "profile_url": str(
                    channel.get("url")
                    or f"https://www.tiktok.com/@{username}"
                ),
                "avatar_url": channel.get("avatar"),
                "followers": followers,
                # Diagnostics only. Never authoritative for the InfluRank badge.
                "provider_verified": (
                    channel.get("verified")
                    if isinstance(channel.get("verified"), bool)
                    else None
                ),
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
        row["max_views_seen"] = max(
            row["max_views_seen"], _safe_int(post.get("views"))
        )
        row["max_likes_seen"] = max(
            row["max_likes_seen"], _safe_int(post.get("likes"))
        )
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

        if len(row["polish_signals"]) < min_pl_signals:
            stats["below_min_pl_signals"] += 1
            continue

        candidates.append(
            Candidate(
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
        )

    candidates.sort(
        key=lambda c: (
            c.polish_signal_count,
            c.followers,
            c.max_views_seen,
        ),
        reverse=True,
    )

    stats["accepted_candidates_latest_run"] = len(candidates)
    return candidates, dict(stats)


def compact_post(post: dict[str, Any]) -> dict[str, Any]:
    """
    Keep only fields useful to InfluRank discovery.

    Direct video URLs, covers and music payloads are intentionally omitted
    because they are large/ephemeral and do not belong in the Git repository.
    """
    channel = post.get("channel")
    if not isinstance(channel, dict):
        channel = {}

    poi = post.get("poi")
    compact_poi = None
    if isinstance(poi, dict):
        compact_poi = {
            "poiName": poi.get("poiName"),
            "address": poi.get("address"),
            "cityName": poi.get("cityName"),
            "regionCode": poi.get("regionCode"),
        }

    return {
        "seed": str(
            post.get("_discovery_seed")
            or post.get("keyword")
            or post.get("inputSource")
            or ""
        ),
        "id": str(post.get("id") or ""),
        "title": post.get("title"),
        "views": _safe_int(post.get("views")),
        "likes": _safe_int(post.get("likes")),
        "comments": _safe_int(post.get("comments")),
        "shares": _safe_int(post.get("shares")),
        "bookmarks": _safe_int(post.get("bookmarks")),
        "hashtags": [
            tag for tag in (post.get("hashtags") or []) if tag is not None
        ],
        "uploadedAtFormatted": post.get("uploadedAtFormatted"),
        "channel": {
            "id": str(channel.get("id") or ""),
            "name": channel.get("name"),
            "username": channel.get("username"),
            "profile_url": channel.get("url"),
            "followers": _safe_int(channel.get("followers")),
            "following": _safe_int(channel.get("following")),
            "provider_verified": (
                channel.get("verified")
                if isinstance(channel.get("verified"), bool)
                else None
            ),
        },
        "subtitle_languages": _pl_subtitle_languages(post),
        "poi": compact_poi,
        "polish_signals": polish_signals(post),
    }


def _identity_key(row: dict[str, Any]) -> str:
    tiktok_id = str(row.get("tiktok_id") or "").strip()
    username = _normalize_username(row.get("username"))
    return tiktok_id or username


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def merge_candidate_registry(
    existing_payload: dict[str, Any],
    latest_candidates: list[Candidate],
    *,
    run_at: str,
    latest_run_meta: dict[str, Any],
) -> dict[str, Any]:
    """
    Upsert discovery candidates instead of replacing the universe every run.

    This is important because InfluRank is building a cumulative creator map.
    """
    existing_rows = existing_payload.get("creators", [])
    if not isinstance(existing_rows, list):
        existing_rows = []

    registry: dict[str, dict[str, Any]] = {}
    for row in existing_rows:
        if not isinstance(row, dict):
            continue
        key = _identity_key(row)
        if key:
            registry[key] = dict(row)

    for candidate in latest_candidates:
        incoming = candidate.to_dict()
        key = candidate.tiktok_id or candidate.username
        old = registry.get(key, {})

        old_found = set(old.get("found_by") or [])
        new_found = set(incoming.get("found_by") or [])
        old_signals = set(old.get("polish_signals") or [])
        new_signals = set(incoming.get("polish_signals") or [])

        first_seen = old.get("first_discovered_at") or run_at
        old_total_posts = _safe_int(
            old.get("posts_seen_total", old.get("posts_seen", 0))
        )

        merged = {
            **old,
            **incoming,
            "first_discovered_at": first_seen,
            "last_discovered_at": run_at,
            "discovery_runs_seen": _safe_int(old.get("discovery_runs_seen")) + 1,
            "found_by": sorted(old_found | new_found),
            "polish_signals": sorted(old_signals | new_signals),
            "polish_signal_count": len(old_signals | new_signals),
            "posts_seen_latest_run": incoming.get("posts_seen", 0),
            "posts_seen_total": old_total_posts + incoming.get("posts_seen", 0),
            "followers_max_seen": max(
                _safe_int(old.get("followers_max_seen", old.get("followers", 0))),
                _safe_int(incoming.get("followers")),
            ),
            "max_views_seen": max(
                _safe_int(old.get("max_views_seen")),
                _safe_int(incoming.get("max_views_seen")),
            ),
            "max_likes_seen": max(
                _safe_int(old.get("max_likes_seen")),
                _safe_int(incoming.get("max_likes_seen")),
            ),
        }
        registry[key] = merged

    rows = sorted(
        registry.values(),
        key=lambda row: (
            _safe_int(row.get("polish_signal_count")),
            _safe_int(row.get("followers")),
            _safe_int(row.get("max_views_seen")),
        ),
        reverse=True,
    )

    return {
        "meta": {
            "latest_run": latest_run_meta,
            "registry_count": len(rows),
            "updated_at": run_at,
        },
        "creators": rows,
    }


def build_scanner_queue(
    registry_payload: dict[str, Any],
    existing_queue_payload: dict[str, Any],
    *,
    updated_at: str,
) -> dict[str, Any]:
    existing_items = existing_queue_payload.get("items", [])
    if not isinstance(existing_items, list):
        existing_items = []

    prior: dict[str, dict[str, Any]] = {}
    for row in existing_items:
        if not isinstance(row, dict):
            continue
        key = _identity_key(row)
        if key:
            prior[key] = row

    creators = registry_payload.get("creators", [])
    if not isinstance(creators, list):
        creators = []

    items = []
    for priority, creator in enumerate(creators, start=1):
        key = _identity_key(creator)
        old = prior.get(key, {})

        items.append(
            {
                "username": creator.get("username"),
                "tiktok_id": creator.get("tiktok_id"),
                "priority": priority,
                "discovery_followers": _safe_int(creator.get("followers")),
                "polish_signals": creator.get("polish_signals") or [],
                "found_by": creator.get("found_by") or [],
                "last_discovered_at": creator.get("last_discovered_at"),
                # Preserve downstream state on subsequent discovery runs.
                "status": old.get("status") or "pending_profile_scan",
                **(
                    {"last_profile_scan_at": old.get("last_profile_scan_at")}
                    if old.get("last_profile_scan_at")
                    else {}
                ),
            }
        )

    return {
        "meta": {
            "purpose": "Queue for authoritative profile enrichment",
            "count": len(items),
            "updated_at": updated_at,
        },
        "items": items,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

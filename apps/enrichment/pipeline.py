from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .classification import classify_all_creators
from .ranking import build_excluded_creators, build_web_ranking
from .store import (
    load_json,
    normalize_username,
    safe_float,
    safe_int,
    write_json,
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso(run_at: str) -> str:
    try:
        return datetime.fromisoformat(run_at.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return run_at[:10]


def _row_username(row: dict[str, Any]) -> str:
    author = row.get("author")
    if isinstance(author, dict):
        username = normalize_username(author.get("username"))
        if username:
            return username
    return normalize_username(row.get("ownerUsername"))


def _profile_from_rows(
    username: str,
    rows: list[dict[str, Any]],
    *,
    run_at: str,
    queue_item: dict[str, Any] | None,
    previous: dict[str, Any] | None,
    source: str,
) -> dict[str, Any] | None:
    author = None
    for row in rows:
        candidate = row.get("author")
        if isinstance(candidate, dict) and normalize_username(candidate.get("username")) == username:
            author = candidate
            break

    if not isinstance(author, dict):
        return None

    bio = str(author.get("biography") or "")

    discovery_signals = []
    discovery_strong_signals = []
    discovery_pl_confidence = None
    if isinstance(queue_item, dict):
        discovery_signals = list(queue_item.get("polish_signals") or [])
        discovery_strong_signals = list(
            queue_item.get("polish_strong_signals") or []
        )
        discovery_pl_confidence = queue_item.get("discovery_pl_confidence")

    previous = previous or {}

    return {
        "tiktok_id": str(author.get("userId") or rows[0].get("ownerId") or ""),
        "username": username,
        "display_name": str(
            author.get("nickname")
            or rows[0].get("ownerNickname")
            or username
        ),
        "profile_url": str(
            author.get("profileUrl")
            or rows[0].get("profileUrl")
            or f"https://www.tiktok.com/@{username}"
        ),
        "bio": bio,
        "verified": bool(author.get("isVerified")),
        "private": bool(author.get("isPrivate")),
        "followers": safe_int(author.get("followerCount")),
        "followers_are_exact": bool(author.get("followersAreExact")),
        "following": safe_int(author.get("followingCount")),
        "total_likes": safe_int(author.get("heartCount")),
        "video_count": safe_int(author.get("postCount")),
        "friend_count": safe_int(author.get("friendCount")),
        "avatar_url": author.get("avatarUrl") or author.get("avatarThumbnailUrl") or "",
        "bio_link": author.get("bioLink"),
        "sec_uid": author.get("secUid"),
        "account_created_at": author.get("accountCreatedAt"),
        "is_organization": bool(author.get("isOrganization")),
        "is_commerce_user": bool(author.get("isCommerceUser")),
        "is_seller": bool(author.get("isSeller")),
        "language": author.get("language"),
        "recent_activity_provider": author.get("recentActivity"),
        "discovery_pl_confidence": discovery_pl_confidence,
        "discovery_signals": sorted(set(discovery_signals)),
        "discovery_strong_signals": sorted(set(discovery_strong_signals)),
        "category_manual": previous.get("category_manual"),
        "account_type_manual": previous.get("account_type_manual"),
        "first_enriched_at": previous.get("first_enriched_at") or run_at,
        "last_enriched_at": run_at,
        "source": source,
    }


def _normalized_post(row: dict[str, Any], username: str) -> dict[str, Any] | None:
    post_id = str(row.get("id") or "").strip()
    if not post_id:
        return None

    views = safe_int(row.get("playCount"))
    likes = safe_int(row.get("likeCount"))
    comments = safe_int(row.get("commentCount"))
    shares = safe_int(row.get("shareCount"))

    # Calculate ourselves; do not depend on provider engagementRatePercent.
    engagement = (
        100.0 * (likes + comments + shares) / views
        if views > 0
        else 0.0
    )

    return {
        "id": post_id,
        "username": username,
        "url": row.get("url"),
        "type": row.get("type"),
        "caption": row.get("caption") or "",
        "hashtags": list(row.get("hashtags") or []),
        "mentions": list(row.get("mentions") or []),
        "timestamp": row.get("timestamp"),
        "timestamp_unix": row.get("timestampUnix"),
        "views": views,
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "engagement_rate_percent": round(engagement, 4),
        "is_pinned": bool(row.get("isPinned")),
        "is_ad": bool(row.get("isAd")),
        "is_branded_content": bool(row.get("isBrandedContent")),
        "created_in_region": row.get("createdInRegion"),
        "scraped_at": row.get("scrapedAt"),
    }


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def select_queue_items(
    queue_payload: dict[str, Any],
    *,
    max_profiles: int,
    refresh_all: bool,
    min_refresh_age_hours: float = 0,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Select enrichment work without re-scraping fresh profiles.

    Normal runs select new/pending creators and retry enrichment errors.
    Refresh runs without an age threshold preserve the historical
    ``--refresh-all`` behaviour.

    When ``min_refresh_age_hours`` is positive, the call is treated as the
    scheduled "refresh existing" phase: only already-enriched profiles whose
    last successful profile scan is old enough are selected. Pending/error
    items are intentionally left for the normal enrichment phase.
    """
    items = queue_payload.get("items", [])
    if not isinstance(items, list):
        return []

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)

    min_age = max(0.0, float(min_refresh_age_hours or 0))
    eligible = []

    for item in items:
        if not isinstance(item, dict):
            continue

        username = normalize_username(item.get("username"))
        if not username:
            continue

        status = str(item.get("status") or "pending_profile_scan")

        if refresh_all:
            if min_age > 0:
                # The 7-day refresh phase is for existing, successfully
                # enriched profiles only. New/error accounts are handled by
                # the preceding normal enrichment phase.
                if status != "enriched":
                    continue

                scanned_at = _parse_iso_datetime(
                    item.get("last_profile_scan_at")
                    or item.get("last_enriched_at")
                )

                # Missing timestamp on an enriched row means we cannot prove
                # that it is fresh, so allow a one-time refresh.
                if scanned_at is not None:
                    age_hours = (current_time - scanned_at).total_seconds() / 3600.0
                    if age_hours < min_age:
                        continue

                eligible.append(item)
            else:
                eligible.append(item)
        elif status in {
            "pending_profile_scan",
            "enrichment_error",
        }:
            eligible.append(item)

    eligible.sort(key=lambda row: safe_int(row.get("priority")) or 10**9)
    if max_profiles > 0:
        eligible = eligible[:max_profiles]
    return eligible


def enrich_state(
    *,
    settings,
    actor_rows: list[dict[str, Any]],
    selected_items: list[dict[str, Any]],
    run_at: str,
) -> dict[str, Any]:
    queue_payload = load_json(settings.queue_path, {"meta": {}, "items": []})
    creators_payload = load_json(settings.creators_path, {"meta": {}, "creators": []})
    posts_payload = load_json(settings.posts_path, {"meta": {}, "posts": []})
    snapshots_payload = load_json(settings.snapshots_path, {"meta": {}, "snapshots": []})

    queue_items = queue_payload.get("items", [])
    creators = creators_payload.get("creators", [])
    posts = posts_payload.get("posts", [])
    snapshots = snapshots_payload.get("snapshots", [])

    if not isinstance(queue_items, list):
        queue_items = []
    if not isinstance(creators, list):
        creators = []
    if not isinstance(posts, list):
        posts = []
    if not isinstance(snapshots, list):
        snapshots = []

    selected_by_username = {
        normalize_username(item.get("username")): item
        for item in selected_items
    }

    rows_by_username: dict[str, list[dict[str, Any]]] = {}
    actor_errors: dict[str, str] = {}
    for row in actor_rows:
        if row.get("error"):
            # Some Actor error rows include the input handle/url. Preserve a generic message.
            possible = normalize_username(
                row.get("ownerUsername")
                or row.get("handle")
                or row.get("username")
            )
            if possible:
                actor_errors[possible] = str(
                    row.get("errorDescription")
                    or row.get("error")
                )
            continue

        username = _row_username(row)
        if username:
            rows_by_username.setdefault(username, []).append(row)

    creators_by_username = {
        normalize_username(row.get("username")): dict(row)
        for row in creators
        if isinstance(row, dict) and normalize_username(row.get("username"))
    }
    posts_by_id = {
        str(row.get("id")): dict(row)
        for row in posts
        if isinstance(row, dict) and row.get("id")
    }

    successful: set[str] = set()
    failures: dict[str, str] = {}

    for requested_username, item in selected_by_username.items():
        rows = rows_by_username.get(requested_username, [])

        # Handle renamed accounts when inputUrl/author lets us connect the result.
        if not rows:
            for returned_username, returned_rows in rows_by_username.items():
                if any(
                    requested_username in str(r.get("inputUrl") or "").lower()
                    for r in returned_rows
                ):
                    rows = returned_rows
                    requested_username = returned_username
                    break

        if not rows:
            failures[requested_username] = actor_errors.get(
                requested_username,
                "No public profile/post rows returned.",
            )
            continue

        previous = creators_by_username.get(requested_username)
        profile = _profile_from_rows(
            requested_username,
            rows,
            run_at=run_at,
            queue_item=item,
            previous=previous,
            source=settings.actor_id.replace("~", "/"),
        )
        if not profile:
            failures[requested_username] = "Profile author block missing."
            continue

        creators_by_username[requested_username] = profile

        for row in rows:
            post = _normalized_post(row, requested_username)
            if post:
                old = posts_by_id.get(post["id"], {})
                posts_by_id[post["id"]] = {**old, **post}

        successful.add(requested_username)

        today = _today_iso(run_at)
        snapshot_key = (requested_username, today)
        snapshots = [
            snap
            for snap in snapshots
            if not (
                normalize_username(snap.get("username")) == snapshot_key[0]
                and str(snap.get("date") or "") == snapshot_key[1]
            )
        ]
        snapshots.append(
            {
                "date": today,
                "username": requested_username,
                "collected_at": run_at,
                "followers": profile["followers"],
                "following": profile["following"],
                "total_likes": profile["total_likes"],
                "video_count": profile["video_count"],
            }
        )

    # Update queue state while preserving discovery fields.
    updated_queue = []
    for item in queue_items:
        row = dict(item)
        username = normalize_username(row.get("username"))
        if username in successful:
            row["status"] = "enriched"
            row["last_profile_scan_at"] = run_at
            row["enrichment_source"] = settings.actor_id.replace("~", "/")
            row.pop("enrichment_error", None)
        elif username in failures:
            row["status"] = "enrichment_error"
            row["last_profile_scan_at"] = run_at
            row["enrichment_error"] = failures[username]
        updated_queue.append(row)

    creators_out_unclassified = sorted(
        creators_by_username.values(),
        key=lambda row: safe_int(row.get("followers")),
        reverse=True,
    )
    posts_out = sorted(
        posts_by_id.values(),
        key=lambda row: str(row.get("timestamp") or ""),
        reverse=True,
    )
    snapshots_out = sorted(
        snapshots,
        key=lambda row: (
            str(row.get("collected_at") or ""),
            normalize_username(row.get("username")),
        ),
    )

    creators_out = classify_all_creators(
        creators_out_unclassified,
        posts_out,
        updated_queue,
    )

    ranking = build_web_ranking(creators_out, posts_out, snapshots_out)
    excluded = build_excluded_creators(creators_out)

    write_json(
        settings.creators_path,
        {
            "meta": {
                "updated_at": run_at,
                "count": len(creators_out),
                "source": settings.actor_id.replace("~", "/"),
            },
            "creators": creators_out,
        },
    )
    write_json(
        settings.posts_path,
        {
            "meta": {
                "updated_at": run_at,
                "count": len(posts_out),
            },
            "posts": posts_out,
        },
    )
    write_json(
        settings.snapshots_path,
        {
            "meta": {
                "updated_at": run_at,
                "count": len(snapshots_out),
            },
            "snapshots": snapshots_out,
        },
    )
    write_json(
        settings.queue_path,
        {
            "meta": {
                **(queue_payload.get("meta") or {}),
                "updated_at": run_at,
                "count": len(updated_queue),
            },
            "items": updated_queue,
        },
    )
    write_json(
        settings.web_ranking_path,
        {
            "generated_at": run_at,
            "source": "influRank-enrichment-v6",
            "score_note": (
                "Influence Score is provisional until 30-day follower history exists. "
                "Momentum is omitted and remaining weights are re-normalized. "
                "Only ranking-eligible person/creator_brand accounts are scored."
            ),
            "creators": ranking,
            "excluded_creators": excluded,
        },
    )

    return {
        "selected": len(selected_items),
        "successful": len(successful),
        "failed": len(failures),
        "creators_total": len(creators_out),
        "posts_total": len(posts_out),
        "snapshots_total": len(snapshots_out),
        "ranking_count": len(ranking),
        "excluded_count": len(excluded),
        "failures": failures,
    }

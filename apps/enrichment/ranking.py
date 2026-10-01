from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import log10
from statistics import mean, median, pstdev
from typing import Any

from .store import normalize_username, safe_float, safe_int


WEIGHTS = {
    "reach": 0.30,
    "engagement": 0.25,
    "audience": 0.20,
    "momentum": 0.15,
    "consistency": 0.10,
}


def _percentile(values: list[float], value: float) -> float:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return 50.0
    if len(vals) == 1:
        return 50.0
    below = sum(1 for v in vals if v < value)
    equal = sum(1 for v in vals if v == value)
    return 100.0 * (below + 0.5 * equal) / len(vals)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _latest_snapshot_before(
    snapshots: list[dict[str, Any]],
    username: str,
    target: datetime,
) -> dict[str, Any] | None:
    username = normalize_username(username)
    eligible = []
    for row in snapshots:
        if normalize_username(row.get("username")) != username:
            continue
        dt = _parse_dt(row.get("collected_at"))
        if dt and dt <= target:
            eligible.append((dt, row))
    return max(eligible, key=lambda x: x[0])[1] if eligible else None


def build_web_ranking(
    creators: list[dict[str, Any]],
    posts: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Build a provisional ranking from InfluRank-owned normalized raw data.

    The provider's precomputed engagement/median fields are deliberately ignored.
    We calculate medians ourselves from raw posts.
    """
    posts_by_user: dict[str, list[dict[str, Any]]] = {}
    for post in posts:
        username = normalize_username(post.get("username"))
        if username:
            posts_by_user.setdefault(username, []).append(post)

    raw: list[dict[str, Any]] = []

    for creator in creators:
        username = normalize_username(creator.get("username"))
        if not username:
            continue

        creator_posts = sorted(
            posts_by_user.get(username, []),
            key=lambda p: str(p.get("timestamp") or ""),
            reverse=True,
        )

        # Pinned posts can be much older and distort "recent" performance.
        metric_posts = [p for p in creator_posts if not bool(p.get("is_pinned"))][:13]
        if not metric_posts:
            metric_posts = creator_posts[:13]

        views = [safe_int(p.get("views")) for p in metric_posts if safe_int(p.get("views")) > 0]
        engagements = []
        for p in metric_posts:
            v = safe_int(p.get("views"))
            if v <= 0:
                continue
            total = (
                safe_int(p.get("likes"))
                + safe_int(p.get("comments"))
                + safe_int(p.get("shares"))
            )
            engagements.append(100.0 * total / v)

        followers = safe_int(creator.get("followers"))
        median_views = float(median(views)) if views else 0.0
        median_engagement = float(median(engagements)) if engagements else 0.0
        reach_ratio = median_views / max(1, followers)

        if len(views) >= 3 and mean(views) > 0:
            cv = pstdev(views) / mean(views)
            consistency = max(0.0, min(100.0, 100.0 * (1.0 - min(cv, 1.0))))
        else:
            consistency = 50.0

        current_dt = _parse_dt(creator.get("last_enriched_at")) or datetime.now(timezone.utc)
        older = _latest_snapshot_before(
            snapshots,
            username,
            current_dt - timedelta(days=30),
        )
        growth = None
        if older and safe_int(older.get("followers")) > 0:
            old_followers = safe_int(older.get("followers"))
            growth = 100.0 * (followers - old_followers) / old_followers

        raw.append(
            {
                "handle": username,
                "name": creator.get("display_name") or username,
                "avatar": creator.get("avatar_url") or "",
                "verified": bool(creator.get("verified")),
                "category": creator.get("category") or "",
                "pl_confidence": creator.get("pl_confidence"),
                "followers": followers,
                "views": median_views,
                "engagement": median_engagement,
                "growth": growth,
                "reach_ratio": reach_ratio,
                "consistency_raw": consistency,
                "posts_measured": len(metric_posts),
                "updated_at": creator.get("last_enriched_at"),
            }
        )

    if not raw:
        return []

    audience_vals = [log10(max(1, x["followers"])) for x in raw]
    reach_vals = [x["reach_ratio"] for x in raw]
    engagement_vals = [x["engagement"] for x in raw]
    growth_vals = [x["growth"] for x in raw if x["growth"] is not None]

    for row in raw:
        components: dict[str, float | None] = {
            "audience": _percentile(
                audience_vals,
                log10(max(1, row["followers"])),
            ),
            "reach": _percentile(reach_vals, row["reach_ratio"]),
            "engagement": _percentile(engagement_vals, row["engagement"]),
            "momentum": (
                _percentile(growth_vals, row["growth"])
                if row["growth"] is not None
                else None
            ),
            "consistency": row["consistency_raw"],
        }

        available_weight = sum(
            WEIGHTS[name]
            for name, value in components.items()
            if value is not None
        )
        weighted = sum(
            WEIGHTS[name] * float(value)
            for name, value in components.items()
            if value is not None
        )
        row["score"] = round(weighted / max(available_weight, 1e-9), 1)
        row["score_status"] = (
            "provisional_no_30d_history"
            if components["momentum"] is None
            else "full"
        )
        row["components"] = {
            name: (round(value, 1) if value is not None else None)
            for name, value in components.items()
        }

        row.pop("reach_ratio", None)
        row.pop("consistency_raw", None)

    raw.sort(key=lambda x: x["score"], reverse=True)
    for index, row in enumerate(raw, start=1):
        row["rank"] = index

    return raw

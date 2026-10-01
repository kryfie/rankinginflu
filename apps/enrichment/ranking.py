from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import log10
from statistics import median
from typing import Any

from .store import normalize_username, safe_int


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


def robust_consistency_index(views: list[int]) -> float:
    """
    Robust 0-100 consistency index for TikTok views.

    TikTok distributions are heavy-tailed: a normal viral post should not make
    consistency collapse to zero. We therefore measure dispersion on log10
    views and use the median absolute deviation (MAD), which is resistant to
    outliers.

    Approximate interpretation:
      - 100: nearly identical reach on measured posts
      - 60-80: reasonably stable with normal viral variation
      - 30-60: volatile
      - <30: very volatile

    This is an absolute diagnostic index. The final score component is its
    percentile inside the current ranking cohort.
    """
    clean = [max(1, safe_int(v)) for v in views if safe_int(v) > 0]
    if len(clean) < 3:
        return 50.0

    logs = [log10(v) for v in clean]
    center = median(logs)
    mad = median(abs(x - center) for x in logs)

    # Rational decay is deliberately forgiving of a few viral outliers.
    score = 100.0 / (1.0 + 2.5 * mad)
    return round(max(0.0, min(100.0, score)), 2)


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
    Build InfluRank from normalized raw data.

    Provider-calculated engagement, medians and scores are ignored.
    InfluRank calculates its own metrics from raw posts.
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
        if creator.get("ranking_eligible") is False:
            continue

        creator_posts = sorted(
            posts_by_user.get(username, []),
            key=lambda p: str(p.get("timestamp") or ""),
            reverse=True,
        )

        # Pinned posts can be old and can badly distort current performance.
        metric_posts = [
            p for p in creator_posts
            if not bool(p.get("is_pinned"))
        ][:13]
        if not metric_posts:
            metric_posts = creator_posts[:13]

        views = [
            safe_int(p.get("views"))
            for p in metric_posts
            if safe_int(p.get("views")) > 0
        ]

        engagements: list[float] = []
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
        consistency_index = robust_consistency_index(views)

        current_dt = (
            _parse_dt(creator.get("last_enriched_at"))
            or datetime.now(timezone.utc)
        )
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
                "category": creator.get("category") or "Other",
                "pl_confidence": creator.get("pl_confidence"),
                "account_type": creator.get("account_type") or "creator_brand",
                "ranking_eligible": True,
                "followers": followers,
                "views": median_views,
                "engagement": median_engagement,
                "growth": growth,
                "reach_ratio": reach_ratio,
                "consistency_index": consistency_index,
                "posts_measured": len(metric_posts),
                "updated_at": creator.get("last_enriched_at"),
            }
        )

    if not raw:
        return []

    audience_vals = [log10(max(1, row["followers"])) for row in raw]
    reach_vals = [row["reach_ratio"] for row in raw]
    engagement_vals = [row["engagement"] for row in raw]
    consistency_vals = [row["consistency_index"] for row in raw]
    growth_vals = [
        row["growth"]
        for row in raw
        if row["growth"] is not None
    ]

    for row in raw:
        components: dict[str, float | None] = {
            "audience": _percentile(
                audience_vals,
                log10(max(1, row["followers"])),
            ),
            "reach": _percentile(
                reach_vals,
                row["reach_ratio"],
            ),
            "engagement": _percentile(
                engagement_vals,
                row["engagement"],
            ),
            "momentum": (
                _percentile(growth_vals, row["growth"])
                if row["growth"] is not None
                else None
            ),
            # Use relative consistency in the final score. Keep the absolute
            # robust index separately for transparency/debugging.
            "consistency": _percentile(
                consistency_vals,
                row["consistency_index"],
            ),
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

        row["score"] = round(
            weighted / max(available_weight, 1e-9),
            1,
        )
        row["score_status"] = (
            "provisional_no_30d_history"
            if components["momentum"] is None
            else "full"
        )
        row["components"] = {
            name: (
                round(value, 1)
                if value is not None
                else None
            )
            for name, value in components.items()
        }

        row.pop("reach_ratio", None)

    raw.sort(key=lambda row: row["score"], reverse=True)

    for index, row in enumerate(raw, start=1):
        row["rank"] = index

    return raw



def build_excluded_creators(
    creators: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out = []

    for creator in creators:
        if creator.get("ranking_eligible") is not False:
            continue

        out.append(
            {
                "handle": normalize_username(creator.get("username")),
                "name": creator.get("display_name")
                or normalize_username(creator.get("username")),
                "followers": safe_int(creator.get("followers")),
                "category": creator.get("category") or "Other",
                "account_type": creator.get("account_type") or "unknown",
                "pl_confidence": creator.get("pl_confidence"),
                "eligibility_reasons": list(
                    creator.get("eligibility_reasons") or []
                ),
                "updated_at": creator.get("last_enriched_at"),
            }
        )

    return sorted(
        out,
        key=lambda row: row["followers"],
        reverse=True,
    )

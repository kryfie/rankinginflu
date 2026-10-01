from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import Candidate


PL_FLAG = "🇵🇱"

# These are deliberately weak. A generic mention of "Polska" can refer to a
# person/name/topic and must not qualify a creator by itself.
PL_WEAK_TEXT_MARKERS = (
    "polska",
    "polski",
    "polskie",
    "polskich",
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

PL_WEAK_HASHTAG_MARKERS = {
    "polska",
    "polski",
    "polish",
    "poland",
    "polskatiktok",
    "tiktokpolska",
    "polishtiktok",
    "polishtiktoker",
}

# Excludes generic country-name tokens such as "polska". We want language
# evidence, not just a keyword match.
POLISH_LANGUAGE_WORDS = {
    "jest", "nie", "tak", "dla", "jak", "mam", "mamy", "moja", "moje", "mój",
    "czy", "się", "sie", "ale", "też", "tez", "tylko", "dzisiaj", "dziś",
    "juz", "już", "będzie", "bedzie", "było", "bylo", "tego", "kiedy",
    "kto", "co", "na", "do", "z", "w", "i", "że", "ze", "to", "od",
    "polskich", "wyborach", "zapraszam", "jutro", "musieliśmy", "dodac", "dodać",
    "powinni", "mieć", "miec", "prawo", "głosować", "glosowac", "właściciel",
}

POLISH_DIACRITICS_RE = re.compile(r"[ąćęłńóśźż]", re.IGNORECASE)
TOKEN_RE = re.compile(r"[a-ząćęłńóśźż]+", re.IGNORECASE)


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


def is_demo_row(post: dict[str, Any]) -> bool:
    return bool(post.get("demo") is True)


def _subtitle_languages(post: dict[str, Any]) -> list[str]:
    # Raw provider payload.
    subtitles = post.get("subtitleInformation")
    out: list[str] = []

    if isinstance(subtitles, list):
        for subtitle in subtitles:
            if not isinstance(subtitle, dict):
                continue
            code = str(subtitle.get("language_code") or "").strip().lower()
            lang = str(subtitle.get("lang") or "").strip().lower()
            value = code or lang
            if value and value not in out:
                out.append(value)

    # Compact v3/v4 repository payload.
    compact = post.get("subtitle_languages")
    if isinstance(compact, list):
        for value in compact:
            low = str(value or "").strip().lower()
            if low and low not in out:
                out.append(low)

    return out


def _has_pl_subtitle(post: dict[str, Any]) -> bool:
    for value in _subtitle_languages(post):
        if value == "pl" or value.startswith("pol-"):
            return True
    return False


def _has_foreign_subtitles_without_pl(post: dict[str, Any]) -> bool:
    languages = _subtitle_languages(post)
    return bool(languages) and not _has_pl_subtitle(post)


def _title(post: dict[str, Any]) -> str:
    return str(post.get("title") or "")


def _hashtags(post: dict[str, Any]) -> set[str]:
    return {
        str(tag).strip().lower()
        for tag in (post.get("hashtags") or [])
        if tag is not None and str(tag).strip()
    }


def _has_polish_language_text(text: str) -> bool:
    """
    Strong content-language evidence.

    Polish-specific diacritics are strong evidence. Without them, require at
    least two common Polish function/content words. Generic "polska/polish"
    does not count here.
    """
    text = str(text or "")
    low = text.lower()

    if POLISH_DIACRITICS_RE.search(low):
        return True

    tokens = TOKEN_RE.findall(low)
    hits = {token for token in tokens if token in POLISH_LANGUAGE_WORDS}
    return len(hits) >= 2


def _poi_evidence(post: dict[str, Any]) -> tuple[bool, bool]:
    poi = post.get("poi")
    if not isinstance(poi, dict):
        return False, False

    poi_text = " ".join(
        str(poi.get(k) or "")
        for k in ("poiName", "address", "cityName")
    ).lower()

    if not poi_text.strip():
        return False, False

    is_pl = "poland" in poi_text or "polska" in poi_text
    return is_pl, not is_pl


def polish_evidence(post: dict[str, Any]) -> dict[str, Any]:
    """
    Return strong/weak Polish evidence and a conservative discovery confidence.

    Strong evidence:
      - TikTok subtitle language = PL
      - POI explicitly in Poland
      - Polish flag
      - Polish-language text

    Weak evidence:
      - #polska / #polish / #polskatiktok etc.
      - word "Polska/Poland/Polish" in title
      - country marker in channel name

    Weak evidence alone never qualifies a creator for enrichment.
    """
    title = _title(post)
    title_lower = title.lower()
    hashtags = _hashtags(post)

    channel = post.get("channel")
    if not isinstance(channel, dict):
        channel = {}
    channel_text = " ".join(
        str(channel.get(k) or "")
        for k in ("name", "username")
    )
    channel_lower = channel_text.lower()

    strong: set[str] = set()
    weak: set[str] = set()
    negative: set[str] = set()

    if _has_pl_subtitle(post):
        strong.add("subtitle_pl")

    poi_pl, poi_foreign = _poi_evidence(post)
    if poi_pl:
        strong.add("poi_pl")
    elif poi_foreign:
        negative.add("poi_foreign")

    flag_text = " ".join([title, channel_text, " ".join(hashtags)])
    if PL_FLAG in flag_text:
        strong.add("flag_pl")

    # Use title as language evidence. Search result title contains caption/text.
    if _has_polish_language_text(title):
        strong.add("polish_text")

    if any(marker in title_lower for marker in PL_WEAK_TEXT_MARKERS):
        weak.add("title_marker_pl")

    if any(
        tag in PL_WEAK_HASHTAG_MARKERS
        or any(marker in tag for marker in PL_WEAK_HASHTAG_MARKERS)
        for tag in hashtags
    ):
        weak.add("hashtag_pl")

    if any(marker in channel_lower for marker in PL_WEAK_TEXT_MARKERS):
        weak.add("channel_marker_pl")

    if _has_foreign_subtitles_without_pl(post):
        negative.add("subtitle_foreign")

    # Confidence intentionally requires a strong clue.
    score = 0.0
    weights = {
        "subtitle_pl": 80.0,
        "poi_pl": 80.0,
        "flag_pl": 70.0,
        "polish_text": 65.0,
    }
    if strong:
        score = max(weights.get(signal, 0.0) for signal in strong)
        # Multiple independent strong clues increase confidence modestly.
        score += max(0, len(strong) - 1) * 10.0
        score += min(20.0, 7.5 * len(weak))

        if "subtitle_foreign" in negative and "subtitle_pl" not in strong:
            score -= 25.0
        if "poi_foreign" in negative and "poi_pl" not in strong:
            score -= 10.0
    else:
        # Weak matches are kept for diagnostics but cannot pass the gate.
        score = min(30.0, 10.0 * len(weak))
        if "subtitle_foreign" in negative:
            score = max(0.0, score - 15.0)

    return {
        "strong_signals": sorted(strong),
        "weak_signals": sorted(weak),
        "negative_signals": sorted(negative),
        "pl_confidence": round(max(0.0, min(100.0, score)), 1),
    }


def polish_signals(post: dict[str, Any]) -> list[str]:
    evidence = polish_evidence(post)
    return sorted(
        set(evidence["strong_signals"]) | set(evidence["weak_signals"])
    )


def deduplicate_candidates(
    posts: Iterable[dict[str, Any]],
    *,
    min_followers: int,
    min_pl_signals: int,
    min_pl_confidence: float = 50.0,
) -> tuple[list[Candidate], dict[str, int]]:
    buckets: dict[str, dict[str, Any]] = {}
    stats = defaultdict(int)

    for post in posts:
        if is_demo_row(post):
            stats["demo_rows_ignored"] += 1
            continue

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
            or post.get("seed")
            or post.get("keyword")
            or post.get("inputSource")
            or ""
        ).strip()

        evidence = polish_evidence(post)
        strong = set(evidence["strong_signals"])
        weak = set(evidence["weak_signals"])
        negative = set(evidence["negative_signals"])
        confidence = float(evidence["pl_confidence"])

        if dedupe_key not in buckets:
            buckets[dedupe_key] = {
                "tiktok_id": tiktok_id,
                "username": username,
                "display_name": str(channel.get("name") or username).strip(),
                "profile_url": str(
                    channel.get("url")
                    or channel.get("profile_url")
                    or f"https://www.tiktok.com/@{username}"
                ),
                "avatar_url": channel.get("avatar"),
                "followers": followers,
                "provider_verified": (
                    channel.get("verified")
                    if isinstance(channel.get("verified"), bool)
                    else channel.get("provider_verified")
                    if isinstance(channel.get("provider_verified"), bool)
                    else None
                ),
                "found_by": set(),
                "posts_seen": 0,
                "max_views_seen": 0,
                "max_likes_seen": 0,
                "latest_post_at": None,
                "polish_strong_signals": set(),
                "polish_weak_signals": set(),
                "polish_negative_signals": set(),
                "pl_confidence": 0.0,
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

        row["polish_strong_signals"].update(strong)
        row["polish_weak_signals"].update(weak)
        row["polish_negative_signals"].update(negative)
        row["pl_confidence"] = max(row["pl_confidence"], confidence)

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

        strong_count = len(row["polish_strong_signals"])
        if strong_count < min_pl_signals:
            stats["below_min_strong_pl_signals"] += 1
            continue

        if row["pl_confidence"] < min_pl_confidence:
            stats["below_min_pl_confidence"] += 1
            continue

        all_signals = sorted(
            row["polish_strong_signals"] | row["polish_weak_signals"]
        )

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
                polish_signal_count=len(all_signals),
                polish_signals=all_signals,
                polish_strong_signal_count=strong_count,
                polish_strong_signals=sorted(row["polish_strong_signals"]),
                polish_weak_signals=sorted(row["polish_weak_signals"]),
                pl_confidence=round(row["pl_confidence"], 1),
                discovery_eligible=True,
            )
        )

    candidates.sort(
        key=lambda c: (
            c.pl_confidence,
            c.polish_strong_signal_count,
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

    evidence = polish_evidence(post)

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
            "profile_url": channel.get("url") or channel.get("profile_url"),
            "followers": _safe_int(channel.get("followers")),
            "following": _safe_int(channel.get("following")),
            "provider_verified": (
                channel.get("verified")
                if isinstance(channel.get("verified"), bool)
                else channel.get("provider_verified")
                if isinstance(channel.get("provider_verified"), bool)
                else None
            ),
        },
        "subtitle_languages": _subtitle_languages(post),
        "poi": compact_poi,
        "polish_signals": polish_signals(post),
        "pl_evidence": evidence,
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


def revalidate_registry_from_previous_raw(
    registry_payload: dict[str, Any],
    previous_compact_payload: dict[str, Any],
    existing_queue_payload: dict[str, Any],
    *,
    min_followers: int,
    min_pl_signals: int,
    min_pl_confidence: float,
) -> tuple[dict[str, Any], dict[str, int]]:
    """
    Migration/cleanup for the v3 -> v4 rule change.

    If a creator was present in the immediately previous compact discovery run,
    re-evaluate that creator with v4 evidence. Pending weak-only false positives
    are quarantined from scanner_queue. Already enriched creators are preserved.
    """
    posts = previous_compact_payload.get("posts", [])
    if not isinstance(posts, list) or not posts:
        return registry_payload, {"legacy_rows_revalidated": 0, "legacy_rows_quarantined": 0}

    evaluated_usernames = {
        _normalize_username((post.get("channel") or {}).get("username"))
        for post in posts
        if isinstance(post, dict) and isinstance(post.get("channel"), dict)
    }
    evaluated_usernames.discard("")

    accepted, _ = deduplicate_candidates(
        posts,
        min_followers=min_followers,
        min_pl_signals=min_pl_signals,
        min_pl_confidence=min_pl_confidence,
    )
    accepted_by_username = {
        candidate.username: candidate
        for candidate in accepted
    }

    queue_items = existing_queue_payload.get("items", [])
    if not isinstance(queue_items, list):
        queue_items = []
    queue_status = {
        _normalize_username(item.get("username")): str(item.get("status") or "")
        for item in queue_items
        if isinstance(item, dict)
    }

    creators = registry_payload.get("creators", [])
    if not isinstance(creators, list):
        creators = []

    out = []
    revalidated = 0
    quarantined = 0

    for original in creators:
        if not isinstance(original, dict):
            continue
        row = dict(original)
        username = _normalize_username(row.get("username"))

        if username in evaluated_usernames:
            revalidated += 1
            accepted_candidate = accepted_by_username.get(username)

            if accepted_candidate:
                incoming = accepted_candidate.to_dict()
                row.update({
                    "polish_signal_count": incoming["polish_signal_count"],
                    "polish_signals": incoming["polish_signals"],
                    "polish_strong_signal_count": incoming["polish_strong_signal_count"],
                    "polish_strong_signals": incoming["polish_strong_signals"],
                    "polish_weak_signals": incoming["polish_weak_signals"],
                    "pl_confidence": incoming["pl_confidence"],
                    "discovery_eligible": True,
                })
                row.pop("discovery_rejection_reason", None)
            else:
                status = queue_status.get(username, "")
                # Keep historical/enriched entities in the registry, but do not
                # enqueue weak-only pending candidates for paid enrichment.
                if status not in {"enriched", "profile_scanned"}:
                    row["discovery_eligible"] = False
                    row["discovery_rejection_reason"] = "weak_pl_evidence_revalidated_v4"
                    quarantined += 1

        out.append(row)

    result = dict(registry_payload)
    result["creators"] = out
    return result, {
        "legacy_rows_revalidated": revalidated,
        "legacy_rows_quarantined": quarantined,
    }


def merge_candidate_registry(
    existing_payload: dict[str, Any],
    latest_candidates: list[Candidate],
    *,
    run_at: str,
    latest_run_meta: dict[str, Any],
) -> dict[str, Any]:
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
        old_strong = set(old.get("polish_strong_signals") or [])
        new_strong = set(incoming.get("polish_strong_signals") or [])
        old_weak = set(old.get("polish_weak_signals") or [])
        new_weak = set(incoming.get("polish_weak_signals") or [])

        first_seen = old.get("first_discovered_at") or run_at
        old_total_posts = _safe_int(
            old.get("posts_seen_total", old.get("posts_seen", 0))
        )

        merged_signals = old_signals | new_signals
        merged_strong = old_strong | new_strong
        merged_weak = old_weak | new_weak

        merged = {
            **old,
            **incoming,
            "first_discovered_at": first_seen,
            "last_discovered_at": run_at,
            "discovery_runs_seen": _safe_int(old.get("discovery_runs_seen")) + 1,
            "found_by": sorted(old_found | new_found),
            "polish_signals": sorted(merged_signals),
            "polish_signal_count": len(merged_signals),
            "polish_strong_signals": sorted(merged_strong),
            "polish_strong_signal_count": len(merged_strong),
            "polish_weak_signals": sorted(merged_weak),
            "pl_confidence": max(
                float(old.get("pl_confidence") or 0),
                float(incoming.get("pl_confidence") or 0),
            ),
            "discovery_eligible": True,
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
        merged.pop("discovery_rejection_reason", None)
        registry[key] = merged

    rows = sorted(
        registry.values(),
        key=lambda row: (
            bool(row.get("discovery_eligible", True)),
            float(row.get("pl_confidence") or 0),
            _safe_int(row.get("followers")),
            _safe_int(row.get("max_views_seen")),
        ),
        reverse=True,
    )

    return {
        "meta": {
            "latest_run": latest_run_meta,
            "registry_count": len(rows),
            "eligible_count": sum(
                1 for row in rows
                if row.get("discovery_eligible", True) is not False
            ),
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
    for creator in creators:
        key = _identity_key(creator)
        old = prior.get(key, {})
        old_status = str(old.get("status") or "")

        eligible = creator.get("discovery_eligible", True) is not False

        # Preserve already enriched/profile-scanned entities even if later
        # discovery evidence is weak, but do not spend provider calls on new
        # weak-only candidates.
        if not eligible and old_status not in {"enriched", "profile_scanned"}:
            continue

        items.append(
            {
                "username": creator.get("username"),
                "tiktok_id": creator.get("tiktok_id"),
                "priority": 0,  # assigned below after filtering
                "discovery_followers": _safe_int(creator.get("followers")),
                "polish_signals": creator.get("polish_signals") or [],
                "polish_strong_signals": creator.get("polish_strong_signals") or [],
                "discovery_pl_confidence": creator.get("pl_confidence"),
                "found_by": creator.get("found_by") or [],
                "last_discovered_at": creator.get("last_discovered_at"),
                "status": old.get("status") or "pending_profile_scan",
                **(
                    {"last_profile_scan_at": old.get("last_profile_scan_at")}
                    if old.get("last_profile_scan_at")
                    else {}
                ),
                **(
                    {"enrichment_source": old.get("enrichment_source")}
                    if old.get("enrichment_source")
                    else {}
                ),
            }
        )

    for priority, item in enumerate(items, start=1):
        item["priority"] = priority

    return {
        "meta": {
            "purpose": "Queue for authoritative profile enrichment",
            "count": len(items),
            "updated_at": updated_at,
            "discovery_filter_version": "v4-strong-pl-evidence",
        },
        "items": items,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

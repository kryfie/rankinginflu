from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from packages.classifier.pl_classifier import (
    TOKEN_RE,
    infer_category_scored,
    pl_confidence,
)

from .store import normalize_username, safe_int


PERSON_NAME_RE = re.compile(
    r"^[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż'-]{2,}"
    r"(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż'-]{2,}){1,2}$"
)

MEDIA_STRONG = (
    "redakcja", "portal informacyjny", "serwis informacyjny", "wiadomości",
    "wiadomosci", "newsroom", "gazeta", "dziennik", "telewizja", "radio ",
    "stacja radiowa", "magazyn informacyjny",
)

MEDIA_WEAK = (
    " media", "news", "tv24", "24.pl", "portal",
)

COMPANY_STRONG = (
    "sp. z o.o", "sp z oo", "s.a.", "sklep internetowy", "oficjalny sklep",
    "firma ", "producent", "dystrybutor", "agencja ",
)

CREATOR_BRAND_MARKERS = (
    "kanał", "kanal", "projekt", "współpraca", "wspolpraca", "kontakt:",
    "official account", "youtube", "instagram", "podcast", "duet", "bliźni",
    "blizni", "ekipa", "banda", "team", "vlog", "karaoke",
)


def _post_caption(post: dict[str, Any]) -> str:
    return str(post.get("caption") or post.get("title") or "")


def _post_region(post: dict[str, Any]) -> str:
    return str(
        post.get("created_in_region")
        or post.get("createdInRegion")
        or ""
    ).upper()


def _post_views(post: dict[str, Any]) -> int:
    return safe_int(post.get("views", post.get("playCount")))


def _post_timestamp(post: dict[str, Any]) -> datetime | None:
    value = post.get("timestamp")
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            pass

    unix_value = post.get("timestamp_unix", post.get("timestampUnix"))
    try:
        if unix_value:
            return datetime.fromtimestamp(float(unix_value), tz=timezone.utc)
    except Exception:
        pass

    return None


def estimate_enrichment_pl_confidence(
    creator: dict[str, Any],
    posts: list[dict[str, Any]],
) -> float:
    """
    Conservative post/profile PL confidence. It is an independent enrichment
    signal, not a replacement for discovery confidence.
    """
    bio = str(creator.get("bio") or "")
    language = str(creator.get("language") or "").lower()

    signals: list[float] = []

    bio_score = pl_confidence(bio, seed_context=False)
    if bio_score:
        signals.append(bio_score)

    if language == "pl" or language.startswith("pl-"):
        signals.append(75.0)

    captions = [_post_caption(p) for p in posts[:20]]
    caption_scores = [pl_confidence(c, seed_context=False) for c in captions]
    strong_caption_scores = [score for score in caption_scores if score >= 45]

    if captions:
        ratio = len(strong_caption_scores) / len(captions)
        if ratio >= 0.8:
            signals.append(92.0)
        elif ratio >= 0.5:
            signals.append(82.0)
        elif ratio >= 0.25:
            signals.append(67.0)
        elif strong_caption_scores:
            signals.append(52.0)

    regions = [_post_region(p) for p in posts[:20] if _post_region(p)]
    if regions:
        pl_ratio = sum(1 for region in regions if region == "PL") / len(regions)
        if pl_ratio >= 0.8:
            signals.append(88.0)
        elif pl_ratio >= 0.5:
            signals.append(78.0)
        elif pl_ratio >= 0.25:
            signals.append(62.0)

    if "🇵🇱" in (bio + "\n" + "\n".join(captions)):
        signals.append(85.0)

    if not signals:
        return 0.0

    top = max(signals)
    corroborating = sum(1 for value in signals if value >= 60)
    score = top + min(7.0, max(0, corroborating - 1) * 2.5)

    # 97.5 means "very strong public evidence" without pretending certainty.
    return round(min(97.5, score), 1)


def combine_pl_confidence(
    discovery_confidence: float | None,
    enrichment_confidence: float,
) -> float:
    """
    Preserve discovery confidence and combine it with independent enrichment
    evidence. Do not overwrite every creator with 100.
    """
    if discovery_confidence is None:
        return round(enrichment_confidence, 1)

    d = max(0.0, min(100.0, float(discovery_confidence)))
    e = max(0.0, min(100.0, float(enrichment_confidence)))

    # Discovery is the admission-stage evidence, enrichment is confirmation.
    combined = (0.60 * d) + (0.40 * e)
    return round(min(99.5, combined), 1)


def infer_account_type(
    creator: dict[str, Any],
    posts: list[dict[str, Any]],
) -> tuple[str, float, list[str]]:
    manual = str(creator.get("account_type_manual") or "").strip()
    if manual:
        return manual, 100.0, ["manual_override"]

    display_name = str(creator.get("display_name") or "").strip()
    username = normalize_username(creator.get("username"))
    bio = str(creator.get("bio") or "")
    identity = f"{display_name} {username} {bio}".lower()

    reasons: list[str] = []

    media_score = 0
    media_score += 4 * sum(1 for marker in MEDIA_STRONG if marker in identity)
    media_score += 1 * sum(1 for marker in MEDIA_WEAK if marker in identity)

    company_score = 0
    company_score += 4 * sum(1 for marker in COMPANY_STRONG if marker in identity)
    if bool(creator.get("is_organization")):
        company_score += 4
        reasons.append("provider_is_organization")
    if bool(creator.get("is_seller")):
        company_score += 2
    if bool(creator.get("is_commerce_user")):
        company_score += 1

    creator_brand_score = sum(
        1 for marker in CREATOR_BRAND_MARKERS if marker in identity
    )

    # Content formats that strongly indicate a creator-led brand, even if the
    # name contains "TV" (e.g. Melodia TV Polska karaoke).
    content = " ".join(_post_caption(p).lower() for p in posts[:12])
    if any(term in content for term in ("karaoke", "pov", "vlog", "humor", "skecz")):
        creator_brand_score += 3

    cleaned_name = re.sub(r"[^\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ' -]+", "", display_name).strip()
    looks_personal = bool(PERSON_NAME_RE.match(cleaned_name))

    # Strong publisher/company evidence wins. Generic "TV" is intentionally
    # insufficient so creator brands are not excluded accidentally.
    if company_score >= 5:
        return "company", min(99.0, 65.0 + company_score * 4.0), reasons + ["company_identity"]

    if media_score >= 4 and creator_brand_score < 3:
        return "media", min(99.0, 65.0 + media_score * 4.0), reasons + ["publisher_identity"]

    if looks_personal and creator_brand_score == 0:
        return "person", 92.0, reasons + ["personal_name"]

    return "creator_brand", min(95.0, 72.0 + creator_brand_score * 3.0), reasons + ["creator_identity"]


def _eligibility(
    creator: dict[str, Any],
    posts: list[dict[str, Any]],
) -> tuple[bool, list[str], str | None, int]:
    reasons: list[str] = []

    if bool(creator.get("private")):
        reasons.append("private_account")

    if safe_int(creator.get("followers")) < 10_000:
        reasons.append("below_10k_followers")

    if float(creator.get("pl_confidence") or 0) < 50.0:
        reasons.append("low_pl_confidence")

    account_type = str(creator.get("account_type") or "")
    if account_type not in {"person", "creator_brand"}:
        reasons.append(f"account_type_{account_type or 'unknown'}")

    measurable = [
        p for p in posts
        if not bool(p.get("is_pinned")) and _post_views(p) > 0
    ]
    if len(measurable) < 5:
        reasons.append("insufficient_measurable_posts")

    post_dates = [
        dt for dt in (_post_timestamp(p) for p in posts)
        if dt is not None
    ]
    latest = max(post_dates) if post_dates else None
    latest_iso = latest.isoformat() if latest else None

    reference_value = creator.get("last_enriched_at")
    try:
        reference = datetime.fromisoformat(str(reference_value).replace("Z", "+00:00"))
    except Exception:
        reference = datetime.now(timezone.utc)

    if latest and latest < reference - timedelta(days=180):
        reasons.append("inactive_180d")

    return (len(reasons) == 0), reasons, latest_iso, len(measurable)


def classify_creator(
    creator: dict[str, Any],
    posts: list[dict[str, Any]],
    queue_item: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = dict(creator)
    queue_item = queue_item or {}

    captions = [_post_caption(post) for post in posts[:20]]

    manual_category = str(row.get("category_manual") or "").strip()
    if manual_category:
        category = manual_category
        category_confidence = 100.0
        category_source = "manual"
    else:
        category, category_confidence, _ = infer_category_scored(
            display_name=str(row.get("display_name") or ""),
            username=normalize_username(row.get("username")),
            bio=str(row.get("bio") or ""),
            captions=captions,
        )
        category_source = "auto_v5"

    account_type, account_type_confidence, account_type_reasons = infer_account_type(
        row,
        posts,
    )

    discovery_value = queue_item.get("discovery_pl_confidence")
    if discovery_value is None:
        discovery_value = row.get("discovery_pl_confidence")

    try:
        discovery_confidence = (
            float(discovery_value)
            if discovery_value is not None
            else None
        )
    except (TypeError, ValueError):
        discovery_confidence = None

    enrichment_confidence = estimate_enrichment_pl_confidence(row, posts)
    final_pl = combine_pl_confidence(
        discovery_confidence,
        enrichment_confidence,
    )

    row.update(
        {
            "discovery_pl_confidence": (
                round(discovery_confidence, 1)
                if discovery_confidence is not None
                else None
            ),
            "enrichment_pl_confidence": enrichment_confidence,
            "pl_confidence": final_pl,
            "category": category,
            "category_confidence": category_confidence,
            "category_source": category_source,
            "account_type": account_type,
            "account_type_confidence": round(account_type_confidence, 1),
            "account_type_reasons": account_type_reasons,
            "classification_version": "v5",
        }
    )

    eligible, reasons, latest_post_at, measurable_count = _eligibility(row, posts)
    row["ranking_eligible"] = eligible
    row["eligibility_reasons"] = reasons
    row["last_post_at"] = latest_post_at
    row["measurable_post_count"] = measurable_count

    return row


def classify_all_creators(
    creators: list[dict[str, Any]],
    posts: list[dict[str, Any]],
    queue_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    posts_by_user: dict[str, list[dict[str, Any]]] = {}
    for post in posts:
        username = normalize_username(post.get("username"))
        if username:
            posts_by_user.setdefault(username, []).append(post)

    queue_by_user = {
        normalize_username(item.get("username")): item
        for item in queue_items
        if isinstance(item, dict) and normalize_username(item.get("username"))
    }

    out = []
    for creator in creators:
        username = normalize_username(creator.get("username"))
        if not username:
            continue
        out.append(
            classify_creator(
                creator,
                posts_by_user.get(username, []),
                queue_by_user.get(username),
            )
        )

    return sorted(
        out,
        key=lambda row: safe_int(row.get("followers")),
        reverse=True,
    )

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]

SEEDS_PATH = REPO_ROOT / "apps" / "discovery" / "seeds.json"
SEED_META_PATH = REPO_ROOT / "database" / "data" / "dynamic_seed_meta.json"
RELATED_PATH = REPO_ROOT / "database" / "data" / "related_handles.json"

CREATORS_PATH = REPO_ROOT / "database" / "data" / "enriched_creators.json"
POSTS_PATH = REPO_ROOT / "database" / "data" / "posts.json"
QUEUE_PATH = REPO_ROOT / "apps" / "web" / "data" / "scanner_queue.json"


GENERIC_HASHTAGS = {
    "fyp", "foryou", "foryoupage", "viral", "tiktok", "trend", "trending",
    "xyzbca", "dc", "dcv", "dlaciebie", "dlaciebiee", "dlaciebietiktok",
    "polska", "poland", "polish", "polskatiktok", "tiktokpolska",
    "polishtiktok", "fy", "funny", "love", "video", "reels", "explore",
    "follow", "like", "share", "comment", "capcut", "edit",
}

HASHTAG_RE = re.compile(r"^[a-ząćęłńóśźż0-9_]{3,40}$", re.IGNORECASE)
USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{2,40}$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _normalize_username(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("username", "uniqueId", "unique_id", "handle", "name"):
            if value.get(key):
                value = value[key]
                break
        else:
            return ""

    username = str(value or "").strip().lstrip("@").lower()
    if not USERNAME_RE.match(username):
        return ""
    return username


def _normalize_hashtag(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("name", "title", "hashtagName", "hashtag"):
            if value.get(key):
                value = value[key]
                break
        else:
            return ""

    tag = str(value or "").strip().lstrip("#").lower()
    tag = tag.replace("-", "_").replace(" ", "")
    if not HASHTAG_RE.match(tag):
        return ""
    if tag in GENERIC_HASHTAGS:
        return ""
    if tag.isdigit():
        return ""
    return tag


def _known_seeds() -> tuple[list[str], set[str]]:
    payload = _load(SEEDS_PATH, {"keywords": []})
    rows = payload.get("keywords", []) if isinstance(payload, dict) else payload
    rows = rows if isinstance(rows, list) else []

    clean = [str(row).strip() for row in rows if str(row).strip()]
    return clean, {row.lower() for row in clean}


def _eligible_creator_usernames() -> set[str]:
    payload = _load(CREATORS_PATH, {"creators": []})
    rows = payload.get("creators", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return set()

    return {
        _normalize_username(row.get("username"))
        for row in rows
        if isinstance(row, dict)
        and row.get("ranking_eligible") is not False
        and _normalize_username(row.get("username"))
    }


def _known_creator_usernames() -> set[str]:
    payload = _load(CREATORS_PATH, {"creators": []})
    rows = payload.get("creators", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return set()
    return {
        _normalize_username(row.get("username"))
        for row in rows
        if isinstance(row, dict) and _normalize_username(row.get("username"))
    }


def _queue_usernames(queue_payload: dict[str, Any]) -> set[str]:
    rows = queue_payload.get("items", [])
    if not isinstance(rows, list):
        return set()
    return {
        _normalize_username(row.get("username"))
        for row in rows
        if isinstance(row, dict) and _normalize_username(row.get("username"))
    }


def harvest(
    *,
    max_new_seeds: int = 25,
    max_dynamic_seeds_total: int = 500,
    max_related_handles: int = 20,
    min_seed_score: float = 4.0,
) -> dict[str, Any]:
    """
    Expand discovery from what successful creators already reveal.

    Hashtags:
      - count unique eligible creators using each tag
      - count recent posts using each tag
      - promote specific recurring tags into search seeds

    Mentions:
      - count @handles mentioned by eligible creators
      - promote only repeated/corroborated handles to profile enrichment

    This is deliberately conservative to control cost and avoid seed spam.
    """
    run_at = now_iso()

    eligible_creators = _eligible_creator_usernames()
    known_creators = _known_creator_usernames()

    posts_payload = _load(POSTS_PATH, {"posts": []})
    posts = posts_payload.get("posts", []) if isinstance(posts_payload, dict) else []
    posts = posts if isinstance(posts, list) else []

    queue_payload = _load(QUEUE_PATH, {"meta": {}, "items": []})
    queue_items = queue_payload.get("items", [])
    queue_items = queue_items if isinstance(queue_items, list) else []
    queued = _queue_usernames(queue_payload)

    tag_sources: dict[str, set[str]] = defaultdict(set)
    tag_posts: dict[str, set[str]] = defaultdict(set)
    mention_sources: dict[str, set[str]] = defaultdict(set)
    mention_posts: dict[str, set[str]] = defaultdict(set)

    for post in posts:
        if not isinstance(post, dict):
            continue

        source_creator = _normalize_username(post.get("username"))
        if source_creator not in eligible_creators:
            continue

        post_id = str(post.get("id") or "").strip()
        if not post_id:
            continue

        for raw_tag in post.get("hashtags") or []:
            tag = _normalize_hashtag(raw_tag)
            if not tag:
                continue
            tag_sources[tag].add(source_creator)
            tag_posts[tag].add(post_id)

        for raw_mention in post.get("mentions") or []:
            handle = _normalize_username(raw_mention)
            if not handle:
                continue
            if handle == source_creator:
                continue
            mention_sources[handle].add(source_creator)
            mention_posts[handle].add(post_id)

    # ----------------------------
    # Dynamic hashtags -> seed list
    # ----------------------------
    seeds, known_seed_set = _known_seeds()
    meta_payload = _load(SEED_META_PATH, {"version": 1, "seeds": []})
    old_meta = meta_payload.get("seeds", []) if isinstance(meta_payload, dict) else []
    old_meta = old_meta if isinstance(old_meta, list) else []

    meta_by_seed = {
        str(row.get("seed") or "").lower(): dict(row)
        for row in old_meta
        if isinstance(row, dict) and row.get("seed")
    }

    candidates = []
    for tag, sources in tag_sources.items():
        post_count = len(tag_posts[tag])
        creator_count = len(sources)

        # A tag seen across creators is much more valuable than one repeated by
        # a single creator. Single-creator tags can still qualify if repeated.
        score = (
            creator_count * 3.0
            + min(post_count, 6) * 0.75
        )

        if creator_count >= 2:
            score += 2.0

        if score < min_seed_score:
            continue

        # Search the actual discovered topic; PL location + downstream PL gate
        # prevent us from needing to append "polska" to every term.
        seed = tag
        if seed.lower() in known_seed_set:
            continue

        candidates.append(
            {
                "seed": seed,
                "score": round(score, 2),
                "unique_creators": creator_count,
                "post_count": post_count,
                "source_creators": sorted(sources)[:20],
            }
        )

    candidates.sort(
        key=lambda row: (
            row["score"],
            row["unique_creators"],
            row["post_count"],
        ),
        reverse=True,
    )

    dynamic_existing_count = len(meta_by_seed)
    remaining_capacity = max(
        0,
        max_dynamic_seeds_total - dynamic_existing_count,
    )
    new_seed_rows = candidates[
        : min(max_new_seeds, remaining_capacity)
    ]

    for row in new_seed_rows:
        seed = row["seed"]
        seeds.append(seed)
        known_seed_set.add(seed.lower())
        meta_by_seed[seed.lower()] = {
            **row,
            "source": "auto_hashtag",
            "first_seen_at": run_at,
            "last_seen_at": run_at,
            "status": "active",
        }

    # Refresh evidence for already-known dynamic seeds too.
    for tag, sources in tag_sources.items():
        existing = meta_by_seed.get(tag.lower())
        if not existing:
            continue
        existing["last_seen_at"] = run_at
        existing["unique_creators"] = len(sources)
        existing["post_count"] = len(tag_posts[tag])
        existing["source_creators"] = sorted(sources)[:20]

    _write(SEEDS_PATH, {"keywords": seeds})
    _write(
        SEED_META_PATH,
        {
            "version": 1,
            "updated_at": run_at,
            "count": len(meta_by_seed),
            "seeds": sorted(
                meta_by_seed.values(),
                key=lambda row: (
                    float(row.get("score") or 0),
                    int(row.get("unique_creators") or 0),
                ),
                reverse=True,
            ),
        },
    )

    # --------------------------------
    # Creator mentions -> profile queue
    # --------------------------------
    related_payload = _load(
        RELATED_PATH,
        {"version": 1, "handles": []},
    )
    old_related = related_payload.get("handles", [])
    old_related = old_related if isinstance(old_related, list) else []

    related_by_handle = {
        _normalize_username(row.get("username")): dict(row)
        for row in old_related
        if isinstance(row, dict) and _normalize_username(row.get("username"))
    }

    mention_candidates = []
    for handle, sources in mention_sources.items():
        if handle in known_creators or handle in queued:
            continue

        mentions_count = len(mention_posts[handle])
        source_count = len(sources)

        # Conservative: either corroborated by >=2 eligible creators, or
        # repeatedly mentioned in >=2 separate posts.
        if source_count < 2 and mentions_count < 2:
            continue

        score = (
            source_count * 4.0
            + min(mentions_count, 5) * 1.0
        )
        mention_candidates.append(
            {
                "username": handle,
                "score": round(score, 2),
                "unique_source_creators": source_count,
                "mentions_count": mentions_count,
                "source_creators": sorted(sources)[:20],
            }
        )

    mention_candidates.sort(
        key=lambda row: (
            row["score"],
            row["unique_source_creators"],
            row["mentions_count"],
        ),
        reverse=True,
    )

    promoted = []
    max_priority = max(
        [
            int(row.get("priority") or 0)
            for row in queue_items
            if isinstance(row, dict)
        ]
        or [0]
    )

    for candidate in mention_candidates[:max_related_handles]:
        username = candidate["username"]
        if username in related_by_handle:
            old = related_by_handle[username]
            old.update(candidate)
            old["last_seen_at"] = run_at
            continue

        max_priority += 1
        related_by_handle[username] = {
            **candidate,
            "source": "related_mentions",
            "status": "queued_for_profile_check",
            "first_seen_at": run_at,
            "last_seen_at": run_at,
        }

        queue_items.append(
            {
                "username": username,
                "tiktok_id": None,
                "priority": max_priority,
                "discovery_followers": None,
                "polish_signals": [],
                "polish_strong_signals": [],
                "discovery_pl_confidence": None,
                "found_by": ["related_mentions"],
                "last_discovered_at": run_at,
                "status": "pending_profile_scan",
                "source": "related_mentions",
                "related_score": candidate["score"],
                "related_source_creators": candidate["source_creators"],
            }
        )
        queued.add(username)
        promoted.append(username)

    _write(
        RELATED_PATH,
        {
            "version": 1,
            "updated_at": run_at,
            "count": len(related_by_handle),
            "handles": sorted(
                related_by_handle.values(),
                key=lambda row: float(row.get("score") or 0),
                reverse=True,
            ),
        },
    )

    queue_meta = queue_payload.get("meta", {})
    queue_meta = dict(queue_meta) if isinstance(queue_meta, dict) else {}
    queue_meta.update(
        {
            "updated_at": run_at,
            "count": len(queue_items),
            "related_mentions_enabled": True,
        }
    )
    _write(
        QUEUE_PATH,
        {
            "meta": queue_meta,
            "items": queue_items,
        },
    )

    return {
        "eligible_creators_scanned": len(eligible_creators),
        "hashtags_observed": len(tag_sources),
        "dynamic_seed_candidates": len(candidates),
        "new_dynamic_seeds": len(new_seed_rows),
        "dynamic_seed_total": len(meta_by_seed),
        "mention_handles_observed": len(mention_sources),
        "related_candidates": len(mention_candidates),
        "related_handles_promoted": len(promoted),
        "promoted_handles": promoted,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="influrank-expansion",
        description="Expand discovery from hashtags and creator mentions.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("harvest")
    p.add_argument("--max-new-seeds", type=int, default=25)
    p.add_argument("--max-dynamic-seeds-total", type=int, default=500)
    p.add_argument("--max-related-handles", type=int, default=20)
    p.add_argument("--min-seed-score", type=float, default=4.0)

    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.command == "harvest":
        result = harvest(
            max_new_seeds=max(0, args.max_new_seeds),
            max_dynamic_seeds_total=max(
                0,
                args.max_dynamic_seeds_total,
            ),
            max_related_handles=max(0, args.max_related_handles),
            min_seed_score=max(0.0, args.min_seed_score),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

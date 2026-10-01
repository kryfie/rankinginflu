from __future__ import annotations

import argparse
import json
from pathlib import Path

from .apify_client import run_actor_sync
from .config import REPO_ROOT, Settings
from .pipeline import build_scanner_queue, deduplicate_candidates, write_json


DEFAULT_SEEDS = REPO_ROOT / "apps" / "discovery" / "seeds.json"


def _load_keywords(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(payload, list):
        keywords = payload
    elif isinstance(payload, dict):
        keywords = payload.get("keywords", [])
    else:
        raise ValueError("Seeds file must be a JSON list or {'keywords': [...]}.")

    clean: list[str] = []
    seen: set[str] = set()
    for item in keywords:
        keyword = str(item).strip()
        if keyword and keyword.lower() not in seen:
            seen.add(keyword.lower())
            clean.append(keyword)

    if not clean:
        raise ValueError(f"No keywords found in {path}.")

    return clean


def discover(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    seeds_path = Path(args.seeds).resolve()
    keywords = _load_keywords(seeds_path)

    min_followers = args.min_followers
    max_items = args.max_items
    sort_type = args.sort_type
    date_range = args.date_range
    location = args.location

    actor_input = {
        "keywords": keywords,
        "location": location,
        "maxItems": max_items,
        "dateRange": date_range,
        "sortType": sort_type,
        "includeSearchKeywords": True,
    }

    print(
        f"Discovery: {len(keywords)} keywords | location={location} | "
        f"maxItems={max_items} | minFollowers={min_followers}"
    )
    print(f"Actor: {settings.actor_id}")

    posts = run_actor_sync(
        token=settings.apify_token,
        actor_id=settings.actor_id,
        actor_input=actor_input,
        timeout_seconds=settings.timeout_seconds,
    )

    candidates, stats = deduplicate_candidates(
        posts,
        min_followers=min_followers,
    )
    queue = build_scanner_queue(candidates)

    write_json(settings.output_raw, posts)
    write_json(
        settings.output_candidates,
        {
            "meta": {
                "actor": settings.actor_id,
                "keywords": keywords,
                "location": location,
                "dateRange": date_range,
                "sortType": sort_type,
                "maxItemsRequested": max_items,
                "minFollowers": min_followers,
                "stats": stats,
            },
            "creators": [candidate.to_dict() for candidate in candidates],
        },
    )
    write_json(
        settings.output_queue,
        {
            "meta": {
                "purpose": "Queue for authoritative profile enrichment",
                "count": len(queue),
            },
            "items": queue,
        },
    )

    print()
    print("RESULT")
    for key, value in sorted(stats.items()):
        print(f"  {key}: {value}")

    print()
    print(f"Candidates: {settings.output_candidates}")
    print(f"Scanner queue: {settings.output_queue}")
    print(f"Raw posts: {settings.output_raw}")

    if candidates:
        print()
        print("Top 10 candidates:")
        for candidate in candidates[:10]:
            print(
                f"  @{candidate.username:<24} "
                f"followers={candidate.followers:<10} "
                f"PLsignals={candidate.polish_signal_count} "
                f"postsSeen={candidate.posts_seen}"
            )

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="influrank-discovery",
        description="Discover Polish TikTok creator candidates via an external data provider.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    command = subparsers.add_parser("run", help="Run TikTok creator discovery.")
    command.add_argument(
        "--seeds",
        default=str(DEFAULT_SEEDS),
        help="Path to JSON file containing discovery keywords.",
    )
    command.add_argument(
        "--max-items",
        type=int,
        default=Settings.max_items,
        help="Maximum total posts requested from the Actor.",
    )
    command.add_argument(
        "--min-followers",
        type=int,
        default=Settings.min_followers,
        help="Discard candidates below this follower count.",
    )
    command.add_argument(
        "--location",
        default=Settings.location,
        help="TikTok search location/region (default: PL).",
    )
    command.add_argument(
        "--date-range",
        choices=[
            "DEFAULT",
            "ALL_TIME",
            "YESTERDAY",
            "THIS_WEEK",
            "THIS_MONTH",
            "LAST_THREE_MONTHS",
            "LAST_SIX_MONTHS",
        ],
        default=Settings.date_range,
    )
    command.add_argument(
        "--sort-type",
        choices=["RELEVANCE", "MOST_LIKED", "DATE_POSTED"],
        default=Settings.sort_type,
    )
    command.set_defaults(func=discover)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

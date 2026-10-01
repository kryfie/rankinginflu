from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .apify_client import ApifyError, run_actor_sync
from .config import REPO_ROOT, Settings
from .pipeline import (
    build_scanner_queue,
    compact_post,
    deduplicate_candidates,
    load_json,
    merge_candidate_registry,
    utcnow,
    write_json,
)


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
        key = keyword.lower()
        if keyword and key not in seen:
            seen.add(key)
            clean.append(keyword)

    if not clean:
        raise ValueError(f"No keywords found in {path}.")

    return clean


def _select_seeds(keywords: list[str], max_seeds: int) -> list[str]:
    if max_seeds <= 0:
        return keywords
    return keywords[:max_seeds]


def discover(args: argparse.Namespace) -> int:
    settings = Settings.from_env()

    seeds_path = Path(args.seeds).resolve()
    all_keywords = _load_keywords(seeds_path)
    keywords = _select_seeds(all_keywords, args.max_seeds)

    if not keywords:
        raise RuntimeError("No discovery seeds selected.")

    run_at = utcnow()
    all_posts: list[dict] = []
    seed_stats: list[dict] = []
    errors: list[dict] = []

    print(
        f"InfluRank discovery | seeds={len(keywords)}/{len(all_keywords)} | "
        f"resultsPerSeed={args.results_per_seed} | location={args.location} | "
        f"minFollowers={args.min_followers} | minPLSignals={args.min_pl_signals}"
    )
    print(f"Actor: {settings.actor_id}")
    print()

    for index, seed in enumerate(keywords, start=1):
        actor_input = {
            # One keyword per Actor run = real per-seed coverage.
            "keywords": [seed],
            "location": args.location,
            "maxItems": args.results_per_seed,
            "dateRange": args.date_range,
            "sortType": args.sort_type,
            "includeSearchKeywords": True,
        }

        print(f"[{index}/{len(keywords)}] seed={seed!r} ...", flush=True)

        try:
            posts = run_actor_sync(
                token=settings.apify_token,
                actor_id=settings.actor_id,
                actor_input=actor_input,
                timeout_seconds=settings.timeout_seconds,
            )
        except ApifyError as exc:
            errors.append({"seed": seed, "error": str(exc)})
            print(f"  ERROR: {exc}", file=sys.stderr)
            print(
                "  Stopping before additional provider runs to avoid repeated "
                "failures/charges.",
                file=sys.stderr,
            )
            break

        for post in posts:
            post["_discovery_seed"] = seed

        all_posts.extend(posts)
        seed_stats.append(
            {
                "seed": seed,
                "posts_returned": len(posts),
            }
        )
        print(f"  returned={len(posts)}")

    if not all_posts:
        raise RuntimeError(
            "Discovery returned zero posts. No repository data files were changed."
        )

    candidates, stats = deduplicate_candidates(
        all_posts,
        min_followers=args.min_followers,
        min_pl_signals=args.min_pl_signals,
    )

    latest_run_meta = {
        "run_at": run_at,
        "actor": settings.actor_id,
        "seeds_requested": keywords,
        "seeds_completed": [row["seed"] for row in seed_stats],
        "resultsPerSeed": args.results_per_seed,
        "location": args.location,
        "dateRange": args.date_range,
        "sortType": args.sort_type,
        "minFollowers": args.min_followers,
        "minPLSignals": args.min_pl_signals,
        "stats": stats,
        "per_seed": seed_stats,
        "errors": errors,
    }

    existing_registry = load_json(settings.registry_path, {"creators": []})
    registry_payload = merge_candidate_registry(
        existing_registry,
        candidates,
        run_at=run_at,
        latest_run_meta=latest_run_meta,
    )

    existing_queue = load_json(settings.queue_path, {"items": []})
    queue_payload = build_scanner_queue(
        registry_payload,
        existing_queue,
        updated_at=run_at,
    )

    compact_raw_payload = {
        "meta": latest_run_meta,
        "posts": [compact_post(post) for post in all_posts],
    }

    # Full provider output is useful for short-lived diagnostics only.
    # It is gitignored and uploaded by Actions as an artifact.
    write_json(settings.full_raw_path, all_posts)

    # Persistent, compact repository data.
    write_json(settings.compact_raw_path, compact_raw_payload)
    write_json(settings.registry_path, registry_payload)
    write_json(settings.queue_path, queue_payload)

    print()
    print("RESULT")
    for key, value in sorted(stats.items()):
        print(f"  {key}: {value}")
    print(f"  registry_count: {registry_payload['meta']['registry_count']}")
    print(f"  queue_count: {queue_payload['meta']['count']}")
    print(f"  seeds_completed: {len(seed_stats)}")
    print(f"  provider_errors: {len(errors)}")

    if candidates:
        print()
        print("Top candidates from latest run:")
        for candidate in candidates[:15]:
            print(
                f"  @{candidate.username:<24} "
                f"followers={candidate.followers:<10} "
                f"PLsignals={candidate.polish_signal_count} "
                f"foundBy={','.join(candidate.found_by)}"
            )

    print()
    print(f"Registry: {settings.registry_path}")
    print(f"Queue: {settings.queue_path}")
    print(f"Compact raw: {settings.compact_raw_path}")
    print(f"Full raw diagnostic: {settings.full_raw_path}")

    # A partial provider error still leaves useful completed-seed data.
    # Return success so GitHub can persist that completed work.
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="influrank-discovery",
        description="Discover Polish TikTok creator candidates seed by seed.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    command = subparsers.add_parser("run", help="Run TikTok creator discovery.")
    command.add_argument(
        "--seeds",
        default=str(DEFAULT_SEEDS),
        help="JSON file containing discovery keywords.",
    )
    command.add_argument(
        "--results-per-seed",
        type=int,
        default=Settings.results_per_seed,
        help="Maximum posts requested separately for each seed.",
    )
    command.add_argument(
        "--max-seeds",
        type=int,
        default=Settings.max_seeds,
        help="How many seeds to run. 0 means all configured seeds.",
    )
    command.add_argument(
        "--min-followers",
        type=int,
        default=Settings.min_followers,
        help="Reject new candidates below this discovery follower count.",
    )
    command.add_argument(
        "--min-pl-signals",
        type=int,
        default=Settings.min_pl_signals,
        help="Minimum number of lightweight Polish discovery signals.",
    )
    command.add_argument(
        "--location",
        default=Settings.location,
        help="TikTok search region (default: PL).",
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

    if args.command == "run":
        if args.results_per_seed < 1:
            parser.error("--results-per-seed must be >= 1")
        if args.max_seeds < 0:
            parser.error("--max-seeds must be >= 0")
        if args.min_followers < 0:
            parser.error("--min-followers must be >= 0")
        if args.min_pl_signals < 0:
            parser.error("--min-pl-signals must be >= 0")

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

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
    is_demo_row,
    load_json,
    merge_candidate_registry,
    revalidate_registry_from_previous_raw,
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


def _select_seeds(
    keywords: list[str],
    *,
    start_seed: int,
    max_seeds: int,
) -> list[str]:
    if start_seed < 0:
        raise ValueError("start_seed must be >= 0")

    if start_seed >= len(keywords):
        return []

    remaining = keywords[start_seed:]

    if max_seeds <= 0:
        return remaining

    return remaining[:max_seeds]


def _usable_provider_row(row: dict) -> bool:
    if not isinstance(row, dict) or is_demo_row(row):
        return False
    channel = row.get("channel")
    return (
        isinstance(channel, dict)
        and bool(str(channel.get("username") or "").strip())
    )


def discover(args: argparse.Namespace) -> int:
    settings = Settings.from_env()

    seeds_path = Path(args.seeds).resolve()
    all_keywords = _load_keywords(seeds_path)
    keywords = _select_seeds(
        all_keywords,
        start_seed=args.start_seed,
        max_seeds=args.max_seeds,
    )

    if not keywords:
        raise RuntimeError(
            f"No discovery seeds selected. start_seed={args.start_seed}, "
            f"available={len(all_keywords)}."
        )

    run_at = utcnow()
    all_posts: list[dict] = []
    all_provider_rows: list[dict] = []
    seed_stats: list[dict] = []
    errors: list[dict] = []

    print(
        f"InfluRank discovery v4 | seeds={len(keywords)}/{len(all_keywords)} | "
        f"startSeed={args.start_seed} | resultsPerSeed={args.results_per_seed} | "
        f"location={args.location} | minFollowers={args.min_followers} | "
        f"minStrongPLSignals={args.min_pl_signals} | "
        f"minPLConfidence={args.min_pl_confidence}"
    )
    print(f"Actor: {settings.actor_id}")
    print()

    for index, seed in enumerate(keywords, start=1):
        actor_input = {
            "keywords": [seed],
            "location": args.location,
            "maxItems": args.results_per_seed,
            "dateRange": args.date_range,
            "sortType": args.sort_type,
            "includeSearchKeywords": True,
        }

        print(f"[{index}/{len(keywords)}] seed={seed!r} ...", flush=True)

        try:
            rows = run_actor_sync(
                token=settings.apify_token,
                actor_id=settings.actor_id,
                actor_input=actor_input,
                timeout_seconds=settings.timeout_seconds,
            )
        except ApifyError as exc:
            errors.append({"seed": seed, "error": str(exc)})
            print(f"  ERROR: {exc}", file=sys.stderr)
            print(
                "  Stopping before additional provider runs to avoid repeated failures/charges.",
                file=sys.stderr,
            )
            break

        all_provider_rows.extend(rows)

        demo_rows = [row for row in rows if is_demo_row(row)]
        usable = [row for row in rows if _usable_provider_row(row)]

        for post in usable:
            post["_discovery_seed"] = seed

        all_posts.extend(usable)

        if usable:
            status = "productive"
        elif demo_rows:
            status = "demo_only"
        else:
            status = "no_usable_rows"

        seed_stats.append(
            {
                "seed": seed,
                "rows_returned": len(rows),
                "usable_posts": len(usable),
                "demo_rows": len(demo_rows),
                "status": status,
            }
        )

        print(
            f"  rows={len(rows)} usable={len(usable)} "
            f"demo={len(demo_rows)} status={status}"
        )

    candidates, stats = deduplicate_candidates(
        all_posts,
        min_followers=args.min_followers,
        min_pl_signals=args.min_pl_signals,
        min_pl_confidence=args.min_pl_confidence,
    )

    latest_run_meta = {
        "run_at": run_at,
        "actor": settings.actor_id,
        "filterVersion": "v4-strong-pl-evidence",
        "startSeed": args.start_seed,
        "seeds_requested": keywords,
        "seeds_completed": [row["seed"] for row in seed_stats],
        "resultsPerSeed": args.results_per_seed,
        "location": args.location,
        "dateRange": args.date_range,
        "sortType": args.sort_type,
        "minFollowers": args.min_followers,
        "minStrongPLSignals": args.min_pl_signals,
        "minPLConfidence": args.min_pl_confidence,
        "stats": stats,
        "per_seed": seed_stats,
        "errors": errors,
    }

    existing_registry = load_json(settings.registry_path, {"creators": []})
    existing_queue = load_json(settings.queue_path, {"items": []})
    previous_compact = load_json(settings.compact_raw_path, {"posts": []})

    # Clean up weak-only pending candidates produced by v3 from the immediately
    # previous compact discovery run before adding new v4 candidates.
    existing_registry, migration_stats = revalidate_registry_from_previous_raw(
        existing_registry,
        previous_compact,
        existing_queue,
        min_followers=args.min_followers,
        min_pl_signals=args.min_pl_signals,
        min_pl_confidence=args.min_pl_confidence,
    )
    latest_run_meta["migration"] = migration_stats

    registry_payload = merge_candidate_registry(
        existing_registry,
        candidates,
        run_at=run_at,
        latest_run_meta=latest_run_meta,
    )

    queue_payload = build_scanner_queue(
        registry_payload,
        existing_queue,
        updated_at=run_at,
    )

    compact_raw_payload = {
        "meta": latest_run_meta,
        "posts": [compact_post(post) for post in all_posts],
    }

    # Full provider output is diagnostic only. It includes demo rows so we can
    # inspect provider behavior, but demo rows never enter candidate logic.
    write_json(
        settings.full_raw_path,
        {
            "meta": latest_run_meta,
            "provider_rows": all_provider_rows,
        },
    )

    write_json(settings.compact_raw_path, compact_raw_payload)
    write_json(settings.registry_path, registry_payload)
    write_json(settings.queue_path, queue_payload)

    print()
    print("RESULT")
    for key, value in sorted(stats.items()):
        print(f"  {key}: {value}")
    for key, value in sorted(migration_stats.items()):
        print(f"  {key}: {value}")
    print(f"  registry_count: {registry_payload['meta']['registry_count']}")
    print(f"  eligible_registry_count: {registry_payload['meta']['eligible_count']}")
    print(f"  queue_count: {queue_payload['meta']['count']}")
    print(f"  seeds_completed: {len(seed_stats)}")
    print(f"  provider_errors: {len(errors)}")

    if candidates:
        print()
        print("Accepted candidates from latest run:")
        for candidate in candidates[:20]:
            print(
                f"  @{candidate.username:<24} "
                f"followers={candidate.followers:<10} "
                f"PL={candidate.pl_confidence:>5.1f} "
                f"strong={candidate.polish_strong_signal_count} "
                f"signals={','.join(candidate.polish_strong_signals)} "
                f"foundBy={','.join(candidate.found_by)}"
            )

    print()
    print(f"Registry: {settings.registry_path}")
    print(f"Queue: {settings.queue_path}")
    print(f"Compact raw: {settings.compact_raw_path}")
    print(f"Full raw diagnostic: {settings.full_raw_path}")

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
        "--start-seed",
        type=int,
        default=0,
        help="Zero-based seed offset.",
    )
    command.add_argument(
        "--max-seeds",
        type=int,
        default=Settings.max_seeds,
        help="How many seeds to run from start_seed. 0 means all remaining seeds.",
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
        help="Minimum number of STRONG Polish discovery signals.",
    )
    command.add_argument(
        "--min-pl-confidence",
        type=float,
        default=Settings.min_pl_confidence,
        help="Minimum conservative PL confidence (0-100).",
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
        if args.start_seed < 0:
            parser.error("--start-seed must be >= 0")
        if args.max_seeds < 0:
            parser.error("--max-seeds must be >= 0")
        if args.min_followers < 0:
            parser.error("--min-followers must be >= 0")
        if args.min_pl_signals < 0:
            parser.error("--min-pl-signals must be >= 0")
        if not (0 <= args.min_pl_confidence <= 100):
            parser.error("--min-pl-confidence must be between 0 and 100")

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

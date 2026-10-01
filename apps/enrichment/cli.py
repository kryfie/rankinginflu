from __future__ import annotations

import argparse
import json

from .apify_client import run_profile_actor
from .config import Settings
from .pipeline import enrich_state, select_queue_items, utcnow
from .store import load_json, write_json


def run(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    queue_payload = load_json(settings.queue_path, {"items": []})

    selected = select_queue_items(
        queue_payload,
        max_profiles=args.max_profiles,
        refresh_all=args.refresh_all,
        min_refresh_age_hours=args.min_refresh_age_hours,
    )

    if not selected:
        print("No queue items need enrichment.")
        return 0

    handles = [str(item.get("username") or "").lstrip("@") for item in selected]
    print(
        f"InfluRank enrichment | profiles={len(handles)} | "
        f"maxPosts={args.max_posts} | refreshAll={args.refresh_all}"
    )
    print(f"Actor: {settings.actor_id}")
    print("Handles:")
    for handle in handles:
        print(f"  @{handle}")

    rows = run_profile_actor(
        token=settings.apify_token,
        actor_id=settings.actor_id,
        handles=handles,
        max_posts=args.max_posts,
        timeout_seconds=settings.timeout_seconds,
    )

    run_at = utcnow()
    write_json(
        settings.raw_path,
        {
            "meta": {
                "run_at": run_at,
                "actor": settings.actor_id,
                "handles": handles,
                "rows": len(rows),
            },
            "rows": rows,
        },
    )

    result = enrich_state(
        settings=settings,
        actor_rows=rows,
        selected_items=selected,
        run_at=run_at,
    )

    print()
    print("RESULT")
    for key in (
        "selected",
        "successful",
        "failed",
        "creators_total",
        "posts_total",
        "snapshots_total",
        "ranking_count",
    ):
        print(f"  {key}: {result[key]}")

    if result["failures"]:
        print("Failures:")
        for username, message in result["failures"].items():
            print(f"  @{username}: {message}")

    print()
    print(f"Ranking: {settings.web_ranking_path}")
    print(f"Profiles: {settings.creators_path}")
    print(f"Posts: {settings.posts_path}")
    print(f"Snapshots: {settings.snapshots_path}")
    print(f"Queue: {settings.queue_path}")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="influrank-enrichment",
        description="Enrich scanner_queue TikTok accounts with profile and recent-post data.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    command = sub.add_parser("run")
    command.add_argument(
        "--max-profiles",
        type=int,
        default=10,
        help="Maximum queue profiles to enrich in this run. 0 = all eligible.",
    )
    command.add_argument(
        "--max-posts",
        type=int,
        default=13,
        help="Latest posts requested per profile (provider max: 13).",
    )
    command.add_argument(
        "--refresh-all",
        action="store_true",
        help="Refresh already enriched accounts too.",
    )
    command.add_argument(
        "--min-refresh-age-hours",
        type=int,
        default=0,
        help=(
            "With --refresh-all, skip profiles refreshed more recently "
            "than this many hours."
        ),
    )
    command.set_defaults(func=run)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "run":
        if args.max_profiles < 0:
            parser.error("--max-profiles must be >= 0")
        if not (1 <= args.max_posts <= 13):
            parser.error("--max-posts must be between 1 and 13")
        if args.min_refresh_age_hours < 0:
            parser.error("--min-refresh-age-hours must be >= 0")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

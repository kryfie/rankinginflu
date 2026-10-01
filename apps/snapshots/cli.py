import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from apps.snapshots.growth import build_growth
from apps.snapshots.tiktok_profile import (
    PublicAccessLimitedError,
    TikTokPublicProfileReader,
)


ROOT = Path(__file__).resolve().parents[2]
PUBLIC_CREATORS = ROOT / "apps/web/data/creators.json"
SNAPSHOT_DIR = ROOT / "database/data/profile_snapshots"
STATE_FILE = ROOT / "database/data/profile_snapshot_state.json"
GROWTH_FILE = ROOT / "database/data/growth_metrics.json"


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


def _creator_rows(public_payload):
    rows = public_payload.get("creators", []) if isinstance(public_payload, dict) else []
    out = []
    seen = set()

    for row in rows:
        if not isinstance(row, dict):
            continue

        handle = str(row.get("handle") or "").lstrip("@").strip().lower()
        if not handle or handle in seen:
            continue

        seen.add(handle)
        out.append(
            {
                "handle": handle,
                "name": row.get("name"),
                "rank": row.get("rank"),
                "score": row.get("score"),
                "category": row.get("category"),
                "city": row.get("city"),
            }
        )

    return out


def run_snapshot(
    *,
    snapshot_day=None,
    max_profiles=0,
    delay_seconds=2.5,
    public_creators=PUBLIC_CREATORS,
    snapshot_dir=SNAPSHOT_DIR,
    state_file=STATE_FILE,
    growth_file=GROWTH_FILE,
    reader_factory=TikTokPublicProfileReader,
):
    snapshot_day = snapshot_day or date.today().isoformat()
    date.fromisoformat(snapshot_day)  # validate

    public_payload = _read_json(public_creators, {})
    rows = _creator_rows(public_payload)

    if not rows:
        raise RuntimeError(f"No creators found in {public_creators}")

    snapshot_dir = Path(snapshot_dir)
    snapshot_path = snapshot_dir / f"{snapshot_day}.json"

    payload = _read_json(snapshot_path, {})
    if not isinstance(payload, dict):
        payload = {}

    creators = payload.get("creators")
    if not isinstance(creators, dict):
        creators = {}

    started_at = payload.get("started_at") or _utcnow()

    # Always refresh free ranking metadata from the latest public ranking,
    # even if the profile itself was already successfully scanned today.
    current_handles = []
    for row in rows:
        handle = row["handle"]
        current_handles.append(handle)
        existing = creators.get(handle)
        if not isinstance(existing, dict):
            existing = {}

        existing.update(
            {
                "handle": handle,
                "name": row.get("name"),
                "rank": row.get("rank"),
                "score": row.get("score"),
                "category": row.get("category"),
                "city": row.get("city"),
            }
        )
        creators[handle] = existing

    # Keep historical rows if a creator disappeared from today's public
    # ranking during a same-day rerun, but only current handles count toward
    # today's completion statistics.
    pending = [
        handle
        for handle in current_handles
        if creators.get(handle, {}).get("profile_status") != "ok"
    ]

    if max_profiles and max_profiles > 0:
        pending = pending[:max_profiles]

    attempted_this_run = 0
    success_this_run = 0
    failed_this_run = 0
    stopped_by_rate_limit = False
    stop_reason = None

    reader = reader_factory(delay_seconds=delay_seconds)

    try:
        for index, handle in enumerate(pending, start=1):
            attempted_this_run += 1
            print(
                f"[{index}/{len(pending)}] snapshot @{handle}",
                flush=True,
            )

            try:
                profile = reader.get_profile(handle)
            except PublicAccessLimitedError as exc:
                failed_this_run += 1
                stopped_by_rate_limit = True
                stop_reason = str(exc)
                creators[handle].update(
                    {
                        "profile_status": "limited",
                        "profile_error": str(exc),
                        "last_attempt_at": _utcnow(),
                    }
                )
                print(f"STOP @{handle}: {exc}", file=sys.stderr, flush=True)
                break
            except Exception as exc:
                failed_this_run += 1
                creators[handle].update(
                    {
                        "profile_status": "error",
                        "profile_error": f"{type(exc).__name__}: {exc}",
                        "last_attempt_at": _utcnow(),
                    }
                )
                print(f"WARN @{handle}: {exc}", file=sys.stderr, flush=True)
                continue

            if not profile:
                failed_this_run += 1
                creators[handle].update(
                    {
                        "profile_status": "not_found",
                        "profile_error": "No public profile payload found",
                        "last_attempt_at": _utcnow(),
                    }
                )
                print(
                    f"WARN @{handle}: no public profile payload found",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            creators[handle].update(
                {
                    "profile_status": "ok",
                    "profile_error": None,
                    "collected_at": profile.get("collected_at") or _utcnow(),
                    "followers": profile.get("followers"),
                    "following": profile.get("following"),
                    "total_likes": profile.get("total_likes"),
                    "video_count": profile.get("video_count"),
                    "verified": profile.get("verified"),
                }
            )
            success_this_run += 1

            # Checkpoint locally every 25 successes. The workflow commits
            # only at the end, but this protects the file during normal
            # Python-level errors and makes reruns resumable.
            if success_this_run % 25 == 0:
                checkpoint = {
                    "date": snapshot_day,
                    "source": "tiktok_public_profile_html",
                    "started_at": started_at,
                    "updated_at": _utcnow(),
                    "creators": creators,
                }
                _write_json(snapshot_path, checkpoint)

    finally:
        reader.close()

    successful_current = sum(
        1
        for handle in current_handles
        if creators.get(handle, {}).get("profile_status") == "ok"
    )
    failed_current = len(current_handles) - successful_current

    complete = successful_current == len(current_handles)

    payload = {
        "date": snapshot_day,
        "source": "tiktok_public_profile_html",
        "source_note": (
            "Light public profile snapshot only: followers, following, "
            "total likes, video count and verified. No posts and no Apify."
        ),
        "started_at": started_at,
        "finished_at": _utcnow(),
        "status": "complete" if complete else "partial",
        "stopped_by_rate_limit": stopped_by_rate_limit,
        "stop_reason": stop_reason,
        "current_creator_count": len(current_handles),
        "successful_current_profiles": successful_current,
        "missing_current_profiles": failed_current,
        "attempted_this_run": attempted_this_run,
        "success_this_run": success_this_run,
        "failed_this_run": failed_this_run,
        "creators": creators,
    }
    _write_json(snapshot_path, payload)

    state = {
        "updated_at": _utcnow(),
        "latest_snapshot_date": snapshot_day,
        "latest_snapshot_file": str(snapshot_path.relative_to(ROOT))
        if snapshot_path.is_relative_to(ROOT)
        else str(snapshot_path),
        "status": payload["status"],
        "current_creator_count": len(current_handles),
        "successful_current_profiles": successful_current,
        "missing_current_profiles": failed_current,
        "stopped_by_rate_limit": stopped_by_rate_limit,
        "stop_reason": stop_reason,
    }
    _write_json(state_file, state)

    growth = build_growth(snapshot_dir, growth_file)

    print(
        "SNAPSHOT "
        f"date={snapshot_day} "
        f"status={payload['status']} "
        f"creators={len(current_handles)} "
        f"ok={successful_current} "
        f"missing={failed_current} "
        f"attempted_this_run={attempted_this_run} "
        f"rate_limited={stopped_by_rate_limit}",
        flush=True,
    )
    print(
        f"GROWTH days={growth.get('available_snapshot_days')} "
        f"latest={growth.get('latest_date')}",
        flush=True,
    )

    return payload


def main():
    parser = argparse.ArgumentParser(
        description="InfluRank daily light creator profile snapshots"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run")
    run.add_argument(
        "--date",
        default=None,
        help="UTC snapshot date YYYY-MM-DD; default: current date",
    )
    run.add_argument(
        "--max-profiles",
        type=int,
        default=0,
        help="0 = all current creators; useful for manual tests",
    )
    run.add_argument(
        "--delay-seconds",
        type=float,
        default=2.5,
        help="Delay between public TikTok profile requests",
    )

    growth = sub.add_parser("build-growth")

    args = parser.parse_args()

    if args.command == "run":
        run_snapshot(
            snapshot_day=args.date,
            max_profiles=args.max_profiles,
            delay_seconds=args.delay_seconds,
        )
    elif args.command == "build-growth":
        payload = build_growth(SNAPSHOT_DIR, GROWTH_FILE)
        print(
            f"Growth metrics rebuilt: "
            f"{payload.get('available_snapshot_days')} snapshot days"
        )


if __name__ == "__main__":
    main()

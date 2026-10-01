import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def _pct(current, old):
    if current is None or old in (None, 0):
        return None
    return round((current - old) / old * 100.0, 4)


def _delta(current, old):
    if current is None or old is None:
        return None
    return int(current) - int(old)


def build_growth(snapshot_dir, output_path):
    snapshot_dir = Path(snapshot_dir)
    files = sorted(snapshot_dir.glob("*.json"))

    by_day = {}
    for path in files:
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue

        payload = _load(path)
        if not isinstance(payload, dict):
            continue

        creators = payload.get("creators")
        if isinstance(creators, dict):
            by_day[day] = creators

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "latest_date": None,
        "available_snapshot_days": len(by_day),
        "creators": {},
    }

    if not by_day:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return output

    latest_day = max(by_day)
    latest = by_day[latest_day]
    output["latest_date"] = latest_day.isoformat()

    for handle, current in latest.items():
        if not isinstance(current, dict):
            continue

        row = {
            "as_of": latest_day.isoformat(),
            "followers": current.get("followers"),
            "rank": current.get("rank"),
            "score": current.get("score"),
        }

        for days in (1, 7, 30):
            old_day = latest_day - timedelta(days=days)
            old = by_day.get(old_day, {}).get(handle)

            if not isinstance(old, dict):
                row[f"followers_delta_{days}d"] = None
                row[f"followers_growth_{days}d_pct"] = None
                row[f"rank_change_{days}d"] = None
                continue

            row[f"followers_delta_{days}d"] = _delta(
                current.get("followers"),
                old.get("followers"),
            )
            row[f"followers_growth_{days}d_pct"] = _pct(
                current.get("followers"),
                old.get("followers"),
            )

            current_rank = current.get("rank")
            old_rank = old.get("rank")
            if current_rank is None or old_rank is None:
                row[f"rank_change_{days}d"] = None
            else:
                # Positive = moved up in the ranking.
                row[f"rank_change_{days}d"] = int(old_rank) - int(current_rank)

        historical_ranks = []
        for creators in by_day.values():
            candidate = creators.get(handle)
            if not isinstance(candidate, dict):
                continue
            rank = candidate.get("rank")
            if rank is not None:
                try:
                    historical_ranks.append(int(rank))
                except (TypeError, ValueError):
                    pass

        row["ath_rank"] = min(historical_ranks) if historical_ranks else None
        output["creators"][handle] = row

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output

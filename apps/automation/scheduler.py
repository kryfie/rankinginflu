from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SEEDS_PATH = REPO_ROOT / "apps" / "discovery" / "seeds.json"
STATE_PATH = REPO_ROOT / "database" / "data" / "seed_state.json"
DISCOVERY_RAW_PATH = REPO_ROOT / "apps" / "web" / "data" / "discovery_raw.json"
REGISTRY_PATH = REPO_ROOT / "apps" / "web" / "data" / "discovery_candidates.json"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


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


def load_seeds() -> list[str]:
    payload = _load(SEEDS_PATH, {"keywords": []})
    if isinstance(payload, dict):
        rows = payload.get("keywords", [])
    else:
        rows = payload
    return [str(row).strip() for row in rows if str(row).strip()]


def _blank_seed(index: int, seed: str) -> dict[str, Any]:
    return {
        "index": index,
        "seed": seed,
        "status": "never",
        "attempts": 0,
        "successful_scans": 0,
        "demo_only_count": 0,
        "provider_error_count": 0,
        "accepted_total": 0,
        "new_creators_total": 0,
        "last_run_at": None,
        "last_successful_at": None,
        "next_due_at": None,
        "last_status": None,
        "last_accepted": 0,
        "last_new_creators": 0,
        "last_new_rate": None,
    }


def load_state() -> dict[str, Any]:
    seeds = load_seeds()
    loaded = _load(STATE_PATH, {})

    existing_by_name: dict[str, dict[str, Any]] = {}
    if isinstance(loaded, dict):
        rows = loaded.get("seeds", [])
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and row.get("seed"):
                    existing_by_name[str(row["seed"]).lower()] = dict(row)

    rows = []
    for index, seed in enumerate(seeds):
        row = _blank_seed(index, seed)
        old = existing_by_name.get(seed.lower())
        if old:
            row.update(old)
        row["index"] = index
        row["seed"] = seed
        rows.append(row)

    state = {
        "version": 2,
        "updated_at": loaded.get("updated_at") if isinstance(loaded, dict) else None,
        "bootstrap_target": int(
            (loaded.get("bootstrap_target", 250) if isinstance(loaded, dict) else 250)
        ),
        "results_per_seed": int(
            (loaded.get("results_per_seed", 20) if isinstance(loaded, dict) else 20)
        ),
        "max_queries_per_run": int(
            (loaded.get("max_queries_per_run", 25) if isinstance(loaded, dict) else 25)
        ),
        "seeds": rows,
    }
    return state


def _eligible_registry_count() -> int:
    payload = _load(REGISTRY_PATH, {})
    if not isinstance(payload, dict):
        return 0

    meta = payload.get("meta", {})
    if isinstance(meta, dict) and meta.get("eligible_count") is not None:
        try:
            return int(meta["eligible_count"])
        except Exception:
            pass

    rows = payload.get("creators", [])
    if not isinstance(rows, list):
        return 0

    return sum(
        1 for row in rows
        if isinstance(row, dict)
        and row.get("discovery_eligible", True) is not False
    )


def _is_due(row: dict[str, Any], now: datetime) -> bool:
    due = _parse_dt(row.get("next_due_at"))
    return due is None or due <= now


def _priority(row: dict[str, Any], now: datetime, bootstrap: bool) -> tuple:
    status = str(row.get("status") or "never")

    # After upgrading, first retry seeds that were blocked by Free-plan
    # demo mode. Then scan genuinely new seeds. Only after that revisit due
    # historical seeds.
    if status == "retry_after_upgrade":
        class_rank = 0
    elif status == "never":
        class_rank = 1
    elif _is_due(row, now):
        class_rank = 2
    else:
        class_rank = 3

    # In steady state, among due seeds prefer those that historically found
    # more new creators per successful scan.
    successful = max(1, int(row.get("successful_scans") or 0))
    historical_yield = float(row.get("new_creators_total") or 0) / successful

    due = _parse_dt(row.get("next_due_at"))
    due_ts = due.timestamp() if due else 0.0

    return (
        class_rank,
        -historical_yield,
        due_ts,
        int(row.get("index") or 0),
    )


def plan(mode: str, max_seeds: int, bootstrap_target: int) -> dict[str, Any]:
    # Cost guard: even a manual typo cannot schedule more than 50 provider
    # search queries in one autopilot run.
    max_seeds = min(max(0, int(max_seeds)), 50)
    state = load_state()
    now = utcnow()
    eligible_count = _eligible_registry_count()

    if mode == "auto":
        effective_mode = (
            "bootstrap"
            if eligible_count < bootstrap_target
            else "steady"
        )
    else:
        effective_mode = mode

    rows = state["seeds"]

    if effective_mode == "bootstrap":
        candidates = [
            row for row in rows
            if row.get("status") in {"never", "retry_after_upgrade"}
            or _is_due(row, now)
        ]
    else:
        candidates = [
            row for row in rows
            if _is_due(row, now)
            and row.get("status") != "provider_blocked"
        ]

    candidates.sort(
        key=lambda row: _priority(
            row,
            now,
            bootstrap=(effective_mode == "bootstrap"),
        )
    )

    selected = candidates[:max(0, max_seeds)]

    return {
        "requested_mode": mode,
        "effective_mode": effective_mode,
        "eligible_registry_count": eligible_count,
        "bootstrap_target": bootstrap_target,
        "selected_indices": [int(row["index"]) for row in selected],
        "selected_seeds": [row["seed"] for row in selected],
        "selected_count": len(selected),
        "query_cap": 50,
    }


def _cooldown_days(status: str, new_rate: float, new_count: int) -> int:
    if status == "demo_only":
        # Likely plan/provider access issue. Retry soon after plan changes.
        return 1

    if status == "no_usable_rows":
        return 60

    if status == "productive":
        if new_count >= 5 or new_rate >= 0.50:
            return 14
        if new_count >= 2 or new_rate >= 0.20:
            return 30
        if new_count >= 1:
            return 60
        return 90

    return 7


def record(planned_indices: list[int]) -> dict[str, Any]:
    state = load_state()
    now = utcnow()
    raw = _load(DISCOVERY_RAW_PATH, {})
    meta = raw.get("meta", {}) if isinstance(raw, dict) else {}

    per_seed = meta.get("per_seed", [])
    if not isinstance(per_seed, list):
        per_seed = []

    errors = meta.get("errors", [])
    if not isinstance(errors, list):
        errors = []

    by_name = {
        str(row.get("seed")): row
        for row in per_seed
        if isinstance(row, dict) and row.get("seed")
    }
    error_by_name = {
        str(row.get("seed")): row
        for row in errors
        if isinstance(row, dict) and row.get("seed")
    }

    rows = state["seeds"]

    for index in planned_indices:
        if index < 0 or index >= len(rows):
            continue

        row = rows[index]
        seed = row["seed"]
        result = by_name.get(seed)

        # A provider error may have stopped the discovery loop before this seed.
        if result is None:
            err = error_by_name.get(seed)
            if err:
                row["attempts"] = int(row.get("attempts") or 0) + 1
                row["provider_error_count"] = int(
                    row.get("provider_error_count") or 0
                ) + 1
                row["status"] = "provider_error"
                row["last_status"] = "provider_error"
                row["last_run_at"] = _iso(now)
                row["next_due_at"] = _iso(now + timedelta(days=1))
            continue

        status = str(result.get("status") or "unknown")
        accepted = int(result.get("accepted_candidates") or 0)
        new_count = int(result.get("new_candidates") or 0)
        new_rate = (
            float(new_count) / accepted
            if accepted > 0
            else 0.0
        )

        row["attempts"] = int(row.get("attempts") or 0) + 1
        row["last_run_at"] = _iso(now)
        row["last_status"] = status
        row["last_accepted"] = accepted
        row["last_new_creators"] = new_count
        row["last_new_rate"] = round(new_rate, 4)

        if status == "demo_only":
            row["demo_only_count"] = int(
                row.get("demo_only_count") or 0
            ) + 1
            row["status"] = "provider_blocked"
            row["next_due_at"] = _iso(now + timedelta(days=1))
            # Deliberately DO NOT increment successful_scans.
            continue

        row["successful_scans"] = int(
            row.get("successful_scans") or 0
        ) + 1
        row["accepted_total"] = int(
            row.get("accepted_total") or 0
        ) + accepted
        row["new_creators_total"] = int(
            row.get("new_creators_total") or 0
        ) + new_count
        row["last_successful_at"] = _iso(now)
        row["status"] = status

        cooldown = _cooldown_days(
            status,
            new_rate,
            new_count,
        )
        row["next_due_at"] = _iso(
            now + timedelta(days=cooldown)
        )

    state["updated_at"] = _iso(now)
    _write(STATE_PATH, state)

    return {
        "updated_at": state["updated_at"],
        "planned_indices": planned_indices,
        "provider_blocked": sum(
            1 for row in rows
            if row.get("status") == "provider_blocked"
        ),
        "never_scanned": sum(
            1 for row in rows
            if row.get("status") in {"never", "retry_after_upgrade"}
        ),
    }


def print_plan(plan_data: dict[str, Any]) -> None:
    print(f"MODE={plan_data['effective_mode']}")
    print(
        "SELECTED_INDICES="
        + ",".join(str(i) for i in plan_data["selected_indices"])
    )
    print(f"SELECTED_COUNT={plan_data['selected_count']}")
    print(f"QUERY_CAP={plan_data['query_cap']}")
    print(
        "SELECTED_SEEDS="
        + " | ".join(plan_data["selected_seeds"])
    )
    print(
        f"ELIGIBLE_REGISTRY_COUNT={plan_data['eligible_registry_count']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="influrank-scheduler")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("plan")
    p.add_argument(
        "--mode",
        choices=["auto", "bootstrap", "steady"],
        default="auto",
    )
    p.add_argument("--max-seeds", type=int, default=25)
    p.add_argument("--bootstrap-target", type=int, default=250)

    r = sub.add_parser("record")
    r.add_argument(
        "--planned-indices",
        default="",
        help="Comma-separated indices from the plan step.",
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.command == "plan":
        data = plan(
            args.mode,
            args.max_seeds,
            args.bootstrap_target,
        )
        print_plan(data)
        return 0

    if args.command == "record":
        indices = [
            int(value)
            for value in str(args.planned_indices).split(",")
            if value.strip()
        ]
        result = record(indices)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

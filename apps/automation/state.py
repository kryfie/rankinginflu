from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = REPO_ROOT / "database" / "data" / "pipeline_state.json"
SEEDS_PATH = REPO_ROOT / "apps" / "discovery" / "seeds.json"
DISCOVERY_RAW_PATH = REPO_ROOT / "apps" / "web" / "data" / "discovery_raw.json"


DEFAULT_STATE = {
    "version": 1,
    "next_seed": 0,
    "batch_size": 2,
    "cycle_count": 0,
    "total_seeds_completed": 0,
    "last_run_at": None,
    "last_start_seed": None,
    "last_completed_seeds": [],
}


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


def _seed_count() -> int:
    payload = _load(SEEDS_PATH, [])
    if isinstance(payload, dict):
        rows = payload.get("keywords", [])
    else:
        rows = payload
    return len(rows) if isinstance(rows, list) else 0


def current() -> dict[str, Any]:
    state = dict(DEFAULT_STATE)
    loaded = _load(STATE_PATH, {})
    if isinstance(loaded, dict):
        state.update(loaded)

    count = _seed_count()
    if count > 0:
        state["next_seed"] = int(state.get("next_seed", 0)) % count

    return state


def advance_from_latest_discovery() -> dict[str, Any]:
    """
    Advance only by seeds actually completed by the latest discovery run.

    If the provider errors after the first seed, the failed seed becomes the
    next one for tomorrow instead of being silently skipped.
    """
    state = current()
    discovery = _load(DISCOVERY_RAW_PATH, {})
    meta = discovery.get("meta", {}) if isinstance(discovery, dict) else {}

    completed = meta.get("seeds_completed", [])
    if not isinstance(completed, list):
        completed = []

    try:
        start_seed = int(meta.get("startSeed", state["next_seed"]))
    except (TypeError, ValueError):
        start_seed = int(state["next_seed"])

    seed_count = _seed_count()
    completed_count = len(completed)

    old_cycle = int(state.get("cycle_count", 0))
    new_cycle = old_cycle

    if seed_count > 0 and completed_count > 0:
        raw_next = start_seed + completed_count
        if raw_next >= seed_count:
            new_cycle += raw_next // seed_count
        next_seed = raw_next % seed_count
    else:
        next_seed = start_seed % seed_count if seed_count else 0

    state.update(
        {
            "version": 1,
            "next_seed": next_seed,
            "cycle_count": new_cycle,
            "total_seeds_completed": int(
                state.get("total_seeds_completed", 0)
            ) + completed_count,
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "last_start_seed": start_seed,
            "last_completed_seeds": completed,
        }
    )

    _write(STATE_PATH, state)
    return state


def show_shell() -> int:
    state = current()
    print(f"START_SEED={int(state['next_seed'])}")
    print(f"BATCH_SIZE={int(state.get('batch_size', 2))}")
    print(f"CYCLE_COUNT={int(state.get('cycle_count', 0))}")
    return 0


def advance_command() -> int:
    state = advance_from_latest_discovery()
    print(
        "Autopilot state advanced: "
        f"next_seed={state['next_seed']} "
        f"cycle={state['cycle_count']} "
        f"completed={state['last_completed_seeds']}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="influrank-automation-state")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show-shell")
    sub.add_parser("advance")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "show-shell":
        return show_shell()
    if args.command == "advance":
        return advance_command()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    apify_token: str
    actor_id: str = "apidojo~tiktok-scraper-api"
    location: str = "PL"
    date_range: str = "LAST_THREE_MONTHS"
    sort_type: str = "RELEVANCE"
    min_followers: int = 10_000
    min_pl_signals: int = 1
    results_per_seed: int = 10
    max_seeds: int = 1
    timeout_seconds: int = 180

    registry_path: Path = REPO_ROOT / "apps" / "web" / "data" / "discovery_candidates.json"
    queue_path: Path = REPO_ROOT / "apps" / "web" / "data" / "scanner_queue.json"
    compact_raw_path: Path = REPO_ROOT / "apps" / "web" / "data" / "discovery_raw.json"
    full_raw_path: Path = REPO_ROOT / "apps" / "discovery" / "data" / "discovery_raw_full.json"

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("APIFY_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "Missing APIFY_TOKEN. Add it as a GitHub Actions secret or local environment variable."
            )

        return cls(
            apify_token=token,
            actor_id=os.getenv("APIFY_DISCOVERY_ACTOR", "apidojo~tiktok-scraper-api").strip(),
            location=os.getenv("DISCOVERY_LOCATION", "PL").strip().upper(),
            date_range=os.getenv("DISCOVERY_DATE_RANGE", "LAST_THREE_MONTHS").strip(),
            sort_type=os.getenv("DISCOVERY_SORT_TYPE", "RELEVANCE").strip(),
            min_followers=int(os.getenv("DISCOVERY_MIN_FOLLOWERS", "10000")),
            min_pl_signals=int(os.getenv("DISCOVERY_MIN_PL_SIGNALS", "1")),
            results_per_seed=int(os.getenv("DISCOVERY_RESULTS_PER_SEED", "10")),
            max_seeds=int(os.getenv("DISCOVERY_MAX_SEEDS", "1")),
            timeout_seconds=int(os.getenv("DISCOVERY_TIMEOUT_SECONDS", "180")),
        )

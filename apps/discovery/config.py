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
    max_items: int = 1_000
    timeout_seconds: int = 180
    output_candidates: Path = REPO_ROOT / "apps" / "web" / "data" / "discovery_candidates.json"
    output_queue: Path = REPO_ROOT / "apps" / "web" / "data" / "scanner_queue.json"
    output_raw: Path = REPO_ROOT / "apps" / "web" / "data" / "discovery_raw.json"

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("APIFY_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "Missing APIFY_TOKEN. Set it locally or add it as a GitHub Actions secret."
            )

        return cls(
            apify_token=token,
            actor_id=os.getenv("APIFY_DISCOVERY_ACTOR", "apidojo~tiktok-scraper-api").strip(),
            location=os.getenv("DISCOVERY_LOCATION", "PL").strip().upper(),
            date_range=os.getenv("DISCOVERY_DATE_RANGE", "LAST_THREE_MONTHS").strip(),
            sort_type=os.getenv("DISCOVERY_SORT_TYPE", "RELEVANCE").strip(),
            min_followers=int(os.getenv("DISCOVERY_MIN_FOLLOWERS", "10000")),
            max_items=int(os.getenv("DISCOVERY_MAX_ITEMS", "1000")),
            timeout_seconds=int(os.getenv("DISCOVERY_TIMEOUT_SECONDS", "180")),
        )

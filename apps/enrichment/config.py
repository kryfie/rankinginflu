from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    apify_token: str
    actor_id: str = "simple.actor~tiktok-profile-posts"
    timeout_seconds: int = 3600

    queue_path: Path = REPO_ROOT / "apps" / "web" / "data" / "scanner_queue.json"
    web_ranking_path: Path = REPO_ROOT / "apps" / "web" / "data" / "creators.json"

    creators_path: Path = REPO_ROOT / "database" / "data" / "enriched_creators.json"
    posts_path: Path = REPO_ROOT / "database" / "data" / "posts.json"
    snapshots_path: Path = REPO_ROOT / "database" / "data" / "creator_snapshots.json"

    raw_path: Path = REPO_ROOT / "apps" / "enrichment" / "data" / "enrichment_raw_full.json"

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("APIFY_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "Missing APIFY_TOKEN. Add it as a GitHub Actions repository secret."
            )

        return cls(
            apify_token=token,
            actor_id=os.getenv(
                "APIFY_PROFILE_ACTOR",
                "simple.actor~tiktok-profile-posts",
            ).strip(),
            timeout_seconds=int(os.getenv("ENRICHMENT_TIMEOUT_SECONDS", "3600")),
        )

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Candidate:
    tiktok_id: str
    username: str
    display_name: str
    profile_url: str
    avatar_url: str | None
    followers: int
    provider_verified: bool | None
    found_by: list[str]
    posts_seen: int
    max_views_seen: int
    max_likes_seen: int
    latest_post_at: str | None
    polish_signal_count: int
    polish_signals: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

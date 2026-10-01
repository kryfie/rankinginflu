from __future__ import annotations

from typing import Any

import requests


class ApifyEnrichmentError(RuntimeError):
    pass


def run_profile_actor(
    *,
    token: str,
    actor_id: str,
    handles: list[str],
    max_posts: int = 13,
    timeout_seconds: int = 600,
) -> list[dict[str, Any]]:
    """
    Batch-read public TikTok profiles and their latest public posts.

    The configured Actor accepts `handles` and returns one dataset row per post.
    Profile data is repeated inside each row's `author` object.
    """
    if not handles:
        return []

    actor_id = actor_id.replace("/", "~")
    url = f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"

    actor_input = {
        "handles": [h.lstrip("@") for h in handles],
        "maxPosts": max(1, min(int(max_posts), 13)),
        "includePostDetails": True,
        "includeProfileDetails": True,
    }

    response = requests.post(
        url,
        params={
            "token": token,
            "format": "json",
            "clean": "true",
        },
        json=actor_input,
        timeout=timeout_seconds,
    )

    if not response.ok:
        raise ApifyEnrichmentError(
            f"Profile Actor failed: HTTP {response.status_code}\n"
            f"{response.text[:1800]}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise ApifyEnrichmentError(
            f"Profile Actor returned non-JSON data: {response.text[:1000]}"
        ) from exc

    if not isinstance(payload, list):
        raise ApifyEnrichmentError(
            f"Expected a JSON list, got {type(payload).__name__}."
        )

    return [row for row in payload if isinstance(row, dict)]

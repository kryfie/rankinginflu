from __future__ import annotations

from typing import Any

import requests


class ApifyError(RuntimeError):
    pass


def run_actor_sync(
    *,
    token: str,
    actor_id: str,
    actor_input: dict[str, Any],
    timeout_seconds: int = 180,
) -> list[dict[str, Any]]:
    """
    Run one Apify Actor invocation synchronously and return default dataset items.

    We intentionally call the actor once per discovery seed. This makes
    `results_per_seed` a real per-seed limit instead of a global limit shared
    by all keywords.
    """
    actor_id = actor_id.replace("/", "~")
    url = f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"

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
        body = response.text[:1600]
        raise ApifyError(
            f"Apify request failed: HTTP {response.status_code}\n{body}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise ApifyError(
            f"Apify returned non-JSON data: {response.text[:1000]}"
        ) from exc

    if not isinstance(payload, list):
        raise ApifyError(
            f"Expected dataset items as a JSON list, got {type(payload).__name__}."
        )

    return [item for item in payload if isinstance(item, dict)]

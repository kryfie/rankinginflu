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
    Runs an Apify Actor synchronously and returns its default dataset items.

    Actor IDs in the HTTP endpoint use '~' instead of '/'.
    """
    actor_id = actor_id.replace("/", "~")
    url = (
        f"https://api.apify.com/v2/acts/{actor_id}/"
        f"run-sync-get-dataset-items"
    )

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
        body = response.text[:1500]
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

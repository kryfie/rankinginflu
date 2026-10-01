from __future__ import annotations

import time
from typing import Any

import requests


class ApifyEnrichmentError(RuntimeError):
    pass


TERMINAL_STATUSES = {
    "SUCCEEDED",
    "FAILED",
    "TIMED-OUT",
    "ABORTED",
}


def _api_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _start_run(
    *,
    token: str,
    actor_id: str,
    handles: list[str],
    max_posts: int,
    request_timeout_seconds: int = 60,
) -> dict[str, Any]:
    actor_id = actor_id.replace("/", "~")
    url = f"https://api.apify.com/v2/actors/{actor_id}/runs"

    actor_input = {
        "handles": [h.lstrip("@") for h in handles],
        "maxPosts": max(1, min(int(max_posts), 13)),
        "includePostDetails": True,
        "includeProfileDetails": True,
    }

    response = requests.post(
        url,
        headers=_api_headers(token),
        json=actor_input,
        timeout=request_timeout_seconds,
    )

    if not response.ok:
        raise ApifyEnrichmentError(
            f"Could not start profile Actor: HTTP {response.status_code}\n"
            f"{response.text[:1800]}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise ApifyEnrichmentError(
            f"Start-run endpoint returned non-JSON data: {response.text[:1000]}"
        ) from exc

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not data.get("id"):
        raise ApifyEnrichmentError(
            f"Unexpected Actor start response: {str(payload)[:1800]}"
        )

    return data


def _wait_for_run(
    *,
    token: str,
    run_id: str,
    overall_timeout_seconds: int,
    poll_seconds: int = 10,
) -> dict[str, Any]:
    url = f"https://api.apify.com/v2/actor-runs/{run_id}"
    deadline = time.monotonic() + overall_timeout_seconds

    while True:
        if time.monotonic() >= deadline:
            raise ApifyEnrichmentError(
                f"Profile Actor run {run_id} exceeded "
                f"{overall_timeout_seconds}s timeout."
            )

        response = requests.get(
            url,
            headers=_api_headers(token),
            timeout=60,
        )

        if not response.ok:
            raise ApifyEnrichmentError(
                f"Could not read profile Actor run {run_id}: "
                f"HTTP {response.status_code}\n{response.text[:1000]}"
            )

        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise ApifyEnrichmentError(
                f"Unexpected run-status response for {run_id}."
            )

        status = str(data.get("status") or "")
        if status in TERMINAL_STATUSES:
            return data

        time.sleep(poll_seconds)


def _fetch_run_items(
    *,
    token: str,
    run_id: str,
) -> list[dict[str, Any]]:
    url = f"https://api.apify.com/v2/actor-runs/{run_id}/dataset/items"
    response = requests.get(
        url,
        headers=_api_headers(token),
        params={
            "clean": "true",
            "format": "json",
        },
        timeout=120,
    )

    if not response.ok:
        raise ApifyEnrichmentError(
            f"Could not fetch dataset for run {run_id}: "
            f"HTTP {response.status_code}\n{response.text[:1000]}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise ApifyEnrichmentError(
            f"Dataset endpoint returned non-JSON data for run {run_id}."
        ) from exc

    if not isinstance(payload, list):
        raise ApifyEnrichmentError(
            f"Expected dataset list for run {run_id}, "
            f"got {type(payload).__name__}."
        )

    return [row for row in payload if isinstance(row, dict)]


def _batch_error_rows(
    handles: list[str],
    message: str,
) -> list[dict[str, Any]]:
    return [
        {
            "username": handle.lstrip("@"),
            "error": "batch_failed",
            "errorDescription": message,
        }
        for handle in handles
    ]


def run_profile_actor(
    *,
    token: str,
    actor_id: str,
    handles: list[str],
    max_posts: int = 13,
    timeout_seconds: int = 3600,
    batch_size: int = 50,
) -> list[dict[str, Any]]:
    """
    Read public TikTok profiles/posts in durable asynchronous Actor runs.

    Why async?
    The Apify synchronous endpoint keeps one HTTP request open until the Actor
    finishes. Large batches can take long enough for an intermediary/server to
    close that connection even though the Actor itself is fine.

    We instead:
      1. start the Actor quickly,
      2. poll the run status,
      3. fetch the finished dataset.

    The Actor's own docs recommend batching around fifty handles. If one batch
    fails, other successful batches are preserved and failed handles are
    returned as synthetic error rows so enrichment can commit partial progress.
    """
    clean_handles = []
    seen = set()

    for handle in handles:
        value = str(handle or "").strip().lstrip("@")
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            clean_handles.append(value)

    if not clean_handles:
        return []

    batch_size = max(1, min(int(batch_size), 50))
    all_rows: list[dict[str, Any]] = []

    for offset in range(0, len(clean_handles), batch_size):
        batch = clean_handles[offset: offset + batch_size]
        batch_no = (offset // batch_size) + 1
        total_batches = (len(clean_handles) + batch_size - 1) // batch_size

        print(
            f"Profile Actor batch {batch_no}/{total_batches}: "
            f"{len(batch)} handles",
            flush=True,
        )

        try:
            started = _start_run(
                token=token,
                actor_id=actor_id,
                handles=batch,
                max_posts=max_posts,
            )
            run_id = str(started["id"])
            print(f"  started run {run_id}", flush=True)

            finished = _wait_for_run(
                token=token,
                run_id=run_id,
                overall_timeout_seconds=timeout_seconds,
            )
            status = str(finished.get("status") or "")

            if status != "SUCCEEDED":
                message = (
                    f"Actor run {run_id} ended with status={status}. "
                    f"statusMessage={finished.get('statusMessage')}"
                )
                print(f"  WARNING: {message}", flush=True)
                all_rows.extend(_batch_error_rows(batch, message))
                continue

            rows = _fetch_run_items(
                token=token,
                run_id=run_id,
            )
            print(
                f"  succeeded: dataset rows={len(rows)}",
                flush=True,
            )
            all_rows.extend(rows)

        except (requests.RequestException, ApifyEnrichmentError) as exc:
            message = f"{type(exc).__name__}: {exc}"
            print(
                f"  WARNING: batch failed but pipeline will keep "
                f"other batches: {message}",
                flush=True,
            )
            all_rows.extend(_batch_error_rows(batch, message))

    return all_rows

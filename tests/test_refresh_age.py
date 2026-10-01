from datetime import datetime, timezone

from apps.enrichment.pipeline import select_queue_items


NOW = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)


def test_accepts_new_cli_keyword_for_normal_run():
    q = {
        "items": [
            {"username": "new", "priority": 1, "status": "pending_profile_scan"},
            {"username": "old", "priority": 2, "status": "enriched"},
        ]
    }
    selected = select_queue_items(
        q,
        max_profiles=100,
        refresh_all=False,
        min_refresh_age_hours=0,
        now=NOW,
    )
    assert [row["username"] for row in selected] == ["new"]


def test_seven_day_refresh_only_selects_due_enriched_profiles():
    q = {
        "items": [
            {
                "username": "fresh",
                "priority": 1,
                "status": "enriched",
                "last_profile_scan_at": "2026-09-30T15:00:00+00:00",
            },
            {
                "username": "due",
                "priority": 2,
                "status": "enriched",
                "last_profile_scan_at": "2026-09-24T14:59:59+00:00",
            },
            {
                "username": "pending",
                "priority": 3,
                "status": "pending_profile_scan",
            },
            {
                "username": "error",
                "priority": 4,
                "status": "enrichment_error",
                "last_profile_scan_at": "2026-09-20T00:00:00+00:00",
            },
        ]
    }
    selected = select_queue_items(
        q,
        max_profiles=100,
        refresh_all=True,
        min_refresh_age_hours=168,
        now=NOW,
    )
    assert [row["username"] for row in selected] == ["due"]


def test_enriched_without_timestamp_is_refreshable_once():
    q = {
        "items": [
            {"username": "legacy", "priority": 1, "status": "enriched"},
        ]
    }
    selected = select_queue_items(
        q,
        max_profiles=100,
        refresh_all=True,
        min_refresh_age_hours=168,
        now=NOW,
    )
    assert [row["username"] for row in selected] == ["legacy"]

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import apps.automation.scheduler as scheduler
from apps.enrichment.pipeline import select_queue_items


class AutomationV2Tests(unittest.TestCase):
    def test_refresh_all_uses_oldest_first_and_age_guard(self):
        now = datetime.now(timezone.utc)
        queue = {
            "items": [
                {
                    "username": "fresh",
                    "priority": 1,
                    "status": "enriched",
                    "last_profile_scan_at": (
                        now - timedelta(hours=24)
                    ).isoformat(),
                },
                {
                    "username": "never",
                    "priority": 3,
                    "status": "enriched",
                },
                {
                    "username": "old",
                    "priority": 2,
                    "status": "enriched",
                    "last_profile_scan_at": (
                        now - timedelta(days=10)
                    ).isoformat(),
                },
            ]
        }

        selected = select_queue_items(
            queue,
            max_profiles=10,
            refresh_all=True,
            min_refresh_age_hours=168,
        )

        self.assertEqual(
            [row["username"] for row in selected],
            ["never", "old"],
        )

    def test_bootstrap_prioritizes_never_scanned(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            seeds_path = root / "seeds.json"
            state_path = root / "seed_state.json"
            registry_path = root / "registry.json"

            seeds_path.write_text(
                json.dumps(
                    {"keywords": ["done", "new1", "new2"]}
                ),
                encoding="utf-8",
            )
            state_path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "seeds": [
                            {
                                "index": 0,
                                "seed": "done",
                                "status": "productive",
                                "successful_scans": 1,
                                "new_creators_total": 3,
                                "next_due_at": "2099-01-01T00:00:00+00:00",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            registry_path.write_text(
                json.dumps({"meta": {"eligible_count": 10}}),
                encoding="utf-8",
            )

            with (
                patch.object(scheduler, "SEEDS_PATH", seeds_path),
                patch.object(scheduler, "STATE_PATH", state_path),
                patch.object(scheduler, "REGISTRY_PATH", registry_path),
            ):
                result = scheduler.plan(
                    mode="auto",
                    max_seeds=2,
                    bootstrap_target=250,
                )

            self.assertEqual(result["effective_mode"], "bootstrap")
            self.assertEqual(result["selected_indices"], [1, 2])

    def test_demo_only_does_not_become_successful_scan(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            seeds_path = root / "seeds.json"
            state_path = root / "seed_state.json"
            raw_path = root / "raw.json"

            seeds_path.write_text(
                json.dumps({"keywords": ["beauty"]}),
                encoding="utf-8",
            )
            state_path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "seeds": [
                            {
                                "index": 0,
                                "seed": "beauty",
                                "status": "retry_after_upgrade",
                                "attempts": 1,
                                "successful_scans": 0,
                                "demo_only_count": 1,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            raw_path.write_text(
                json.dumps(
                    {
                        "meta": {
                            "per_seed": [
                                {
                                    "seed": "beauty",
                                    "status": "demo_only",
                                    "accepted_candidates": 0,
                                    "new_candidates": 0,
                                }
                            ],
                            "errors": [],
                        }
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.object(scheduler, "SEEDS_PATH", seeds_path),
                patch.object(scheduler, "STATE_PATH", state_path),
                patch.object(scheduler, "DISCOVERY_RAW_PATH", raw_path),
            ):
                scheduler.record([0])
                state = json.loads(state_path.read_text(encoding="utf-8"))

            row = state["seeds"][0]
            self.assertEqual(row["successful_scans"], 0)
            self.assertEqual(row["status"], "provider_blocked")
            self.assertEqual(row["demo_only_count"], 2)

    def test_high_yield_seed_gets_shorter_cooldown(self):
        self.assertLess(
            scheduler._cooldown_days(
                "productive",
                new_rate=0.60,
                new_count=6,
            ),
            scheduler._cooldown_days(
                "productive",
                new_rate=0.0,
                new_count=0,
            ),
        )


    def test_retry_after_upgrade_is_first(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            seeds_path = root / "seeds.json"
            state_path = root / "seed_state.json"
            registry_path = root / "registry.json"

            seeds_path.write_text(
                json.dumps(
                    {"keywords": ["done", "new", "blocked"]}
                ),
                encoding="utf-8",
            )
            state_path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "seeds": [
                            {
                                "index": 0,
                                "seed": "done",
                                "status": "productive",
                                "next_due_at": "2099-01-01T00:00:00+00:00",
                            },
                            {
                                "index": 2,
                                "seed": "blocked",
                                "status": "retry_after_upgrade",
                                "next_due_at": "2026-10-01T00:00:00+00:00",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            registry_path.write_text(
                json.dumps({"meta": {"eligible_count": 10}}),
                encoding="utf-8",
            )

            with (
                patch.object(scheduler, "SEEDS_PATH", seeds_path),
                patch.object(scheduler, "STATE_PATH", state_path),
                patch.object(scheduler, "REGISTRY_PATH", registry_path),
            ):
                result = scheduler.plan(
                    mode="bootstrap",
                    max_seeds=2,
                    bootstrap_target=250,
                )

            self.assertEqual(result["selected_indices"], [2, 1])

    def test_discovery_query_hard_cap(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            seeds_path = root / "seeds.json"
            state_path = root / "seed_state.json"
            registry_path = root / "registry.json"

            seeds_path.write_text(
                json.dumps(
                    {"keywords": [f"s{i}" for i in range(100)]}
                ),
                encoding="utf-8",
            )
            state_path.write_text(
                json.dumps({"version": 2, "seeds": []}),
                encoding="utf-8",
            )
            registry_path.write_text(
                json.dumps({"meta": {"eligible_count": 0}}),
                encoding="utf-8",
            )

            with (
                patch.object(scheduler, "SEEDS_PATH", seeds_path),
                patch.object(scheduler, "STATE_PATH", state_path),
                patch.object(scheduler, "REGISTRY_PATH", registry_path),
            ):
                result = scheduler.plan(
                    mode="bootstrap",
                    max_seeds=999,
                    bootstrap_target=250,
                )

            self.assertEqual(result["selected_count"], 50)
            self.assertEqual(result["query_cap"], 50)


if __name__ == "__main__":
    unittest.main()

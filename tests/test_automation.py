import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import apps.automation.state as state_module
from apps.enrichment.pipeline import select_queue_items


class AutomationTests(unittest.TestCase):
    def test_refresh_all_uses_oldest_first(self):
        queue = {
            "items": [
                {
                    "username": "newer",
                    "priority": 1,
                    "status": "enriched",
                    "last_profile_scan_at": "2026-10-01T00:00:00Z",
                },
                {
                    "username": "never",
                    "priority": 3,
                    "status": "enriched",
                },
                {
                    "username": "older",
                    "priority": 2,
                    "status": "enriched",
                    "last_profile_scan_at": "2026-09-01T00:00:00Z",
                },
            ]
        }

        selected = select_queue_items(
            queue,
            max_profiles=2,
            refresh_all=True,
        )

        self.assertEqual(
            [row["username"] for row in selected],
            ["never", "older"],
        )

    def test_cursor_wraps_after_last_seed(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            state_path = root / "pipeline_state.json"
            seeds_path = root / "seeds.json"
            raw_path = root / "discovery_raw.json"

            state_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "next_seed": 14,
                        "batch_size": 2,
                        "cycle_count": 0,
                        "total_seeds_completed": 14,
                    }
                ),
                encoding="utf-8",
            )
            seeds_path.write_text(
                json.dumps({"keywords": [f"s{i}" for i in range(15)]}),
                encoding="utf-8",
            )
            raw_path.write_text(
                json.dumps(
                    {
                        "meta": {
                            "startSeed": 14,
                            "seeds_completed": ["s14"],
                        }
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.object(state_module, "STATE_PATH", state_path),
                patch.object(state_module, "SEEDS_PATH", seeds_path),
                patch.object(state_module, "DISCOVERY_RAW_PATH", raw_path),
            ):
                result = state_module.advance_from_latest_discovery()

            self.assertEqual(result["next_seed"], 0)
            self.assertEqual(result["cycle_count"], 1)
            self.assertEqual(result["total_seeds_completed"], 15)

    def test_failed_second_seed_is_retried_next_time(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            state_path = root / "pipeline_state.json"
            seeds_path = root / "seeds.json"
            raw_path = root / "discovery_raw.json"

            state_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "next_seed": 5,
                        "batch_size": 2,
                        "cycle_count": 0,
                        "total_seeds_completed": 5,
                    }
                ),
                encoding="utf-8",
            )
            seeds_path.write_text(
                json.dumps({"keywords": [f"s{i}" for i in range(15)]}),
                encoding="utf-8",
            )
            raw_path.write_text(
                json.dumps(
                    {
                        "meta": {
                            "startSeed": 5,
                            "seeds_completed": ["s5"],
                            "errors": [{"seed": "s6", "error": "provider error"}],
                        }
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.object(state_module, "STATE_PATH", state_path),
                patch.object(state_module, "SEEDS_PATH", seeds_path),
                patch.object(state_module, "DISCOVERY_RAW_PATH", raw_path),
            ):
                result = state_module.advance_from_latest_discovery()

            self.assertEqual(result["next_seed"], 6)
            self.assertEqual(result["total_seeds_completed"], 6)


if __name__ == "__main__":
    unittest.main()

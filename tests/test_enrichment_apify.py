import unittest
from unittest.mock import patch

from apps.enrichment.apify_client import run_profile_actor


class ApifyClientTests(unittest.TestCase):
    def test_splits_100_handles_into_two_50_batches(self):
        handles = [f"user{i}" for i in range(100)]
        starts = []

        def fake_start(**kwargs):
            starts.append(list(kwargs["handles"]))
            return {"id": f"run{len(starts)}"}

        def fake_wait(**kwargs):
            return {"status": "SUCCEEDED"}

        def fake_fetch(**kwargs):
            return [
                {
                    "ownerUsername": kwargs["run_id"],
                    "id": kwargs["run_id"],
                }
            ]

        with (
            patch("apps.enrichment.apify_client._start_run", side_effect=fake_start),
            patch("apps.enrichment.apify_client._wait_for_run", side_effect=fake_wait),
            patch("apps.enrichment.apify_client._fetch_run_items", side_effect=fake_fetch),
        ):
            rows = run_profile_actor(
                token="token",
                actor_id="simple.actor~tiktok-profile-posts",
                handles=handles,
                max_posts=13,
                batch_size=50,
            )

        self.assertEqual(len(starts), 2)
        self.assertEqual(len(starts[0]), 50)
        self.assertEqual(len(starts[1]), 50)
        self.assertEqual(len(rows), 2)

    def test_failed_batch_does_not_discard_other_batch(self):
        handles = [f"user{i}" for i in range(60)]
        counter = {"starts": 0}

        def fake_start(**kwargs):
            counter["starts"] += 1
            return {"id": f"run{counter['starts']}"}

        def fake_wait(**kwargs):
            if kwargs["run_id"] == "run1":
                return {
                    "status": "FAILED",
                    "statusMessage": "temporary failure",
                }
            return {"status": "SUCCEEDED"}

        def fake_fetch(**kwargs):
            return [{"ownerUsername": "ok", "id": "post1"}]

        with (
            patch("apps.enrichment.apify_client._start_run", side_effect=fake_start),
            patch("apps.enrichment.apify_client._wait_for_run", side_effect=fake_wait),
            patch("apps.enrichment.apify_client._fetch_run_items", side_effect=fake_fetch),
        ):
            rows = run_profile_actor(
                token="token",
                actor_id="simple.actor~tiktok-profile-posts",
                handles=handles,
                batch_size=50,
            )

        errors = [row for row in rows if row.get("error") == "batch_failed"]
        good = [row for row in rows if not row.get("error")]

        self.assertEqual(len(errors), 50)
        self.assertEqual(len(good), 1)


if __name__ == "__main__":
    unittest.main()

import unittest

from apps.discovery.models import Candidate
from apps.discovery.pipeline import (
    build_scanner_queue,
    compact_post,
    deduplicate_candidates,
    merge_candidate_registry,
)


class DiscoveryTests(unittest.TestCase):
    def sample_post(
        self,
        user_id="1",
        username="creator",
        followers=20000,
        seed="polskatiktok",
        views=100000,
    ):
        return {
            "_discovery_seed": seed,
            "id": f"post-{seed}-{user_id}",
            "title": "#polska test",
            "views": views,
            "likes": 1000,
            "comments": 20,
            "shares": 10,
            "hashtags": ["polska", "polskatiktok"],
            "uploadedAtFormatted": "2026-09-30T10:00:00.000Z",
            "channel": {
                "id": user_id,
                "name": username,
                "username": username,
                "url": f"https://www.tiktok.com/@{username}",
                "followers": followers,
                "verified": False,
            },
            "subtitleInformation": [
                {"language_code": "pl", "lang": "pol-PL"}
            ],
            "video": {"url": "https://large-ephemeral-video-url.example/video.mp4"},
            "song": {"title": "unused"},
        }

    def test_dedupes_creator_across_seeds(self):
        posts = [
            self.sample_post(seed="polskatiktok"),
            self.sample_post(seed="tiktokpolska", views=200000),
        ]
        creators, stats = deduplicate_candidates(
            posts,
            min_followers=10000,
            min_pl_signals=1,
        )

        self.assertEqual(len(creators), 1)
        self.assertEqual(creators[0].posts_seen, 2)
        self.assertEqual(
            creators[0].found_by,
            ["polskatiktok", "tiktokpolska"],
        )
        self.assertEqual(creators[0].max_views_seen, 200000)
        self.assertEqual(stats["unique_creators"], 1)

    def test_follower_filter(self):
        posts = [self.sample_post(followers=9999)]
        creators, stats = deduplicate_candidates(
            posts,
            min_followers=10000,
            min_pl_signals=1,
        )
        self.assertEqual(creators, [])
        self.assertEqual(stats["below_min_followers"], 1)

    def test_compact_raw_drops_video_payload(self):
        row = compact_post(self.sample_post())
        self.assertNotIn("video", row)
        self.assertNotIn("song", row)
        self.assertEqual(row["channel"]["username"], "creator")

    def test_registry_is_cumulative(self):
        old = {
            "creators": [
                {
                    "tiktok_id": "old",
                    "username": "old_creator",
                    "followers": 50000,
                    "found_by": ["oldseed"],
                    "polish_signals": ["hashtag"],
                    "polish_signal_count": 1,
                }
            ]
        }
        latest = [
            Candidate(
                tiktok_id="new",
                username="new_creator",
                display_name="New",
                profile_url="https://www.tiktok.com/@new_creator",
                avatar_url=None,
                followers=60000,
                provider_verified=False,
                found_by=["newseed"],
                posts_seen=1,
                max_views_seen=1000,
                max_likes_seen=100,
                latest_post_at="2026-09-30T00:00:00Z",
                polish_signal_count=1,
                polish_signals=["hashtag"],
            )
        ]

        merged = merge_candidate_registry(
            old,
            latest,
            run_at="2026-10-01T00:00:00+00:00",
            latest_run_meta={"test": True},
        )
        self.assertEqual(merged["meta"]["registry_count"], 2)

    def test_queue_preserves_status(self):
        registry = {
            "creators": [
                {
                    "tiktok_id": "1",
                    "username": "creator",
                    "followers": 20000,
                    "polish_signals": ["hashtag"],
                    "found_by": ["polskatiktok"],
                    "last_discovered_at": "2026-10-01T00:00:00Z",
                }
            ]
        }
        old_queue = {
            "items": [
                {
                    "tiktok_id": "1",
                    "username": "creator",
                    "status": "profile_scanned",
                    "last_profile_scan_at": "2026-09-30T00:00:00Z",
                }
            ]
        }
        queue = build_scanner_queue(
            registry,
            old_queue,
            updated_at="2026-10-01T00:00:00Z",
        )
        self.assertEqual(queue["items"][0]["status"], "profile_scanned")
        self.assertEqual(
            queue["items"][0]["last_profile_scan_at"],
            "2026-09-30T00:00:00Z",
        )


if __name__ == "__main__":
    unittest.main()

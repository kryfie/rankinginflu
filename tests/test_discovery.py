import unittest

from apps.discovery.models import Candidate
from apps.discovery.cli import _parse_seed_indices, _select_seeds, _usable_provider_row
from apps.discovery.pipeline import (
    build_scanner_queue,
    compact_post,
    deduplicate_candidates,
    merge_candidate_registry,
    polish_evidence,
    revalidate_registry_from_previous_raw,
)


class DiscoveryTests(unittest.TestCase):
    def sample_post(
        self,
        user_id="1",
        username="creator",
        followers=20000,
        seed="polskatiktok",
        views=100000,
        title="#polska test",
        subtitles=None,
        hashtags=None,
        poi=None,
    ):
        if subtitles is None:
            subtitles = [{"language_code": "pl", "lang": "pol-PL"}]
        if hashtags is None:
            hashtags = ["polska", "polskatiktok"]

        return {
            "_discovery_seed": seed,
            "id": f"post-{seed}-{user_id}",
            "title": title,
            "views": views,
            "likes": 1000,
            "comments": 20,
            "shares": 10,
            "hashtags": hashtags,
            "uploadedAtFormatted": "2026-09-30T10:00:00.000Z",
            "channel": {
                "id": user_id,
                "name": username,
                "username": username,
                "url": f"https://www.tiktok.com/@{username}",
                "followers": followers,
                "verified": False,
            },
            "subtitleInformation": subtitles,
            "poi": poi,
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
            min_pl_confidence=50,
        )

        self.assertEqual(len(creators), 1)
        self.assertEqual(creators[0].posts_seen, 2)
        self.assertEqual(
            creators[0].found_by,
            ["polskatiktok", "tiktokpolska"],
        )
        self.assertEqual(creators[0].max_views_seen, 200000)
        self.assertGreaterEqual(creators[0].pl_confidence, 50)
        self.assertEqual(stats["unique_creators"], 1)

    def test_follower_filter(self):
        posts = [self.sample_post(followers=9999)]
        creators, stats = deduplicate_candidates(
            posts,
            min_followers=10000,
            min_pl_signals=1,
            min_pl_confidence=50,
        )
        self.assertEqual(creators, [])
        self.assertEqual(stats["below_min_followers"], 1)

    def test_compact_raw_drops_video_payload(self):
        row = compact_post(self.sample_post())
        self.assertNotIn("video", row)
        self.assertNotIn("song", row)
        self.assertEqual(row["channel"]["username"], "creator")
        self.assertIn("pl_evidence", row)

    def test_foreign_polska_keyword_is_rejected(self):
        # Mirrors the real false-positive pattern: French/English content that
        # happens to contain Polska/#polska.
        post = self.sample_post(
            username="speed_salami1",
            followers=98940,
            seed="polska",
            title="HUMOUR / série française #polska",
            subtitles=[
                {"language_code": "en", "lang": "eng-US"},
                {"language_code": "fr", "lang": "fra-FR"},
            ],
            hashtags=["polska"],
        )
        evidence = polish_evidence(post)
        self.assertEqual(evidence["strong_signals"], [])
        self.assertLess(evidence["pl_confidence"], 50)

        creators, _ = deduplicate_candidates(
            [post],
            min_followers=10000,
            min_pl_signals=1,
            min_pl_confidence=50,
        )
        self.assertEqual(creators, [])

    def test_foreign_person_named_polska_is_rejected(self):
        post = self.sample_post(
            username="w9lachaine",
            followers=2757849,
            seed="polska",
            title="Trahie par son entourage, Polska prend la parole",
            subtitles=[
                {"language_code": "en", "lang": "eng-US"},
                {"language_code": "fr", "lang": "fra-FR"},
            ],
            hashtags=[],
        )
        creators, _ = deduplicate_candidates(
            [post],
            min_followers=10000,
            min_pl_signals=1,
            min_pl_confidence=50,
        )
        self.assertEqual(creators, [])

    def test_polish_language_without_subtitles_is_accepted(self):
        post = self.sample_post(
            username="iskra_polan",
            followers=43170,
            seed="polska",
            title="Tzg będzie jutro, musieliśmy to dodać xdddd #polska",
            subtitles=[],
            hashtags=["polska", "taniec"],
        )
        evidence = polish_evidence(post)
        self.assertIn("polish_text", evidence["strong_signals"])

        creators, _ = deduplicate_candidates(
            [post],
            min_followers=10000,
            min_pl_signals=1,
            min_pl_confidence=50,
        )
        self.assertEqual(len(creators), 1)

    def test_polish_flag_overrides_foreign_poi(self):
        post = self.sample_post(
            username="turystyka.stadionowa",
            followers=22843,
            seed="polska",
            title="Na trybunach nie mamy sobie równych 🇵🇱 #polska",
            subtitles=[],
            hashtags=["polska", "kibice"],
            poi={"address": "Solna, Sweden"},
        )
        evidence = polish_evidence(post)
        self.assertIn("flag_pl", evidence["strong_signals"])
        self.assertIn("poi_foreign", evidence["negative_signals"])
        self.assertGreaterEqual(evidence["pl_confidence"], 50)

    def test_demo_row_is_not_usable(self):
        self.assertFalse(_usable_provider_row({"demo": True}))
        creators, stats = deduplicate_candidates(
            [{"demo": True}],
            min_followers=0,
            min_pl_signals=1,
            min_pl_confidence=50,
        )
        self.assertEqual(creators, [])
        self.assertEqual(stats["demo_rows_ignored"], 1)

    def test_registry_is_cumulative(self):
        old = {
            "creators": [
                {
                    "tiktok_id": "old",
                    "username": "old_creator",
                    "followers": 50000,
                    "found_by": ["oldseed"],
                    "polish_signals": ["subtitle_pl"],
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
                polish_signals=["subtitle_pl"],
                polish_strong_signal_count=1,
                polish_strong_signals=["subtitle_pl"],
                pl_confidence=80.0,
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
                    "polish_signals": ["subtitle_pl"],
                    "polish_strong_signals": ["subtitle_pl"],
                    "pl_confidence": 80,
                    "discovery_eligible": True,
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

    def test_weak_pending_candidate_is_removed_from_queue(self):
        registry = {
            "creators": [
                {
                    "tiktok_id": "1",
                    "username": "foreign_false_positive",
                    "followers": 100000,
                    "discovery_eligible": False,
                }
            ]
        }
        old_queue = {
            "items": [
                {
                    "tiktok_id": "1",
                    "username": "foreign_false_positive",
                    "status": "pending_profile_scan",
                }
            ]
        }
        queue = build_scanner_queue(
            registry,
            old_queue,
            updated_at="2026-10-01T00:00:00Z",
        )
        self.assertEqual(queue["items"], [])

    def test_revalidation_quarantines_previous_weak_false_positive(self):
        registry = {
            "creators": [
                {
                    "tiktok_id": "1",
                    "username": "w9lachaine",
                    "followers": 2757849,
                    "discovery_eligible": True,
                }
            ]
        }
        queue = {
            "items": [
                {
                    "tiktok_id": "1",
                    "username": "w9lachaine",
                    "status": "pending_profile_scan",
                }
            ]
        }
        previous = {
            "posts": [
                {
                    "seed": "polska",
                    "id": "p1",
                    "title": "Polska prend la parole",
                    "hashtags": [],
                    "views": 100,
                    "channel": {
                        "id": "1",
                        "username": "w9lachaine",
                        "name": "W9",
                        "followers": 2757849,
                    },
                    "subtitle_languages": ["en", "fr"],
                    "poi": None,
                }
            ]
        }

        cleaned, stats = revalidate_registry_from_previous_raw(
            registry,
            previous,
            queue,
            min_followers=10000,
            min_pl_signals=1,
            min_pl_confidence=50,
        )
        self.assertFalse(cleaned["creators"][0]["discovery_eligible"])
        self.assertEqual(stats["legacy_rows_quarantined"], 1)

    def test_seed_window(self):
        seeds = ["a", "b", "c", "d", "e"]
        self.assertEqual(
            _select_seeds(seeds, start_seed=2, max_seeds=2),
            ["c", "d"],
        )

    def test_seed_window_all_remaining(self):
        seeds = ["a", "b", "c", "d"]
        self.assertEqual(
            _select_seeds(seeds, start_seed=1, max_seeds=0),
            ["b", "c", "d"],
        )

    def test_seed_window_past_end_is_empty(self):
        seeds = ["a", "b"]
        self.assertEqual(
            _select_seeds(seeds, start_seed=2, max_seeds=2),
            [],
        )


    def test_explicit_seed_indices(self):
        self.assertEqual(
            _parse_seed_indices("5,7,9", 12),
            [5, 7, 9],
        )

    def test_explicit_seed_indices_dedupe(self):
        self.assertEqual(
            _parse_seed_indices("2,2,3", 5),
            [2, 3],
        )


    def test_queue_preserves_related_mentions(self):
        registry = {"creators": []}
        old_queue = {
            "items": [
                {
                    "username": "related_creator",
                    "status": "pending_profile_scan",
                    "source": "related_mentions",
                    "priority": 1,
                }
            ]
        }

        queue = build_scanner_queue(
            registry,
            old_queue,
            updated_at="2026-10-01T00:00:00Z",
        )

        self.assertEqual(
            queue["items"][0]["username"],
            "related_creator",
        )
        self.assertEqual(
            queue["items"][0]["source"],
            "related_mentions",
        )


if __name__ == "__main__":
    unittest.main()

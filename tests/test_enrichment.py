import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from apps.enrichment.pipeline import enrich_state, select_queue_items
from apps.enrichment.classification import (
    classify_creator,
    combine_pl_confidence,
)

from apps.enrichment.ranking import build_web_ranking, robust_consistency_index


class DummySettings:
    actor_id = "simple.actor~tiktok-profile-posts"

    def __init__(self, root):
        root = Path(root)
        self.queue_path = root / "scanner_queue.json"
        self.web_ranking_path = root / "creators.json"
        self.creators_path = root / "enriched_creators.json"
        self.posts_path = root / "posts.json"
        self.snapshots_path = root / "snapshots.json"
        self.raw_path = root / "raw.json"


class EnrichmentTests(unittest.TestCase):
    def actor_row(self, username="creator", post_id="p1", views=1000, pinned=False):
        return {
            "inputUrl": f"https://www.tiktok.com/@{username}",
            "id": post_id,
            "url": f"https://www.tiktok.com/@{username}/video/{post_id}",
            "type": "video",
            "caption": "Polski humor #polska",
            "hashtags": ["polska"],
            "mentions": [],
            "timestamp": "2026-09-30T10:00:00.000Z",
            "timestampUnix": 1790762400,
            "playCount": views,
            "likeCount": 100,
            "commentCount": 10,
            "shareCount": 5,
            "ownerUsername": username,
            "ownerId": "u1",
            "ownerNickname": "Creator",
            "ownerIsVerified": True,
            "createdInRegion": "PL",
            "profileUrl": f"https://www.tiktok.com/@{username}",
            "scrapedAt": "2026-10-01T08:00:00.000Z",
            "isPinned": pinned,
            "isAd": False,
            "isBrandedContent": False,
            "author": {
                "username": username,
                "userId": "u1",
                "nickname": "Creator",
                "profileUrl": f"https://www.tiktok.com/@{username}",
                "biography": "Twórca z Polski 🇵🇱",
                "isVerified": True,
                "isPrivate": False,
                "followerCount": 20000,
                "followingCount": 100,
                "heartCount": 500000,
                "postCount": 200,
                "friendCount": 20,
                "followersAreExact": True,
                "avatarUrl": "https://example.com/a.jpg",
                "accountCreatedAt": "2020-01-01T00:00:00.000Z",
                "isOrganization": False,
                "isCommerceUser": False,
                "isSeller": False,
                "language": "pl",
                "recentActivity": {"postsMeasured": 13},
            },
        }

    def test_queue_selection_pending_only(self):
        q = {
            "items": [
                {"username": "a", "priority": 1, "status": "pending_profile_scan"},
                {"username": "b", "priority": 2, "status": "enriched"},
                {"username": "c", "priority": 3, "status": "enrichment_error"},
            ]
        }
        selected = select_queue_items(q, max_profiles=10, refresh_all=False)
        self.assertEqual([x["username"] for x in selected], ["a", "c"])

    def test_enrichment_writes_normalized_state(self):
        with TemporaryDirectory() as td:
            s = DummySettings(td)
            s.queue_path.write_text(
                '{"meta":{},"items":[{"username":"creator","priority":1,"polish_signals":["hashtag"],"status":"pending_profile_scan"}]}',
                encoding="utf-8",
            )
            rows = [
                self.actor_row(post_id="p1", views=1000),
                self.actor_row(post_id="p2", views=2000),
                self.actor_row(post_id="p3", views=3000),
            ]
            result = enrich_state(
                settings=s,
                actor_rows=rows,
                selected_items=[
                    {
                        "username": "creator",
                        "priority": 1,
                        "polish_signals": ["hashtag"],
                        "status": "pending_profile_scan",
                    }
                ],
                run_at="2026-10-01T08:00:00+00:00",
            )
            self.assertEqual(result["successful"], 1)
            self.assertEqual(result["posts_total"], 3)
            self.assertTrue(s.web_ranking_path.exists())

    def test_ranking_omits_missing_momentum(self):
        creators = [
            {
                "username": "creator",
                "display_name": "Creator",
                "followers": 20000,
                "verified": True,
                "category": "Entertainment",
                "last_enriched_at": "2026-10-01T08:00:00+00:00",
            }
        ]
        posts = [
            {
                "id": "1",
                "username": "creator",
                "timestamp": "2026-09-30T00:00:00Z",
                "views": 1000,
                "likes": 100,
                "comments": 10,
                "shares": 5,
                "is_pinned": False,
            },
            {
                "id": "2",
                "username": "creator",
                "timestamp": "2026-09-29T00:00:00Z",
                "views": 2000,
                "likes": 150,
                "comments": 10,
                "shares": 5,
                "is_pinned": False,
            },
            {
                "id": "3",
                "username": "creator",
                "timestamp": "2026-09-28T00:00:00Z",
                "views": 3000,
                "likes": 200,
                "comments": 10,
                "shares": 5,
                "is_pinned": False,
            },
        ]
        ranking = build_web_ranking(creators, posts, [])
        self.assertEqual(ranking[0]["growth"], None)
        self.assertEqual(
            ranking[0]["score_status"],
            "provisional_no_30d_history",
        )
        self.assertEqual(ranking[0]["views"], 2000.0)


    def test_robust_consistency_does_not_collapse_on_one_viral_post(self):
        stable_with_viral = [
            31100, 31400, 31500, 40100, 44900,
            74000, 223000, 396900, 1600000, 2000000
        ]
        score = robust_consistency_index(stable_with_viral)
        self.assertGreater(score, 40.0)
        self.assertLessEqual(score, 100.0)

    def test_more_stable_series_scores_higher(self):
        stable = [90000, 95000, 100000, 105000, 110000, 115000]
        volatile = [500, 1500, 60000, 180000, 500000, 2000000]
        self.assertGreater(
            robust_consistency_index(stable),
            robust_consistency_index(volatile),
        )


    def test_pl_confidence_preserves_discovery_signal(self):
        combined = combine_pl_confidence(80.0, 90.0)
        self.assertEqual(combined, 84.0)
        self.assertLess(combined, 100.0)

    def test_melodia_tv_is_creator_brand_music_not_media(self):
        creator = {
            "username": "melodiatvpolska_",
            "display_name": "Melodia TV Polska",
            "bio": (
                "Melodia TV polska / Official account. "
                "Drive-by karaoke across the whole of 🇵🇱"
            ),
            "followers": 56858,
            "private": False,
            "language": "en",
            "is_organization": False,
            "is_commerce_user": False,
            "is_seller": False,
            "last_enriched_at": "2026-10-01T09:15:43+00:00",
        }
        posts = [
            {
                "caption": "Karaoke z samochodu #piosenka #polska",
                "created_in_region": "PL",
                "views": 100000 + i,
                "timestamp": f"2026-09-{20+i:02d}T12:00:00Z",
                "is_pinned": False,
            }
            for i in range(8)
        ]
        result = classify_creator(
            creator,
            posts,
            {
                "discovery_pl_confidence": 85.0,
                "polish_strong_signals": ["flag_pl", "polish_text"],
            },
        )
        self.assertEqual(result["account_type"], "creator_brand")
        self.assertEqual(result["category"], "Music")
        self.assertTrue(result["ranking_eligible"])
        self.assertLess(result["pl_confidence"], 100.0)

    def test_company_is_excluded(self):
        creator = {
            "username": "example_company",
            "display_name": "Example Company",
            "bio": "Oficjalny sklep internetowy firmy Example sp. z o.o.",
            "followers": 50000,
            "private": False,
            "language": "pl",
            "is_organization": True,
            "is_commerce_user": True,
            "is_seller": True,
            "last_enriched_at": "2026-10-01T09:15:43+00:00",
        }
        posts = [
            {
                "caption": "Nowy produkt dla Was #polska",
                "created_in_region": "PL",
                "views": 10000,
                "timestamp": f"2026-09-{20+i:02d}T12:00:00Z",
                "is_pinned": False,
            }
            for i in range(8)
        ]
        result = classify_creator(creator, posts, {"discovery_pl_confidence": 80})
        self.assertEqual(result["account_type"], "company")
        self.assertFalse(result["ranking_eligible"])
        self.assertIn("account_type_company", result["eligibility_reasons"])


if __name__ == "__main__":
    unittest.main()

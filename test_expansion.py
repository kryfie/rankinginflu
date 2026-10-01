import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import apps.automation.expansion as expansion


class ExpansionTests(unittest.TestCase):
    def _write_json(self, path, payload):
        path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_recurring_hashtag_becomes_seed(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            seeds = root / "seeds.json"
            meta = root / "meta.json"
            related = root / "related.json"
            creators = root / "creators.json"
            posts = root / "posts.json"
            queue = root / "queue.json"

            self._write_json(seeds, {"keywords": ["polska"]})
            self._write_json(
                creators,
                {
                    "creators": [
                        {
                            "username": "aa",
                            "ranking_eligible": True,
                        },
                        {
                            "username": "bb",
                            "ranking_eligible": True,
                        },
                    ]
                },
            )
            self._write_json(
                posts,
                {
                    "posts": [
                        {
                            "id": "1",
                            "username": "aa",
                            "hashtags": ["skincare", "fyp"],
                            "mentions": [],
                        },
                        {
                            "id": "2",
                            "username": "bb",
                            "hashtags": ["skincare"],
                            "mentions": [],
                        },
                    ]
                },
            )
            self._write_json(queue, {"meta": {}, "items": []})

            with (
                patch.object(expansion, "SEEDS_PATH", seeds),
                patch.object(expansion, "SEED_META_PATH", meta),
                patch.object(expansion, "RELATED_PATH", related),
                patch.object(expansion, "CREATORS_PATH", creators),
                patch.object(expansion, "POSTS_PATH", posts),
                patch.object(expansion, "QUEUE_PATH", queue),
            ):
                result = expansion.harvest(
                    max_new_seeds=10,
                    min_seed_score=4,
                )

            payload = json.loads(seeds.read_text(encoding="utf-8"))
            self.assertIn("skincare", payload["keywords"])
            self.assertNotIn("fyp", payload["keywords"])
            self.assertEqual(result["new_dynamic_seeds"], 1)

    def test_related_handle_requires_repeated_or_corroborated_mention(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            seeds = root / "seeds.json"
            meta = root / "meta.json"
            related = root / "related.json"
            creators = root / "creators.json"
            posts = root / "posts.json"
            queue = root / "queue.json"

            self._write_json(seeds, {"keywords": ["polska"]})
            self._write_json(
                creators,
                {
                    "creators": [
                        {
                            "username": "creator_a",
                            "ranking_eligible": True,
                        },
                        {
                            "username": "creator_b",
                            "ranking_eligible": True,
                        },
                    ]
                },
            )
            self._write_json(
                posts,
                {
                    "posts": [
                        {
                            "id": "1",
                            "username": "creator_a",
                            "hashtags": [],
                            "mentions": ["friend_x", "one_off"],
                        },
                        {
                            "id": "2",
                            "username": "creator_b",
                            "hashtags": [],
                            "mentions": ["friend_x"],
                        },
                    ]
                },
            )
            self._write_json(queue, {"meta": {}, "items": []})

            with (
                patch.object(expansion, "SEEDS_PATH", seeds),
                patch.object(expansion, "SEED_META_PATH", meta),
                patch.object(expansion, "RELATED_PATH", related),
                patch.object(expansion, "CREATORS_PATH", creators),
                patch.object(expansion, "POSTS_PATH", posts),
                patch.object(expansion, "QUEUE_PATH", queue),
            ):
                expansion.harvest(
                    max_related_handles=10,
                )

            q = json.loads(queue.read_text(encoding="utf-8"))
            usernames = {
                row["username"]
                for row in q["items"]
            }
            self.assertIn("friend_x", usernames)
            self.assertNotIn("one_off", usernames)

    def test_generic_hashtags_are_never_promoted(self):
        for tag in ["fyp", "#viral", "polska", "tiktok"]:
            self.assertEqual(
                expansion._normalize_hashtag(tag),
                "",
            )


if __name__ == "__main__":
    unittest.main()

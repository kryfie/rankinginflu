import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import apps.automation.geo as geo


class GeoTests(unittest.TestCase):
    def test_bio_city_is_high_confidence_home_city(self):
        events = {}
        geo._collect_bio_events(
            events,
            [
                {
                    "username": "foodie",
                    "bio": "Food guide • Szczecin 🇵🇱",
                    "last_enriched_at": "2026-10-01T10:00:00+00:00",
                }
            ],
        )
        result = geo._score_username("foodie", list(events.values()))
        self.assertEqual(result["primary_city"], "Szczecin")
        self.assertEqual(result["home_city"], "Szczecin")
        self.assertGreaterEqual(result["geo_confidence"], 90)

    def test_single_poi_creates_content_city_but_not_home_city(self):
        events = {}
        geo._add_event(
            events,
            username="creator",
            city="Warszawa",
            source="poi",
            ref="post1",
            weight=75,
        )
        result = geo._score_username("creator", list(events.values()))
        self.assertEqual(result["primary_city"], "Warszawa")
        self.assertIsNone(result["home_city"])
        self.assertGreaterEqual(result["geo_confidence"], 60)

    def test_repeated_text_can_promote_city(self):
        events = {}
        for i in range(4):
            geo._add_event(
                events,
                username="creator",
                city="Kraków",
                source="post_text",
                ref=f"post{i}",
                weight=18,
            )
        result = geo._score_username("creator", list(events.values()))
        self.assertEqual(result["primary_city"], "Kraków")
        self.assertEqual(result["geo_confidence"], 72.0)

    def test_same_post_is_idempotent(self):
        events = {}
        for _ in range(5):
            geo._add_event(
                events,
                username="creator",
                city="Poznań",
                source="post_text",
                ref="same-post",
                weight=18,
            )
        self.assertEqual(len(events), 1)

    def test_ambiguous_short_city_not_taken_from_free_text(self):
        self.assertNotIn("Piła", geo._text_city_hits("piła drewno przez godzinę"))
        self.assertNotIn("Hel", geo._text_city_hits("hello from Poland"))

    def test_poi_city_from_name_when_city_name_blank(self):
        self.assertEqual(
            geo._poi_city(
                {
                    "poiName": "Szczecin",
                    "address": "West Pomerania, Poland",
                    "cityName": "",
                    "regionCode": "798544",
                }
            ),
            "Szczecin",
        )

    def test_poi_city_from_address_when_city_name_blank(self):
        self.assertEqual(
            geo._poi_city(
                {
                    "poiName": "Bydgoszcz",
                    "address": "Bydgoszcz, Bydgoszcz, Kujawsko-Pomorskie, Poland",
                    "cityName": "",
                    "regionCode": "798544",
                }
            ),
            "Bydgoszcz",
        )

    def test_smaller_city_from_exact_poi_address_agreement(self):
        self.assertEqual(
            geo._poi_city(
                {
                    "poiName": "Przysucha",
                    "address": "Przysucha, Mazovia, Poland",
                    "cityName": "",
                }
            ),
            "Przysucha",
        )

    def test_conflicting_poi_metadata_is_rejected(self):
        self.assertEqual(
            geo._poi_city(
                {
                    "poiName": "Wisła",
                    "address": "Polska",
                    "cityName": "Warsaw",
                }
            ),
            "",
        )


if __name__ == "__main__":
    unittest.main()

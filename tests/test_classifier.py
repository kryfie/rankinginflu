import unittest

from apps.enrichment.classification import infer_account_type
from packages.classifier.pl_classifier import (
    infer_category,
    infer_category_scored,
    pl_confidence,
)


class T(unittest.TestCase):
    def test_pl(self):
        self.assertGreater(
            pl_confidence(
                "Cześć! Jestem z Polski, dziś trening w Warszawie #polska"
            ),
            50,
        )

    def test_cat(self):
        self.assertEqual(
            infer_category("trening fitness siłownia"),
            "Sport & Fitness",
        )

    def test_ai_does_not_match_inside_unrelated_words(self):
        category, _, _ = infer_category_scored(
            display_name="Melodia TV Polska",
            bio="Karaoke i piosenki z samochodu",
            captions=["Karaoke z samochodu #piosenka"],
        )
        self.assertEqual(category, "Music")

    def test_finance_news_creator(self):
        category, _, _ = infer_category_scored(
            display_name="dla_pieniedzy",
            bio="Faktura za prąd rośnie?",
            captions=[
                "Ceny ropy, gospodarka, ekonomia, rynek, energia i pieniądze",
                "Geopolityka i biznes",
            ],
        )
        self.assertEqual(category, "Finance")

    def test_provider_organization_is_company(self):
        account_type, _, reasons = infer_account_type(
            {
                "username": "carrefourpolska",
                "display_name": "CarrefourPoland",
                "bio": "",
                "is_organization": True,
                "is_commerce_user": False,
                "is_seller": False,
            },
            [],
        )
        self.assertEqual(account_type, "company")
        self.assertIn("provider_is_organization", reasons)

    def test_brand_poland_identity_is_company(self):
        account_type, _, reasons = infer_account_type(
            {
                "username": "starbuckspolska",
                "display_name": "Starbucks Polska",
                "bio": "Jeden człowiek, jedna kawa, jedno miejsce",
                "is_organization": False,
                "is_commerce_user": False,
                "is_seller": False,
            },
            [],
        )
        self.assertEqual(account_type, "company")
        self.assertIn("brand_poland_identity", reasons)

    def test_person_in_poland_is_not_company(self):
        account_type, _, _ = infer_account_type(
            {
                "username": "joneswpolsce",
                "display_name": "Jones w Polsce",
                "bio": "Życie w Polsce",
            },
            [],
        )
        self.assertIn(account_type, {"person", "creator_brand"})

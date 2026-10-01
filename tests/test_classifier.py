import unittest

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

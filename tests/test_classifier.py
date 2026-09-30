import unittest
from packages.classifier.pl_classifier import pl_confidence, infer_category
class T(unittest.TestCase):
    def test_pl(self): self.assertGreater(pl_confidence('Cześć! Jestem z Polski, dziś trening w Warszawie #polska'),50)
    def test_cat(self): self.assertEqual(infer_category('trening fitness siłownia'),'Sport & Fitness')

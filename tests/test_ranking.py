import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from apps.scanner.scanner.db import connect, save_snapshot
from packages.shared.models import CreatorSnapshot, PostMetric
from packages.ranking.ranking import build_ranking
class T(unittest.TestCase):
    def test_score(self):
        with TemporaryDirectory() as d:
            c=connect(Path(d)/'t.db')
            save_snapshot(c,CreatorSnapshot(handle='a',display_name='A',followers=100000,collected_at='2026-09-30T00:00:00+00:00',posts=[PostMetric('1',views=200000,likes=20000,comments=1000,shares=500)]),90,'Entertainment')
            save_snapshot(c,CreatorSnapshot(handle='b',display_name='B',followers=500000,collected_at='2026-09-30T00:00:00+00:00',posts=[PostMetric('2',views=100000,likes=5000,comments=100,shares=50)]),90,'Entertainment')
            rows=build_ranking(c); self.assertEqual(len(rows),2); self.assertTrue(all(0<=x['score']<=100 for x in rows)); c.close()

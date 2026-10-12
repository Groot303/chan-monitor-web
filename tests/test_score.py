import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from chan2 import score_signal

def S(**kw):
    d = dict(type='3B', price=100.0, confirmed=True, bars_ago=1, resonance='neutral',
             zg=95.0, zd=90.0, margin_pct=2.0)
    d.update(kw); return d

def sc(level='daily', **kw): return score_signal(S(**kw), level)[0]

class TestScore(unittest.TestCase):
    def test_range_all_types(self):
        for t in ('1B','1S','2B','2S','3B','3S'):
            for conf in (True, False):
                for res in ('strong','partial','neutral','mixed','conflict','n/a'):
                    for age in (0, 3, 10, 500):
                        for ratio in (0.0, 0.5, 1.0):
                            s, bd = score_signal(S(type=t, confirmed=conf, resonance=res, bars_ago=age,
                                                   ratio=ratio, dif_enter=2.0, dif_leave=1.0, margin_pct=50.0), 'daily')
                            self.assertTrue(0 <= s <= 10, (t, conf, res, age, s))
    def test_cap_and_floor(self):
        s, bd = score_signal(S(type='1B', ratio=0.0, dif_enter=5, dif_leave=1, resonance='strong', zg=130, zd=90,
                               bars_ago=0), 'daily')
        self.assertLessEqual(s, 10)
        s, bd = score_signal(S(type='3B', confirmed=False, resonance='conflict', bars_ago=999, margin_pct=0, zg=100, zd=100), 'daily')
        self.assertEqual(s, 0.0); self.assertTrue(bd['capped'])
    def test_cap_flag(self):
        s, bd = score_signal(S(type='1B', ratio=0.0, dif_enter=5, dif_leave=1, resonance='strong', zg=130, zd=90, bars_ago=0), 'daily')
        self.assertEqual(bd['capped'], bd['raw_total'] > 10)
    def test_breakdown_sums_to_raw(self):
        s, bd = score_signal(S(), 'daily')
        parts = sum(bd[k] for k in ('base','divergence','resonance','confirmed','freshness','quality'))
        self.assertAlmostEqual(parts, bd['raw_total'], places=1)
    def test_smaller_ratio_higher(self):
        a = sc(type='1B', ratio=0.2); b = sc(type='1B', ratio=0.8)
        self.assertGreater(a, b)
    def test_resonance_order(self):
        v = [sc(resonance=r) for r in ('strong','partial','neutral','mixed','conflict')]
        self.assertEqual(v, sorted(v, reverse=True)); self.assertGreater(v[0], v[-1])
    def test_unconfirmed_lower(self):
        self.assertLess(sc(confirmed=False), sc(confirmed=True))
    def test_older_lower_and_stale_big_drop(self):
        fresh, mid, edge, stale = (sc(bars_ago=a) for a in (0, 4, 10, 11))
        self.assertGreaterEqual(fresh, mid); self.assertGreaterEqual(mid, edge)
        self.assertGreaterEqual(edge - stale, 3.0)
    def test_stale_threshold_per_level(self):
        self.assertGreater(sc('30m', bars_ago=30), sc('daily', bars_ago=30))
    def test_quality_margin_and_width(self):
        self.assertGreater(sc(margin_pct=4.0), sc(margin_pct=0.2))
        self.assertGreater(sc(zg=100, zd=90), sc(zg=90.1, zd=90))
    def test_type_base_differs(self):
        a = score_signal(S(type='1B', ratio=1.0), 'daily')[1]['base']
        b = score_signal(S(type='2B'), 'daily')[1]['base']
        self.assertNotEqual(a, b)
    def test_buy_sell_symmetric(self):
        self.assertEqual(sc(type='3B'), sc(type='3S'))
if __name__ == '__main__':
    unittest.main()

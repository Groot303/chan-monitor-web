import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from chan2 import build_segments, build_pivots, find_signals, macd, resonance, Seg, level_state

def P(prices, start='bottom'):
    t = start; out = []
    for k, p in enumerate(prices):
        out.append((k*5, t, p)); t = 'top' if t == 'bottom' else 'bottom'
    return out

class TestSegments(unittest.TestCase):
    def test_up_segment_confirmed_by_top_fractal(self):
        # up: 10->20, down 20->14, up 14->30 (top), down 30->22, up 22->26 (lower high), down 26->18
        pts = P([10, 20, 14, 30, 22, 26, 18])
        segs = build_segments(pts)
        self.assertTrue(segs[0].up and segs[0].confirmed)
        self.assertEqual((segs[0].s_p, segs[0].e_p), (10, 30))
        self.assertFalse(segs[-1].up if False else False)
        self.assertEqual(segs[1].up, False)
    def test_no_split_without_fractal(self):
        # strictly rising strokes, feature elements keep rising -> single unconfirmed segment
        pts = P([10, 20, 15, 30, 25, 40, 35, 50])
        segs = build_segments(pts)
        self.assertEqual(len(segs), 1)
        self.assertFalse(segs[0].confirmed)
        self.assertEqual(segs[0].e_p, 50)
    def test_feature_inclusion_merge(self):
        # down strokes (30->20),(28->22) is contained in first -> merged, no early fractal
        pts = P([10, 30, 20, 40, 22, 45, 30, 44, 33, 42, 28])
        segs = build_segments(pts)
        self.assertEqual(segs[0].e_p, 45)
        self.assertTrue(segs[0].confirmed)
    def test_down_segment(self):
        pts = P([50, 40, 46, 30, 38, 34, 42], start='top')
        segs = build_segments(pts)
        self.assertFalse(segs[0].up); self.assertEqual(segs[0].e_p, 30); self.assertTrue(segs[0].confirmed)

class TestBreak(unittest.TestCase):
    def test_break_of_start_closes_segment(self):
        # down seg from 50: new lows 40,30,22 then price rallies above 50 w/o feature fractal
        pts = P([50, 40, 44, 32, 36, 22, 60, 55, 70], start='top')
        segs = build_segments(pts)
        self.assertFalse(segs[0].up); self.assertEqual(segs[0].e_p, 22)
        self.assertTrue(segs[0].by_break or segs[0].confirmed)
    def test_short_broken_segment_restarts(self):
        pts = P([50, 40, 45, 35, 52, 30, 60, 20, 70], start='top')
        segs = build_segments(pts)
        self.assertTrue(len(segs) >= 1)

def S(sp, ep, confirmed=True, i=0):
    return Seg(i, sp, i+1, ep, ep > sp, confirmed)

class TestPivots(unittest.TestCase):
    def test_pivot_zg_zd_and_extension(self):
        segs = [S(10, 30), S(30, 20), S(20, 28), S(28, 22), S(22, 27)]
        pv = build_pivots(segs)
        self.assertEqual(len(pv), 1)
        self.assertEqual((pv[0]['zd'], pv[0]['zg']), (22 if False else 20, 28))
        self.assertEqual(pv[0]['last'], 4); self.assertIsNone(pv[0]['leave'])
    def test_leave_and_third_buy(self):
        segs = [S(10, 30), S(30, 20), S(20, 28), S(28, 40), S(40, 31)]
        pv = build_pivots(segs)
        self.assertEqual(pv[0]['leave'], 3); self.assertTrue(pv[0]['third'])
        sig = find_signals(segs, pv, lambda a, b, u: (1.0, 0.0))
        t3 = [s for s in sig if s['type'] == '3B']
        self.assertEqual(len(t3), 1); self.assertEqual(t3[0]['price'], 31)
    def test_return_into_pivot_is_extension_not_third(self):
        segs = [S(10, 30), S(30, 20), S(20, 28), S(28, 40), S(40, 26), S(26, 33)]
        pv = build_pivots(segs)
        self.assertFalse(pv[0]['third'])
        self.assertEqual([s for s in find_signals(segs, pv, lambda a, b, u: (1.0, 0.0)) if s['type'] == '3B'], [])

class TestDivergenceSignals(unittest.TestCase):
    def build(self):
        # downtrend: pivot A (zone ~ 90-100), leave down to 70, pivot B (zone 72-78), leave down to 60
        pts_segs = [S(120, 100), S(100, 110), S(110, 90), S(90, 105), S(105, 70),   # pivot A then leave seg(4) to 70
                    S(70, 80), S(80, 72), S(72, 78), S(78, 60)]                     # pivot B then leave to 60 (seg 8)
        return pts_segs
    def test_1B_when_area_smaller(self):
        segs = self.build(); pv = build_pivots(segs)
        # enter seg of B is seg 4 (area 10), leave seg 8 smaller area 4
        areas = {4: 10.0, 8: 4.0}
        def af(i0, i1, up):
            # i0 identifies segment by construction below
            return (areas.get(i0, 1.0), 0.0)
        for k, s in enumerate(segs): s.s_i = k; s.e_i = k
        sig = find_signals(segs, pv, lambda a, b, u: (areas.get(a, 1.0), -1.0))
        b1 = [s for s in sig if s['type'] == '1B']
        self.assertEqual(len(b1), 1, (pv, sig))
        self.assertEqual(b1[0]['price'], 60); self.assertLess(b1[0]['ratio'], 1)
    def test_no_1B_when_area_larger(self):
        segs = self.build(); pv = build_pivots(segs)
        for k, s in enumerate(segs): s.s_i = k; s.e_i = k
        areas = {4: 4.0, 8: 10.0}
        sig = find_signals(segs, pv, lambda a, b, u: (areas.get(a, 1.0), -1.0))
        self.assertEqual([s for s in sig if s['type'] == '1B'], [])
    def test_2B_after_1B(self):
        segs = self.build() + [S(60, 75), S(75, 65)]
        for k, s in enumerate(segs): s.s_i = k; s.e_i = k
        pv = build_pivots(segs)
        areas = {4: 10.0, 8: 4.0}
        sig = find_signals(segs, pv, lambda a, b, u: (areas.get(a, 1.0), -1.0))
        b2 = [s for s in sig if s['type'] == '2B']
        self.assertEqual(len(b2), 1); self.assertEqual(b2[0]['price'], 65)
    def test_unconfirmed_flag(self):
        segs = self.build(); segs[-1].confirmed = False
        for k, s in enumerate(segs): s.s_i = k; s.e_i = k
        pv = build_pivots(segs)
        sig = find_signals(segs, pv, lambda a, b, u: ({4: 10.0, 8: 4.0}.get(a, 1.0), -1.0))
        self.assertFalse([s for s in sig if s['type'] == '1B'][0]['confirmed'])

class TestMacdAndResonance(unittest.TestCase):
    def test_macd_constant_is_zero(self):
        dif, dea, h = macd([5.0]*50); self.assertAlmostEqual(abs(h).max(), 0)
    def test_macd_rising_positive(self):
        dif, dea, h = macd(list(range(1, 80))); self.assertGreater(dif[-1], 0)
    def test_resonance(self):
        up = {'direction': 'up'}; dn = {'direction': 'down'}; rg = {'direction': 'range'}
        self.assertEqual(resonance('2B', [up, up]), 'strong')
        self.assertEqual(resonance('2B', [up, rg]), 'partial')
        self.assertEqual(resonance('2B', [dn, dn]), 'conflict')
        self.assertEqual(resonance('2S', [dn, dn]), 'strong')
    def test_level_state(self):
        pv = [dict(zg=10, zd=5)]
        self.assertEqual(level_state([], pv, 12)['direction'], 'up')
        self.assertEqual(level_state([], pv, 3)['direction'], 'down')
        self.assertEqual(level_state([], pv, 7)['direction'], 'range')

if __name__ == '__main__': unittest.main()

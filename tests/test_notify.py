import sys, unittest
sys.path.insert(0, "scripts")
import notify_telegram as n

def sig(**k):
    d = dict(symbol="A", level="30m", type="3B", time="t1", price=1.0, score=6.5, recent=True, confirmed=False)
    d.update(k); return d

class T(unittest.TestCase):
    def test_flow(self):
        s = sig(); st = {}
        self.assertEqual(n.select([s], st), [s])
        n.update_state([s], st)
        self.assertEqual(n.select([s], st), [])
        c = sig(confirmed=True)
        self.assertEqual(n.select([c], st), [c])
        n.update_state([c], st)
        self.assertEqual(n.select([c], st), [])
    def test_filters(self):
        self.assertEqual(n.select([sig(score=3.9), sig(recent=False, time="t2")], {}, score_min=4.0), [])
        self.assertEqual(len(n.select([sig(score=4.0)], {}, score_min=4.0)), 1)
    def test_fmt(self):
        self.assertIn("可能重绘", n.fmt([sig()]))

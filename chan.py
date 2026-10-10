"""Chan (缠论) daily-level prototype: merge, fractals, new strokes, pivots."""
from dataclasses import dataclass

@dataclass
class Bar:
    date: object
    high: float
    low: float
    first: int  # raw index of first raw bar merged
    last: int
    ext: int    # raw index of the bar giving the extreme (high for up-merge, low for down-merge)

def merge_inclusion(raw):
    """raw: list of (date, high, low). Returns merged Bars.
    Direction from previous two merged bars; up: max high/max low, down: min high/min low."""
    out = []
    for i, (d, h, l) in enumerate(raw):
        b = Bar(d, h, l, i, i, i)
        if not out:
            out.append(b); continue
        p = out[-1]
        contained = (p.high >= h and p.low <= l) or (p.high <= h and p.low >= l)
        if not contained:
            out.append(b); continue
        up = True
        if len(out) >= 2:
            up = p.high > out[-2].high
        if up:
            nh, nl = max(p.high, h), max(p.low, l)
            ext = p.ext if p.high >= h else i
        else:
            nh, nl = min(p.high, h), min(p.low, l)
            ext = p.ext if p.low <= l else i
        out[-1] = Bar(p.date if False else d, nh, nl, p.first, i, ext)
    return out

def find_fractals(bars):
    """list of (idx, 'top'|'bottom') on merged bars."""
    fr = []
    for i in range(1, len(bars) - 1):
        a, b, c = bars[i-1], bars[i], bars[i+1]
        if b.high > a.high and b.high > c.high and b.low > a.low and b.low > c.low:
            fr.append((i, 'top'))
        elif b.low < a.low and b.low < c.low and b.high < a.high and b.high < c.high:
            fr.append((i, 'bottom'))
    return fr

def build_strokes(bars, min_gap=4):
    """New-stroke rule: alternating top/bottom fractals, extreme bars at least
    min_gap apart in merged index (>=5 merged bars inclusive), fractal triples don't overlap."""
    pts = []  # (idx, type, price)
    def price(i, t): return bars[i].high if t == 'top' else bars[i].low
    for i, t in find_fractals(bars):
        p = price(i, t)
        if not pts:
            pts.append((i, t, p)); continue
        li, lt, lp = pts[-1]
        if t == lt:
            if (t == 'top' and p > lp) or (t == 'bottom' and p < lp):
                pts[-1] = (i, t, p)
                # re-validate against previous point
                if len(pts) >= 2 and pts[-1][0] - pts[-2][0] < min_gap:
                    pts.pop()
            continue
        if i - li >= min_gap and ((t == 'top' and p > lp) or (t == 'bottom' and p < lp)):
            pts.append((i, t, p))
    strokes = [(pts[k], pts[k+1]) for k in range(len(pts) - 1)]
    return pts, strokes

def find_pivots(strokes):
    """Pivot: >=3 consecutive overlapping strokes. Returns (start_idx, end_idx, ZD, ZG, n_strokes)
    with idx in merged-bar index."""
    rng = [(min(a[2], b[2]), max(a[2], b[2]), a[0], b[0]) for a, b in strokes]
    res, i = [], 0
    while i + 2 < len(rng):
        zd = max(r[0] for r in rng[i:i+3]); zg = min(r[1] for r in rng[i:i+3])
        if zg > zd:
            j = i + 3
            while j < len(rng) and min(rng[j][1], zg) > max(rng[j][0], zd):
                j += 1  # stroke still touches the pivot zone; zone itself kept from first 3
            res.append((rng[i][2], rng[j-1][3], zd, zg, j - i))
            i = j
        else:
            i += 1
    return res

def analyze(raw):
    bars = merge_inclusion(raw)
    pts, strokes = build_strokes(bars)
    return bars, pts, strokes, find_pivots(strokes)

"""Chan v2: segments (feature-sequence, simplified), segment-based pivots,
MACD divergence, buy/sell points 1/2/3, multi-level resonance.
Builds on chan.py (v1: inclusion merge, fractals, new strokes) unchanged.
See DOCS_chan2.md for rules and known deviations from standard Chan theory.
Points `pts` are tuples (idx, 'top'|'bottom', price)."""
from dataclasses import dataclass
import numpy as np
from chan import analyze

@dataclass
class Seg:
    s_i: int; s_p: float; e_i: int; e_p: float
    up: bool; confirmed: bool
    s_k: int = 0; e_k: int = 0   # indexes into pts
    by_break: bool = False       # ended because price broke beyond the segment start (no feature fractal)
    @property
    def hi(self): return max(self.s_p, self.e_p)
    @property
    def lo(self): return min(self.s_p, self.e_p)

def build_segments(pts, min_strokes=3):
    """Feature-sequence segmentation (simplified, 'first-kind' fractal only).
    Up segment: opposite-direction strokes (down strokes) form feature elements (hi,lo);
    elements are merged for inclusion (up: max/max); a TOP fractal in the merged feature
    sequence ends the segment at the high point starting the middle element.
    Down segments symmetric. No gap ('second-kind') handling. Last segment, ending at the
    extreme point so far, is returned with confirmed=False.
    Fallback (documented deviation): if price breaks beyond the segment start before any feature
    fractal, the segment is closed at its extreme (by_break=True, treated as confirmed)."""
    n = len(pts); segs = []; k = 0
    while k < n - 1:
        up = pts[k][1] == 'bottom'
        merged = []; end = None; brk = None; m = k + 1
        while m + 1 < n:
            a, b = pts[m], pts[m+1]
            if (up and b[2] < pts[k][2]) or ((not up) and b[2] > pts[k][2]):
                brk = m + 1; break   # start of segment broken before a feature fractal appeared
            hi, lo = max(a[2], b[2]), min(a[2], b[2])
            el = [hi, lo, m]
            if merged:
                l = merged[-1]
                if (l[0] >= hi and l[1] <= lo) or (l[0] <= hi and l[1] >= lo):
                    if up:
                        el = [max(l[0], hi), max(l[1], lo), l[2] if l[0] >= hi else m]
                    else:
                        el = [min(l[0], hi), min(l[1], lo), l[2] if l[1] <= lo else m]
                    merged[-1] = el
                else:
                    merged.append(el)
            else:
                merged.append(el)
            if len(merged) >= 3:
                c, bb, aa = merged[-3], merged[-2], merged[-1]
                if up and bb[0] > c[0] and bb[0] > aa[0] and bb[1] > c[1] and bb[1] > aa[1]:
                    cand = bb[2]
                    if cand - k >= min_strokes and pts[cand][2] > pts[k][2]:
                        end = cand; break
                if (not up) and bb[1] < c[1] and bb[1] < aa[1] and bb[0] < c[0] and bb[0] < aa[0]:
                    cand = bb[2]
                    if cand - k >= min_strokes and pts[cand][2] < pts[k][2]:
                        end = cand; break
            m += 2
        if end is not None:
            segs.append(Seg(pts[k][0], pts[k][2], pts[end][0], pts[end][2], up, True, k, end))
            k = end
        elif brk is not None:
            typ = 'top' if up else 'bottom'
            cands = [x for x in range(k+1, brk) if pts[x][1] == typ]
            e = (max(cands, key=lambda x: pts[x][2]) if up else min(cands, key=lambda x: pts[x][2])) if cands else None
            if e is not None and e - k >= min_strokes and ((up and pts[e][2] > pts[k][2]) or ((not up) and pts[e][2] < pts[k][2])):
                segs.append(Seg(pts[k][0], pts[k][2], pts[e][0], pts[e][2], up, True, k, e, by_break=True))
                k = e
            else:
                k = brk   # too short / invalid: restart from the more extreme start point
        else:
            typ = 'top' if up else 'bottom'
            cands = [x for x in range(k+1, n) if pts[x][1] == typ and
                     ((up and pts[x][2] > pts[k][2]) or ((not up) and pts[x][2] < pts[k][2]))]
            if cands:
                e = max(cands, key=lambda x: pts[x][2]) if up else min(cands, key=lambda x: pts[x][2])
                segs.append(Seg(pts[k][0], pts[k][2], pts[e][0], pts[e][2], up, False, k, e))
            break
    return segs

def build_pivots(segs):
    """Segment pivots. Three consecutive overlapping segments i..i+2 give ZG=min(highs),
    ZD=max(lows) (fixed afterwards). Later segments extend it unless an UP seg ends > ZG
    (resp. DOWN seg ends < ZD) AND the next (pullback) seg ends still > ZG (< ZD): then the
    pivot is left (leave seg = that seg; pullback = third-type point). If the leave seg is last,
    pullback is pending. Next pivot search restarts at the pullback seg (leave+1)."""
    res = []; i = 0; n = len(segs)
    while i + 2 < n:
        s = segs[i:i+3]
        zd = max(x.lo for x in s); zg = min(x.hi for x in s)
        if zg <= zd:
            i += 1; continue
        last = i + 2; j = i + 3; leave = None; third = False; exits = []
        while j < n:
            sj = segs[j]
            up_leave = sj.up and sj.e_p > zg
            dn_leave = (not sj.up) and sj.e_p < zd
            if up_leave or dn_leave:
                exits.append(j)
                if j + 1 < n:
                    nx = segs[j+1]
                    if (up_leave and nx.e_p > zg) or (dn_leave and nx.e_p < zd):
                        leave = j; third = True; break
                    last = j + 1; j += 2; continue
                leave = j; break
            last = j; j += 1
        res.append(dict(first=i, last=last, zg=zg, zd=zd, enter=i-1 if i > 0 else None,
                        leave=leave, leave_up=(segs[leave].up if leave is not None else None),
                        third=third, n_segs=last - i + 1, exits=exits))
        if leave is None: break
        i = leave + 1
    return res

def macd(close, fast=12, slow=26, sig=9):
    c = np.asarray(close, float)
    def ema(x, n):
        a = 2/(n+1); o = np.empty_like(x); o[0] = x[0]
        for t in range(1, len(x)): o[t] = a*x[t] + (1-a)*o[t-1]
        return o
    dif = ema(c, fast) - ema(c, slow); dea = ema(dif, sig)
    return dif, dea, dif - dea

def make_area_fn(hist, dif):
    def f(i0, i1, up):
        h = hist[i0:i1+1]; d = dif[i0:i1+1]
        if len(h) == 0: return 0.0, 0.0
        return (float(np.maximum(h, 0).sum()), float(d.max())) if up else \
               (float(np.maximum(-h, 0).sum()), float(d.min()))
    return f

def find_signals(segs, pivots, area_fn, level=None):
    """Return list of signal dicts (type in 1B,1S,2B,2S,3B,3S, plus PRE_1B... pre-signals
    and BC_B/BC_S on 30m only). Time/price = extreme point.
    level: 'weekly' | 'daily' | '30m' | None. BC (盘整背驰) signals are ONLY generated
      when level == '30m' (user decision 2026-10-13: daily/weekly BC is a dead signal).
    Pre-signals (2026-10-13 opt): classic 1/2/3 patterns whose exit segment is not yet
      confirmed (confirmed=False) are emitted as PRE_1B/PRE_1S/... instead of the raw
      unconfirmed signal. They are explicitly repaintable (may vanish on later refits);
      backtest maps them to half-size watch positions, topped up when the confirmed
      signal later appears.
    Rules:
    1B/1S: pivot P with previous pivot P' lower (P.zg < P'.zd) [higher for 1S], P left downward
      (upward), entering seg same direction as leave seg, leave end beyond entering end, and
      MACD area(leave) < area(enter) -> trend divergence.
    2B/2S: after 1B/1S at seg L: next opposite seg then a seg back toward the extreme that ends
      above (below) L's end -> 2B (2S).
    3B/3S: pivot left with pullback seg end still above ZG (below ZD)."""
    out = []
    def mk(typ, seg, idx, **kw):
        d = dict(type=typ, idx=seg.e_i, price=seg.e_p, confirmed=seg.confirmed, seg=idx)
        d.update(kw); return d
    def pre_typ(base, seg):
        """Return (type_name, is_pre): unconfirmed classic signals become PRE_* pre-signals."""
        if seg.confirmed:
            return base, False
        return 'PRE_' + base, True
    for pi, P in enumerate(pivots):
        if P['enter'] is None or pi == 0: continue
        prev = pivots[pi-1]; en = segs[P['enter']]
        for ex in P['exits']:
            lv = segs[ex]
            if lv.up != en.up: continue
            if not lv.up and P['zg'] < prev['zd'] and lv.e_p < en.e_p:
                a_en, d_en = area_fn(en.s_i, en.e_i, False); a_lv, d_lv = area_fn(lv.s_i, lv.e_i, False)
                if a_lv < a_en:
                    typ, is_pre = pre_typ('1B', lv)
                    out.append(mk(typ, lv, ex, area_enter=a_en, area_leave=a_lv,
                                  ratio=a_lv/a_en if a_en else None, dif_enter=d_en, dif_leave=d_lv,
                                  zd=P['zd'], zg=P['zg'], pre=is_pre))
            if lv.up and P['zd'] > prev['zg'] and lv.e_p > en.e_p:
                a_en, d_en = area_fn(en.s_i, en.e_i, True); a_lv, d_lv = area_fn(lv.s_i, lv.e_i, True)
                if a_lv < a_en:
                    typ, is_pre = pre_typ('1S', lv)
                    out.append(mk(typ, lv, ex, area_enter=a_en, area_leave=a_lv,
                                  ratio=a_lv/a_en if a_en else None, dif_enter=d_en, dif_leave=d_lv,
                                  zd=P['zd'], zg=P['zg'], pre=is_pre))
    for s in list(out):
        if s['type'] not in ('1B', '1S', 'PRE_1B', 'PRE_1S'): continue
        L = s['seg']
        if L + 2 < len(segs):
            pb = segs[L+2]; ref = segs[L]
            is_buy = s['type'] in ('1B', 'PRE_1B')
            if is_buy and pb.e_p > ref.e_p:
                typ, is_pre = pre_typ('2B', pb)
                out.append(mk(typ, pb, L+2, ref_low=ref.e_p, margin_pct=100*(pb.e_p/ref.e_p-1), pre=is_pre))
            if not is_buy and pb.e_p < ref.e_p:
                typ, is_pre = pre_typ('2S', pb)
                out.append(mk(typ, pb, L+2, ref_high=ref.e_p, margin_pct=100*(1-pb.e_p/ref.e_p), pre=is_pre))
    # 盘整背驰 (consolidation divergence, 2026-10-13): pure pivot-level MACD divergence
    # on exit vs entry, without the trend-context filter required for 1B/1S.
    # BC_B: exit makes new low vs entry end, but MACD area weaker -> exhaustion, potential buy.
    # BC_S: exit makes new high vs entry end, but MACD area weaker -> exhaustion, potential sell.
    # These are weaker than 1B/1S (no trend confirmation) and scored accordingly.
    # 2026-10-13 opt: BC is ONLY generated on the 30m timeframe (dead signal on daily/weekly).
    # 2026-10-13 opt: BC signals now carry stop_price (same 3% rule as ZD_B/ZG_S).
    if level == '30m':
        for pi, P in enumerate(pivots):
            if P['enter'] is None: continue
            en = segs[P['enter']]
            for ex in P['exits']:
                lv = segs[ex]
                if lv.up != en.up: continue
                # skip if this exit already produced a 1B/1S (or its PRE_ pre-signal): avoid duplicates
                if any(s['type'] in ('1B','1S','PRE_1B','PRE_1S') and s['seg'] == ex for s in out):
                    continue
                if not lv.up and lv.e_p < en.e_p:
                    a_en, d_en = area_fn(en.s_i, en.e_i, False); a_lv, d_lv = area_fn(lv.s_i, lv.e_i, False)
                    if a_en > 0 and a_lv < a_en:
                        out.append(mk('BC_B', lv, ex, area_enter=a_en, area_leave=a_lv,
                                      ratio=a_lv/a_en, dif_enter=d_en, dif_leave=d_lv,
                                      zd=P['zd'], zg=P['zg'], kind='beichi',
                                      stop_price=round(lv.e_p * (1 - STOP_PCT), 2)))
                if lv.up and lv.e_p > en.e_p:
                    a_en, d_en = area_fn(en.s_i, en.e_i, True); a_lv, d_lv = area_fn(lv.s_i, lv.e_i, True)
                    if a_en > 0 and a_lv < a_en:
                        out.append(mk('BC_S', lv, ex, area_enter=a_en, area_leave=a_lv,
                                      ratio=a_lv/a_en, dif_enter=d_en, dif_leave=d_lv,
                                      zd=P['zd'], zg=P['zg'], kind='beichi',
                                      stop_price=round(lv.e_p * (1 + STOP_PCT), 2)))
    for P in pivots:
        if P['leave'] is not None and P['third']:
            pb = segs[P['leave']+1]
            if P['leave_up']:
                typ, is_pre = pre_typ('3B', pb)
                out.append(mk(typ, pb, P['leave']+1, zg=P['zg'], zd=P['zd'],
                              margin_pct=100*(pb.e_p/P['zg']-1), pre=is_pre))
            else:
                typ, is_pre = pre_typ('3S', pb)
                out.append(mk(typ, pb, P['leave']+1, zg=P['zg'], zd=P['zd'],
                              margin_pct=100*(1-pb.e_p/P['zd']), pre=is_pre))
    out.sort(key=lambda d: d['idx'])
    return out

def level_state(segs, pivots, last_close):
    """Direction at one level: 'up' if close > last pivot ZG, 'down' if < ZD, 'range' if inside;
    with no pivot falls back to last segment direction."""
    seg_dir = None if not segs else ('up' if segs[-1].up else 'down')
    if pivots:
        P = pivots[-1]
        pos = 'above' if last_close > P['zg'] else 'below' if last_close < P['zd'] else 'inside'
        d = {'above': 'up', 'below': 'down', 'inside': 'range'}[pos]
        return dict(direction=d, pivot_pos=pos, zg=P['zg'], zd=P['zd'], last_seg=seg_dir)
    return dict(direction=seg_dir or 'unknown', pivot_pos='none', zg=None, zd=None, last_seg=seg_dir)

def resonance(sig_type, big_states):
    """sig_type startswith buy ('B') or sell ('S'); big_states: list of level_state dicts.
    Returns 'strong' (all larger levels agree), 'partial', 'conflict' (all opposite), 'neutral'."""
    want = 'up' if sig_type.endswith('B') else 'down'
    opp = 'down' if want == 'up' else 'up'
    ds = [b['direction'] for b in big_states if b]
    if not ds: return 'n/a'
    if all(d == want for d in ds): return 'strong'
    if any(d == want for d in ds) and not any(d == opp for d in ds): return 'partial'
    if all(d == opp for d in ds): return 'conflict'
    return 'mixed' if any(d == want for d in ds) else 'neutral'

EDGE_TOL = 0.003  # 0.3%: treat high/low crossing ZG/ZD within this band as a touch
BREAK_TOL = 0.02   # 2%: a close beyond ZD/ZG by this much = pivot broken, edge signal invalid
STOP_PCT = 0.03    # 3%: stop-loss distance beyond the pivot edge for edge signals

def find_pivot_edge_signals(segs, pivots, highs, lows, closes):
    """中枢上沿卖 (ZG_S) / 中枢下沿买 (ZD_B).
    For each segment-pivot, scan bars in its active window; keep the *latest* touch
    of ZG and of ZD. A touch = bar range intersects [level*(1-tol), level*(1+tol)].
    These are heuristic edge alerts, NOT classic Chan 1/2/3 points. kind=pivot_edge.

    Validity filters (added 2026-10-13):
    - The touch bar's close must hold the edge (ZD_B: close >= ZD*(1-EDGE_TOL)).
      A close well below = breakdown, not a hold -> no signal.
    - After the touch, if any close breaks beyond the edge by BREAK_TOL
      (ZD_B: close < ZD*(1-BREAK_TOL)), the pivot is broken -> no signal.
    Each signal carries stop_price (ZD*(1-STOP_PCT) for ZD_B, ZG*(1+STOP_PCT) for ZG_S)."""
    out = []
    n = len(closes)
    if n == 0 or not pivots or not segs:
        return out
    for P in pivots:
        zg, zd = float(P["zg"]), float(P["zd"])
        if zg <= zd:
            continue
        i0 = int(segs[P["first"]].s_i)
        i1 = int(segs[P["last"]].e_i)
        if P.get("leave") is not None:
            i1 = max(i1, int(segs[P["leave"]].e_i))
        i0 = max(0, i0); i1 = min(n - 1, i1)
        last_zg = last_zd = None
        for i in range(i0, i1 + 1):
            hi, lo, cl = float(highs[i]), float(lows[i]), float(closes[i])
            if hi >= zg * (1 - EDGE_TOL) and lo <= zg * (1 + EDGE_TOL):
                last_zg = (i, cl, abs(cl - zg) / zg if zg else 0.0)
            if lo <= zd * (1 + EDGE_TOL) and hi >= zd * (1 - EDGE_TOL):
                last_zd = (i, cl, abs(cl - zd) / zd if zd else 0.0)
        if last_zg is not None:
            i, px, dist = last_zg
            # validity: touch bar must not close above the edge (breakout), and no
            # later close may break above ZG by BREAK_TOL
            broken = px > zg * (1 + EDGE_TOL)
            if not broken:
                for j in range(i, n):
                    if float(closes[j]) > zg * (1 + BREAK_TOL):
                        broken = True
                        break
            if not broken:
                out.append(dict(type="ZG_S", idx=i, price=px, confirmed=True, seg=None,
                                zg=zg, zd=zd, edge="ZG", kind="pivot_edge",
                                dist_pct=100.0 * dist, margin_pct=100.0 * (px / zg - 1.0),
                                stop_price=round(zg * (1 + STOP_PCT), 2)))
        if last_zd is not None:
            i, px, dist = last_zd
            # validity: touch bar must hold the edge (close not below), and no later
            # close may break below ZD by BREAK_TOL
            broken = px < zd * (1 - EDGE_TOL)
            if not broken:
                for j in range(i, n):
                    if float(closes[j]) < zd * (1 - BREAK_TOL):
                        broken = True
                        break
            if not broken:
                out.append(dict(type="ZD_B", idx=i, price=px, confirmed=True, seg=None,
                                zg=zg, zd=zd, edge="ZD", kind="pivot_edge",
                                dist_pct=100.0 * dist, margin_pct=100.0 * (1.0 - px / zd),
                                stop_price=round(zd * (1 - STOP_PCT), 2)))
    out.sort(key=lambda d: d["idx"])
    return out

def analyze_level(df, level=None):
    """df: DataFrame with High, Low, Close. level: 'weekly'|'daily'|'30m'|None.
    level is passed to find_signals (BC signals only fire on '30m')."""
    raw = [(d, float(r.High), float(r.Low)) for d, r in df.iterrows()]
    bars, pts_m, strokes, _ = analyze(raw)
    pts = [(bars[i].ext, t, p) for i, t, p in pts_m]
    # keep raw indexes strictly increasing
    clean = []
    for p in pts:
        if clean and p[0] <= clean[-1][0]: continue
        clean.append(p)
    pts = clean
    segs = build_segments(pts)
    pivots = build_pivots(segs)
    dif, dea, hist = macd(df['Close'].values)
    sigs = find_signals(segs, pivots, make_area_fn(hist, dif), level=level)
    for s in sigs:
        s.setdefault("kind", "chan")
    edge = find_pivot_edge_signals(segs, pivots, df["High"].values, df["Low"].values, df["Close"].values)
    sigs = sigs + edge
    sigs.sort(key=lambda d: d["idx"])
    return dict(pts=pts, segs=segs, pivots=pivots, signals=sigs,
                state=level_state(segs, pivots, float(df['Close'].iloc[-1])))


# ---------------------------------------------------------------------------
# Heuristic signal strength score (0-10). Transparent, additive, NOT backtested.
# ---------------------------------------------------------------------------
RECENT_BARS = {'weekly': 4, 'daily': 10, '30m': 40, '5m': 120}
BASE_SCORE = {'1': 3.0, '2': 4.0, '3': 3.5, 'BC': 2.5}
RESONANCE_PTS = {'strong': 1.5, 'partial': 0.75, 'neutral': 0.0, 'mixed': -0.5,
                 'conflict': -1.5, 'n/a': 0.0, None: 0.0}
UNCONFIRMED_PENALTY = -1.5
STALE_PENALTY = -4.0

def _clip(x, lo, hi): return max(lo, min(hi, x))

def score_pivot_edge(sig, level):
    """Simplified 0-10 score for ZG_S / ZD_B (kind=pivot_edge). Not backtested."""
    bd = {"base": 3.0, "divergence": 0.0}
    bd["resonance"] = RESONANCE_PTS.get(sig.get("resonance"), 0.0)
    bd["confirmed"] = 0.0 if sig.get("confirmed") else UNCONFIRMED_PENALTY
    R = RECENT_BARS[level]; age = sig.get("bars_ago", 0)
    if age > R:
        bd["freshness"] = STALE_PENALTY
    else:
        f = age / R
        bd["freshness"] = 1.0 if f <= 0.25 else 0.5 if f <= 0.5 else 0.0
    dist = sig.get("dist_pct")
    q = 0.0
    if dist is not None:
        q += 2.0 * (1.0 - _clip(float(dist) / 0.5, 0.0, 1.0))  # within 0.5% -> full +2
    zg, zd, px = sig.get("zg"), sig.get("zd"), sig.get("price")
    if zg is not None and zd is not None and px:
        q += 0.5 * _clip(((zg - zd) / px * 100) / 6.0, 0.0, 1.0)
    bd["quality"] = round(q, 2)
    raw = sum(bd.values())
    score = round(_clip(raw, 0.0, 10.0), 1)
    bd = {k: round(v, 2) for k, v in bd.items()}
    bd["raw_total"] = round(raw, 2); bd["capped"] = raw > 10 or raw < 0
    return score, bd

def score_signal(sig, level):
    """sig: signal dict as written to signals.json (type, price, confirmed, bars_ago, resonance,
    ratio, dif_enter, dif_leave, zd, zg, margin_pct). Returns (score 0-10 float, breakdown dict).
    Components (points): base, divergence, resonance, confirmed, freshness, quality.
    Pivot-edge signals (ZG_S/ZD_B, kind=pivot_edge) use score_pivot_edge()."""
    if sig.get("kind") == "pivot_edge" or sig.get("type") in ("ZG_S", "ZD_B"):
        return score_pivot_edge(sig, level)
    typ = sig['type']
    if typ.startswith('PRE_'):
        # pre-signal: half base score (unconfirmed pattern, may repaint).
        # unconfirmed penalty below applies on top.
        kind = typ[4]
        bd = {'base': BASE_SCORE[kind] / 2.0}
    else:
        kind = 'BC' if typ.startswith('BC') else typ[0]
        bd = {'base': BASE_SCORE[kind]}
    # divergence: MACD area ratio leave/enter, smaller = stronger. 1B/1S and BC carry it. 0..2.5
    r = sig.get('ratio')
    bd['divergence'] = round(2.5 * (1 - _clip(r, 0.0, 1.0)), 2) if (kind in ('1', 'BC') and r is not None) else 0.0
    bd['resonance'] = RESONANCE_PTS.get(sig.get('resonance'), 0.0)
    bd['confirmed'] = 0.0 if sig.get('confirmed') else UNCONFIRMED_PENALTY
    R = RECENT_BARS[level]; age = sig.get('bars_ago', 0)
    if age > R: bd['freshness'] = STALE_PENALTY
    else:
        f = age / R
        bd['freshness'] = 1.0 if f <= 0.25 else 0.5 if f <= 0.5 else 0.0
    # structure quality 0..1.5
    q = 0.0
    zg, zd, px = sig.get('zg'), sig.get('zd'), sig.get('price')
    if zg is not None and zd is not None and px:
        q += 0.5 * _clip(((zg - zd) / px * 100) / 6.0, 0.0, 1.0)      # pivot width >=6% of price -> 0.5
    if kind in ('2', '3') and sig.get('margin_pct') is not None:
        q += 1.0 * _clip(sig['margin_pct'] / 4.0, 0.0, 1.0)           # margin >=4% -> 1.0
    if kind in ('1', 'BC') and sig.get('dif_enter') is not None and sig.get('dif_leave') is not None:
        if abs(sig['dif_leave']) < abs(sig['dif_enter']): q += 1.0     # DIF extreme also weaker
    bd['quality'] = round(q, 2)
    raw = sum(bd.values())
    score = round(_clip(raw, 0.0, 10.0), 1)
    bd = {k: round(v, 2) for k, v in bd.items()}
    bd['raw_total'] = round(raw, 2); bd['capped'] = raw > 10 or raw < 0
    return score, bd

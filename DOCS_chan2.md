# chan2 – rules and known limitations (prototype, read-only, not investment advice)
Files: chan.py (v1, unchanged; backup chan_v1.py), chan2.py, run2.py, tests/test_chan2.py, out/*_chan2.png, out/signals.json, out/signals_summary.md.

## Pipeline per level (weekly 5y/1wk, daily 2y/1d, 30m 60d/30m from Yahoo via yfinance, unadjusted)
1. v1: inclusion merge -> fractals -> new strokes (>=5 merged bars, alternating).
2. Segments (build_segments): simplified feature-sequence method. Up segment: down strokes form feature elements (hi,lo); merge inclusions (up: max/max); a top fractal in the merged feature sequence ends the segment at the high starting the middle element; needs >=3 strokes and end beyond start. Down symmetric. NO gap ("second kind") handling. Fallback (not standard): if price breaks beyond the segment start before any fractal, close the segment at its extreme (by_break). Final segment ends at the extreme so far, confirmed=False.
3. Pivots (build_pivots): 3 consecutive overlapping segments -> ZG=min(highs), ZD=max(lows), fixed (no ZZ/GG, no pivot expansion/upgrade). Extension while segments stay in/around; "exit" = up seg ending > ZG (down seg < ZD). Leave+third point = exit followed by a pullback seg that still ends beyond ZG (ZD). Next pivot search restarts at the pullback seg.
4. Divergence: MACD(12,26,9) histogram, area = sum of positive (up) / negative (down) hist over the segment's bars; DIF extreme also stored. Divergence if area(leaving) < area(entering) while price makes a new extreme beyond the entering end.
5. Signals: 1B/1S = divergence at an exit of pivot P, requiring a previous pivot (trend: P.ZG < prev.ZD for buy; P.ZD > prev.ZG for sell) and the entering seg same direction. 2B/2S = after 1B/1S: opposite seg, then a seg that ends above(below) the 1B(1S) extreme. 3B/3S = pullback after exit that does not re-enter the pivot. No range-bound (single pivot) divergence, no interval-nesting (区间套), no 1/2 combos (类二买).
6. Time = time of the extreme bar, not the confirmation time (confirmation lags by several bars). confirmed=False means the last segment has no feature fractal yet: may repaint or vanish.
7. Multi-level: level direction = close vs last pivot (above ZG=up, below ZD=down, inside=range; no pivot -> last segment direction). Resonance of a signal vs larger levels (30m vs daily+weekly; daily vs weekly): strong / partial / mixed / neutral / conflict.

## Known limitations / deviations from standard Chan
- Segment algorithm is an approximation; real Chan has gap case and stricter characteristic-sequence rules. Results will differ from hand-drawn charts.
- Segments after the last confirmed one are only "extreme so far" and ignore any later counter-move; the "last segment" can be stale.
- Pivots use fixed ZG/ZD from first 3 segments; ZG/ZD in the pivot "exit" logic is coarse. Old pivots far from current price can still generate 3B/3S (flagged with bars_ago; 'recent' = within 4 weekly/10 daily/40 30m bars).
- Divergence uses only MACD area + price extreme; parameters not tuned or backtested. Zero backtesting; no reliability/win-rate evidence.
- 30m data: Yahoo gives only ~60 calendar days (~780 bars, regular hours) -> few pivots, 1B/2B rarely testable. SPCX/SKHY (listed 2026-06/07) have too few weekly bars (18/14) -> weekly skipped; daily history short.
- Last bar can be incomplete (today's intraday); weekly last bar is the current week.
- Yahoo is unofficial; prices unadjusted for splits/dividends (auto_adjust=False) so long history may contain split discontinuities.
- Only unit tests with hand-made data; no validation on real data against a reference implementation.


## Signal strength score (0-10) — heuristic, NOT backtested

**Disclaimer:** the score is a hand-set heuristic. It has NOT been backtested or calibrated, it is NOT a win rate or probability, and it is NOT investment advice. Weights are my judgement and can be wrong. Backup of the pre-score code: `chan2_v1.py`. Code: `score_signal()` at the end of `chan2.py`.

`score = clip(base + divergence + resonance + confirmed + freshness + quality, 0, 10)`, rounded to 0.1. `signals.json` stores `score` and `score_breakdown` (each component, `raw_total`, `capped`). Buy and sell are scored symmetrically.

| Component | Rule | Range |
|---|---|---|
| base (type) | 1B/1S = 3.0 (counter-trend, relies on divergence evidence which is added separately); 2B/2S = 4.0 (reversal already partly confirmed by a higher low/lower high); 3B/3S = 3.5 (trend continuation, pivot not re-entered) | 3.0-4.0 |
| divergence | 1B/1S only: 2.5 x (1 - MACD area ratio leave/enter), ratio clipped to [0,1]; smaller ratio = higher. 2/3 types have no ratio -> 0 | 0 to +2.5 |
| resonance | vs larger levels: strong +1.5, partial +0.75, neutral 0, mixed -0.5, conflict -1.5; n/a (weekly has no larger level) 0 | -1.5 to +1.5 |
| confirmed | unconfirmed (may repaint) -1.5 | -1.5 or 0 |
| freshness | R = recent window (weekly 4, daily 10, 30m 40 bars). age <= R/4: +1.0; <= R/2: +0.5; <= R: 0; age > R (STALE): -4.0 | -4 to +1 |
| quality | pivot width (ZG-ZD)/price: up to +0.5 (full at >=6%); 2B/3B margin_pct: up to +1.0 (full at >=4%); 1B/1S: +1.0 if |DIF| at leave < at enter (DIF also diverges) | 0 to +1.5 |

Notes: a stale signal is almost always driven to ~0-2. Theoretical max ~9.5 (1B/1S) and ~7.5 (3B), so 3B/2B signals rarely score high by design; scores are only comparable roughly, not across signal types as equal probabilities. The cap at 10 and floor at 0 are applied after summing. Quality uses only fields the detector exposes; it does not measure segment amplitude vs. ATR. Tests: `tests/test_score.py` (hand-made data: range, cap/floor, direction of each component).

Re-run with cached data (no download): `CACHED=1 .venv/bin/python run2.py` (the existing `.venv` has pandas/matplotlib).


## Pivot-edge signals (中枢上沿买 / 下沿卖) — `kind=pivot_edge`

**Disclaimer:** heuristic edge alerts, not classic Chan 1/2/3 points, not backtested, not investment advice.

| Type | Label | Rule |
|---|---|---|
| `ZG_B` | 中枢上沿买 | Within a segment-pivot's active bar window, the latest bar whose range intersects ZG ± 0.3% (`EDGE_TOL`). Price near/at upper edge → buy hint. |
| `ZD_S` | 中枢下沿卖 | Same window; latest bar intersecting ZD ± 0.3% → sell hint. |

- Emitted alongside classic 1B/2B/3B/1S/2S/3S; each signal has `kind` (`chan` or `pivot_edge`), plus `edge` (`ZG`/`ZD`) and `dist_pct` (close vs edge, %).
- At most one `ZG_B` and one `ZD_S` **per pivot** (latest touch kept).
- Score uses `score_pivot_edge()`: base 3.0 + resonance + confirmed + freshness + quality (proximity up to +2, pivot width up to +0.5). Cap 0–10. No MACD divergence term.
- Web UI styles them with cyan/amber chips (`chip-edge-buy` / `chip-edge-sell`), distinct from red/green Chan chips. Interactive chart markers use circles (Chan uses arrows).

### Limitations
- Tolerance 0.3% is arbitrary; noisy markets may spam touches on large pivots.
- Uses high/low range intersection, not order-book / wick filters; incomplete last bar may trigger.
- Does not require price to reverse after the edge; it is a proximity alert only.
- Still approximate pivots from the simplified segment algorithm.

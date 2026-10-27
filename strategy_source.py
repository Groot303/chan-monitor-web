"""美股自动模拟的独立输入：真实采集下界、已收盘数据、原检测器。"""
import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from chan2 import analyze_level
from paper_market import ExchangeSessions
from paper_trading import timestamp
from signal_safety import measured_regime, regime_decision, unknown_regime

SCHEMA = 'us-strategy-source-v1'
FINALITY_MINUTES = 15
MAX_SOURCE_AGE_MINUTES = 45


def frame_rows(frame):
    if frame is None:
        return []
    return [dict(time=t.isoformat(), **{k.lower(): float(row[k]) for k in ('Open','High','Low','Close')})
            for t, row in frame.iterrows()]


def build_source(frames, benchmark, observed_at, generated):
    """observed_at 是请求前服务器时间，不是信号首次可识别时间。缓存无此证据。"""
    symbols = sorted(set(frames.get('daily', {})) | set(frames.get('30m', {})))
    return dict(schema=SCHEMA, observed_at=observed_at, generated=generated, benchmark=benchmark,
                symbols={s: {lv: frame_rows(frames.get(lv, {}).get(s)) for lv in ('daily','30m')}
                         for s in symbols if re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}', s)})


class FileStrategySource:
    def __init__(self, path, sessions=None):
        self.path = path
        self.sessions = sessions or ExchangeSessions()
        self.cached = None

    def _session(self, day):
        return self.sessions.session('us', day.isoformat())

    def closed_frame(self, rows, level, cutoff, minimum=40):
        """严格校验完整的常规交易时段；缺口、重复、无日历时不决策。"""
        values, labels, ends = [], [], []
        previous = None
        for row in rows:
            label = timestamp(row['time'])
            if previous and label <= previous:
                raise ValueError('行情重复或乱序')
            previous = label
            day = label.astimezone(ZoneInfo('America/New_York')).date()
            session = self._session(day)
            if not session:
                raise ValueError('交易日历缺失或行情日期异常')
            start, end, _ = session
            if level == '30m':
                if not start <= label < end:
                    continue  # 盘前盘后不参与此模拟策略
                if (label-start).total_seconds() % 1800:
                    raise ValueError('30分钟标签未对齐常规开盘')
                end = min(label+timedelta(minutes=30), end)
            if end > cutoff:
                continue
            prices = [float(row[k]) for k in ('open','high','low','close')]
            op, hi, lo, cl = prices
            if not all(math.isfinite(x) and x > 0 for x in prices) or not lo <= min(op,cl) <= max(op,cl) <= hi:
                raise ValueError('行情价格缺失或无效')
            labels.append(label); values.append(prices); ends.append(end)
        if len(labels) < minimum:
            raise ValueError('已完成行情不足')
        expected = []
        day = labels[0].astimezone(ZoneInfo('America/New_York')).date()
        last_day = cutoff.astimezone(ZoneInfo('America/New_York')).date()
        while day <= last_day:
            session = self._session(day)
            if session:
                start, end, _ = session
                if level == 'daily':
                    if end <= cutoff: expected.append(end)
                else:
                    cursor = start
                    while cursor < end:
                        close = min(cursor+timedelta(minutes=30),end)
                        if close <= cutoff and close >= ends[0]: expected.append(close)
                        cursor = close
            day += timedelta(days=1)
        if ends != expected:
            raise ValueError('常规时段行情存在缺口或尾部未更新')
        return pd.DataFrame(values, columns=['Open','High','Low','Close'], index=pd.DatetimeIndex(labels))

    def read(self, now):
        try:
            raw = self.path.read_bytes()
            source = json.loads(raw)
            if not isinstance(source,dict) or source.get('schema') != SCHEMA:
                raise ValueError('缺少自动策略数据契约')
            if not isinstance(source.get('symbols'),dict):
                raise ValueError('标的行情结构无效')
            observed = timestamp(source['observed_at'])
            if not timedelta(0) <= now-observed <= timedelta(minutes=MAX_SOURCE_AGE_MINUTES):
                raise ValueError('数据采集时间过期或超前')
            digest = hashlib.sha256(raw).hexdigest()
            if self.cached and self.cached['id'] == digest:
                return self.cached
            cutoff = observed-timedelta(minutes=FINALITY_MINUTES)
            benchmark = source.get('benchmark') or {}
            try:
                benchmark_cutoff = min(cutoff, timestamp(benchmark['observed_at'])-timedelta(minutes=FINALITY_MINUTES))
                frame = self.closed_frame(benchmark['bars'], 'daily', benchmark_cutoff, minimum=210)
                regime = measured_regime('SPY', frame.Close, bar_complete=True)
            except (ValueError, KeyError, TypeError, OverflowError) as exc:
                regime = unknown_regime('SPY', exc)
            snapshot = dict(id=digest, observed_at=observed.isoformat(), cutoff=cutoff.isoformat(),
                            regime=regime, context=regime_decision(regime), symbols={})
            for symbol, levels in source.get('symbols', {}).items():
                if not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}', symbol): continue
                try:
                    daily = self.closed_frame(levels['daily'], 'daily', cutoff)
                    frame = self.closed_frame(levels['30m'], '30m', cutoff)
                    direction = analyze_level(daily, level='daily')['state']['direction']
                    result = analyze_level(frame, level='30m')
                    signals = []
                    for raw_signal in result['signals']:
                        signal = dict(raw_signal)
                        signal['signal_bar_time'] = frame.index[signal.pop('idx')].isoformat()
                        signal.pop('seg', None)
                        signals.append(signal)
                    snapshot['symbols'][symbol] = dict(valid=True, direction=direction, signals=signals,
                        last_completed_bar=frame.index[-1].isoformat())
                except (ValueError, KeyError, TypeError, OverflowError) as exc:
                    snapshot['symbols'][symbol] = dict(valid=False, reason=str(exc)[:160])
            self.cached = snapshot
            return snapshot
        except OSError:
            return dict(id=None, symbols={}, error='等待新的美股策略行情发布',regime=unknown_regime('SPY','source unavailable'))
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            return dict(id=None, symbols={}, error=str(exc)[:160], regime=unknown_regime('SPY', exc))

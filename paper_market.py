"""Paper-only adapter over the existing exported charts. Fail closed on ambiguity."""
import json
import math
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from paper_trading import timestamp


class ExchangeSessions:
    def __init__(self):
        self.calendars = {}
        self.session_records = {}

    def session(self, market, day):
        key=(market,day)
        if key in self.session_records: return self.session_records[key]
        result=self._session(market,day)
        self.session_records[key]=result
        return result

    def _session(self, market, day):
        try:
            import exchange_calendars as xc
            if market not in self.calendars:
                self.calendars[market] = xc.get_calendar('XNYS' if market=='us' else 'XSHG')
            cal = self.calendars[market]
            if not cal.is_session(day): return None
            start, end = cal.session_open(day).to_pydatetime(), cal.session_close(day).to_pydatetime()
            bs, be = cal.session_break_start(day), cal.session_break_end(day)
            pause = None if str(bs)=='NaT' else (bs.to_pydatetime(),be.to_pydatetime())
            return start,end,pause
        except Exception:
            return None

    def valid(self, market, opened, closed):
        day = opened.astimezone(ZoneInfo('America/New_York' if market=='us' else 'Asia/Shanghai')).date().isoformat()
        session = self.session(market,day)
        if not session or closed-opened != timedelta(minutes=5): return None
        start,end,pause=session
        if not start<=opened<closed<=end: return None
        if pause and opened<pause[1] and closed>pause[0]: return None
        return day

    def fresh(self, market, closed, now):
        zone = ZoneInfo('America/New_York' if market=='us' else 'Asia/Shanghai')
        day = now.astimezone(zone).date()
        for offset in range(12):
            session = self.session(market,(day-timedelta(days=offset)).isoformat())
            if not session: continue
            start,end,pause=session
            if now<=start: continue
            expected=min(now,end)
            if pause and pause[0]<=now<=pause[1]: expected=pause[0]
            return timedelta(0)<=expected-closed<=timedelta(minutes=30)
        return False


class FileMarketData:
    CN_EQUITIES = {'万向钱潮','三花智控','三孚股份','诺德股份'}

    def __init__(self, data_root, sessions=None):
        self.root = data_root
        self.sessions = sessions or ExchangeSessions()

    def read(self, path):
        try:
            data=json.loads((self.root / path).read_text(encoding='utf-8'))
            return data if isinstance(data,dict) else {}
        except (OSError,ValueError): return {}

    def signal_snapshot(self, market, symbol):
        snapshot=self.read('signals.json' if market=='us' else 'signals_cn.json')
        return {'captured_from_generated':snapshot.get('generated'),'symbol':symbol,
                'signals':[s for s in snapshot.get('signals',[]) if s.get('symbol')==symbol][:200],
                'symbol_state':snapshot.get('symbols',{}).get(symbol),
                'regime':snapshot.get('regime'), 'strategy_context':snapshot.get('strategy_context'),
                'meaning':'server_snapshot_at_manual_order_not_historic_first_seen'}

    def allowed(self, market, symbol):
        if not isinstance(symbol,str): return False
        snapshot=self.read('signals.json' if market=='us' else 'signals_cn.json')
        if symbol not in snapshot.get('symbols',{}): return False
        if market=='cn': return symbol in self.CN_EQUITIES
        return bool(re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}',symbol))

    def bars(self, market, symbol, now):
        if not isinstance(symbol,str) or '/' in symbol or '\\' in symbol or '..' in symbol: return []
        chart=self.read(('charts/' if market=='us' else 'charts_cn/')+symbol+'.json')
        levels=chart.get('levels')
        level=levels.get('5m') if isinstance(levels,dict) else None
        raw=level.get('ohlc') if isinstance(level,dict) else None
        if not isinstance(raw,list): return []
        result=[]
        for row in raw:
            try:
                if type(row['time']) not in (int,float): return []
                label=datetime.fromtimestamp(row['time'],timezone.utc)
                # Alpaca/Yahoo US labels are starts; EastMoney/Sina CN intraday labels are ends.
                opened=label if market=='us' else label-timedelta(minutes=5)
                closed=opened+timedelta(minutes=5)
                if closed>now: continue
                day=self.sessions.valid(market,opened,closed)
                prices=[float(row[k]) for k in ('open','high','low','close')]
                if not day: continue
                if not all(math.isfinite(x) and x>0 for x in prices): return []
                op,hi,lo,cl=prices
                if not lo<=min(op,cl)<=max(op,cl)<=hi: return []
                result.append({'open_time':opened.isoformat(),'close_time':closed.isoformat(),
                               'session_day':day,'open':op,'close':cl,'high':hi,'low':lo})
            except (KeyError,ValueError,TypeError,OverflowError): return []
        # Duplicate timestamps or disorder are ambiguous, rather than silently repaired.
        if any(timestamp(b['open_time'])<=timestamp(a['open_time']) for a,b in zip(result,result[1:])): return []
        return result

    def quote(self, market, symbol, now):
        if not self.allowed(market,symbol): return None
        return self._quote(market,symbol,now)

    def _quote(self, market, symbol, now):
        bars=self.bars(market,symbol,now)
        if not bars: return None
        last=bars[-1]
        return {'price':last['close'],'time':last['close_time'],
                'fresh':self.sessions.fresh(market,timestamp(last['close_time']),now),
                'constraint_note':'A股撮合须有当日涨跌停及停牌证据；缺失时订单继续等待' if market=='cn' else ''}

    def benchmark(self, market, now):
        return self._quote(market,'纳指' if market=='us' else '上证指数',now)

    def execution_bars(self, market, symbol, submitted, now, *, include_blocked=False):
        if not self.allowed(market,symbol): return [],'标的不支持模拟交易或行情缺失'
        bars=self.bars(market,symbol,now)
        if not bars: return [],'等待已完成行情及交易日历'
        if timestamp(bars[0]['open_time'])>submitted:
            return [],'历史行情有缺口，等待核验；不会跳过缺失区间回填成交'
        rules=self.read('paper_cn_rules.json') if market=='cn' else {}
        eligible=[]
        by_open={timestamp(bar['open_time']):bar for bar in bars}
        cursor=datetime.fromtimestamp((int(submitted.timestamp())//300+1)*300,timezone.utc)
        # Only a continuous, classified history may advance an order. Missing IEX
        # bars cannot silently become a later, more convenient entry price.
        while cursor+timedelta(minutes=5)<=now:
            opened=cursor;cursor+=timedelta(minutes=5)
            day=self.sessions.valid(market,opened,cursor)
            if not day: continue
            bar=by_open.get(opened)
            if bar is None: return eligible,'常规交易时段行情有缺口，暂停撮合等待核验'
            tradable=bar['high']>bar['low']
            if market=='cn':
                rule=rules.get(bar['session_day'],{}).get(symbol,{})
                try:
                    upper,lower=float(rule['upper_limit']),float(rule['lower_limit'])
                    if not (bool(rule.get('source')) and type(rule.get('suspended')) is bool and
                            timestamp(rule['observed_at'])<=opened and 0<lower<upper and math.isfinite(upper)):
                        return eligible,'缺少可核验的当日A股交易约束数据'
                    tradable = tradable and rule['suspended'] is False and lower<bar['open']<upper
                except (KeyError,ValueError,TypeError): return eligible,'等待A股当日涨跌停及停牌证据'
            if tradable or include_blocked:
                eligible.append({**bar,'tradable':tradable,'constraint_evidence':
                    {**rules[bar['session_day']][symbol],'upper_limit':upper,'lower_limit':lower} if market=='cn' else 'regular_session_nonflat_bar'})
        return eligible,'等待下一可成交开盘；A股须核验T+1、停牌与价格限制' if market=='cn' else '等待提交后的常规交易时段K线'

    def stop_bars(self, market, symbol, since, now):
        # Include a bar opening exactly at the previous closed-bar boundary.
        return self.execution_bars(market,symbol,since-timedelta(microseconds=1),now,include_blocked=True)

    def stop_amendment_safe(self, market, symbol, since, now):
        bars=self.bars(market,symbol,now)
        if not bars or not self.allowed(market,symbol) or not self.sessions.fresh(market,timestamp(bars[-1]['close_time']),now):
            return False
        seen={timestamp(bar['open_time']) for bar in bars}
        cursor=datetime.fromtimestamp(math.ceil(since.timestamp()/300)*300,timezone.utc)
        while cursor+timedelta(minutes=5)<=now:
            end=cursor+timedelta(minutes=5)
            if self.sessions.valid(market,cursor,end) and cursor not in seen: return False
            cursor=end
        return True

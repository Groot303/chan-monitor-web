"""Server-owned manual paper ledger. No broker connectivity or real orders."""
import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


class PaperError(ValueError):
    pass


def money(value):
    amount=Decimal(str(value))
    if not amount.is_finite(): raise PaperError('金额或价格不是有效数值')
    return float(amount.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def timestamp(value):
    t = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise PaperError('时间必须包含时区')
    return t.astimezone(timezone.utc)


def costs(market, side, qty, price):
    notional = Decimal(str(money(Decimal(qty) * Decimal(str(price)))))
    commission = max(Decimal('1'),Decimal(qty)*Decimal('.005')) if market=='us' else max(Decimal('5'),notional*Decimal('.0003'))
    tax = money(notional*Decimal('.0005')) if market=='cn' and side=='sell' else 0
    return money(Decimal(str(money(commission)))+Decimal(str(tax)))


class PaperStore:
    def __init__(self, path, market_data, clock=None):
        self.path, self.market_data = path, market_data
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @contextmanager
    def db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        con = sqlite3.connect(self.path, timeout=15)
        self.path.chmod(0o600)
        con.row_factory = sqlite3.Row
        try:
            con.executescript('''
            CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY, token_hash TEXT UNIQUE,
              market TEXT, created TEXT, initial REAL, cash REAL);
            CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY, account TEXT, request_key TEXT,
              symbol TEXT, side TEXT, qty INTEGER, submitted TEXT, status TEXT,
              reserve REAL, reason TEXT, plan_stop REAL, signal_json TEXT, message TEXT,
              UNIQUE(account,request_key));
            CREATE TABLE IF NOT EXISTS lots(id INTEGER PRIMARY KEY, account TEXT, symbol TEXT,
              qty INTEGER, remaining INTEGER, cost REAL, basis_remaining REAL, acquired_day TEXT);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, account TEXT, time TEXT,
              kind TEXT, payload TEXT);
            CREATE TABLE IF NOT EXISTS equity(id INTEGER PRIMARY KEY, account TEXT, time TEXT,
              value REAL, benchmark REAL, UNIQUE(account,time));
            CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
              BEGIN SELECT RAISE(ABORT,'immutable events'); END;
            CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
              BEGIN SELECT RAISE(ABORT,'immutable events'); END;
            ''')
            con.execute('BEGIN IMMEDIATE')
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def event(self, db, account, kind, payload, at=None):
        db.execute('INSERT INTO events(account,time,kind,payload) VALUES(?,?,?,?)',
                   (account, (at or self.clock()).isoformat(), kind, json.dumps(payload, ensure_ascii=False)))

    def account(self, db, token):
        if not isinstance(token, str) or len(token) < 32:
            raise PaperError('练习账户凭据无效')
        row = db.execute('SELECT * FROM accounts WHERE token_hash=?',
                         (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if row is None:
            raise PaperError('练习账户凭据无效')
        return dict(row)

    def create(self, market, initial):
        if market not in ('us', 'cn') or isinstance(initial, bool):
            raise PaperError('账户参数不正确')
        try:
            initial = money(initial)
        except Exception:
            raise PaperError('初始资金不正确')
        if not 1000 <= initial <= 10000000:
            raise PaperError('初始资金需为 1,000 至 10,000,000')
        token, aid = secrets.token_urlsafe(32), secrets.token_hex(16)
        now = self.clock().isoformat()
        with self.db() as db:
            recent=(self.clock()-timedelta(minutes=1)).isoformat()
            if db.execute('SELECT COUNT(*) FROM accounts WHERE created>?',(recent,)).fetchone()[0]>=5:
                raise PaperError('创建过于频繁，请稍后重试')
            if db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0] >= 1000:
                raise PaperError('练习账户数量已达服务上限')
            db.execute('INSERT INTO accounts VALUES(?,?,?,?,?,?)',
                       (aid, hashlib.sha256(token.encode()).hexdigest(), market, now, initial, initial))
            self.event(db, aid, 'account_created', {'market': market, 'initial': initial, 'model': 'paper-v1-5bps'})
            db.execute('INSERT INTO equity(account,time,value) VALUES(?,?,?)', (aid, now, initial))
        return {'token': token, 'market': market, 'initial': initial}

    def positions(self, db, aid):
        return [dict(r) for r in db.execute('SELECT symbol,SUM(remaining) qty,SUM(basis_remaining) basis '
                'FROM lots WHERE account=? AND remaining>0 GROUP BY symbol', (aid,))]

    def preview(self, db, a, symbol, side, qty):
        if not isinstance(symbol, str) or len(symbol) > 40 or side not in ('buy', 'sell'):
            raise PaperError('订单参数不正确')
        if type(qty) is not int or not 1 <= qty <= 1000000:
            raise PaperError('数量必须为正整数')
        if a['market'] == 'cn' and qty % 100:
            raise PaperError('A股练习单须为100股整数倍')
        quote = self.market_data.quote(a['market'], symbol, self.clock())
        if not quote or not quote.get('fresh') or quote.get('price', 0) <= 0:
            raise PaperError('没有可核验的已完成行情，暂不能提交')
        reserve = money(qty * quote['price'] * 1.05 + costs(a['market'], side, qty, quote['price'] * 1.05))
        if side == 'buy':
            reserved = db.execute("SELECT COALESCE(SUM(reserve),0) FROM orders WHERE account=? AND status='pending' AND side='buy'", (a['id'],)).fetchone()[0]
            if reserve > money(a['cash'] - reserved):
                raise PaperError('可用模拟资金不足（含5%跳空预留）')
        else:
            owned = db.execute('SELECT COALESCE(SUM(remaining),0) FROM lots WHERE account=? AND symbol=?', (a['id'], symbol)).fetchone()[0]
            queued = db.execute("SELECT COALESCE(SUM(qty),0) FROM orders WHERE account=? AND symbol=? AND status='pending' AND side='sell'", (a['id'], symbol)).fetchone()[0]
            if qty > owned - queued:
                raise PaperError('可卖模拟持仓不足')
        return {'reference_price': quote['price'], 'quote_time': quote['time'], 'reserve': reserve,
                'estimated_fee': costs(a['market'], side, qty, quote['price']),
                'estimated_notional': money(qty * quote['price']), 'slippage_bps': 5,
                'constraint_note': quote.get('constraint_note', ''), 'model': 'paper-v1-5bps'}

    def order(self, token, payload):
        with self.db() as db:
            a = self.account(db, token)
            self.reconcile(db, a)
            a = self.account(db, token)
            key = payload.get('request_key')
            if not isinstance(key, str) or not 16 <= len(key) <= 100:
                raise PaperError('缺少订单幂等编号')
            old = db.execute('SELECT * FROM orders WHERE account=? AND request_key=?', (a['id'], key)).fetchone()
            if old:
                if any(payload.get(k) != old[k] for k in ('symbol', 'side', 'qty', 'reason', 'plan_stop')):
                    raise PaperError('同一幂等编号不能更改订单')
                return dict(old)
            if db.execute('SELECT COUNT(*) FROM orders WHERE account=?',(a['id'],)).fetchone()[0]>=10000:
                raise PaperError('账户练习单数量已达上限')
            if db.execute("SELECT COUNT(*) FROM orders WHERE account=? AND status='pending'",(a['id'],)).fetchone()[0]>=50:
                raise PaperError('最多保留50笔待成交单')
            symbol, side, qty = (payload.get(k) for k in ('symbol', 'side', 'qty'))
            p = self.preview(db, a, symbol, side, qty)
            reason, stop = payload.get('reason', ''), payload.get('plan_stop')
            if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
                raise PaperError('请填写1至500字练习理由')
            if stop is not None:
                if type(stop) not in (int, float) or not 0 < stop < p['reference_price'] or side != 'buy':
                    raise PaperError('计划止损须为低于参考价的正数；它仅作复盘记录')
            oid, now = secrets.token_hex(16), self.clock().isoformat()
            snapshot = self.market_data.signal_snapshot(a['market'], symbol)
            db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (oid,a['id'],key,symbol,side,qty,now,'pending',p['reserve'] if side=='buy' else 0,
                        reason,stop,json.dumps(snapshot,ensure_ascii=False),'等待提交后的可成交行情'))
            self.event(db,a['id'],'order_submitted',{'id':oid,'symbol':symbol,'side':side,'qty':qty,
                       'reason':reason,'plan_stop':stop,'signal_snapshot':snapshot,'preview':p})
            return dict(db.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone())

    def preview_order(self, token, payload):
        with self.db() as db:
            a = self.account(db, token)
            self.reconcile(db, a)
            return self.preview(db,self.account(db,token),payload.get('symbol'),payload.get('side'),payload.get('qty'))

    def cancel(self, token, oid):
        with self.db() as db:
            a = self.account(db, token)
            self.reconcile(db, a)
            row = db.execute('SELECT * FROM orders WHERE id=? AND account=?',(oid,a['id'])).fetchone()
            if row is None or row['status'] != 'pending':
                raise PaperError('该订单已成交或不可撤销')
            db.execute("UPDATE orders SET status='canceled',message='用户撤单' WHERE id=?",(oid,))
            self.event(db,a['id'],'order_canceled',{'id':oid})

    def reconcile(self, db, a):
        now = self.clock()
        previous_fills = [json.loads(r['payload']) for r in db.execute(
            "SELECT payload FROM events WHERE account=? AND kind='fill'", (a['id'],))]
        latest_filled_open = max((timestamp(f['market_bar']['open_time']) for f in previous_fills), default=None)
        pending = list(db.execute("SELECT * FROM orders WHERE account=? AND status='pending' ORDER BY submitted,rowid",(a['id'],)))
        timeline=[]
        for order in pending:
            submitted = timestamp(order['submitted'])
            if (now-submitted).total_seconds() > 7*86400:
                db.execute("UPDATE orders SET status='rejected',message='订单7天到期' WHERE id=?",(order['id'],))
                self.event(db,a['id'],'order_rejected',{'id':order['id'],'reason':'expired'})
                continue
            bars, note = self.market_data.execution_bars(a['market'],order['symbol'],submitted,now)
            db.execute('UPDATE orders SET message=? WHERE id=?',(note,order['id']))
            for bar in bars:
                timeline.append((timestamp(bar['open_time']),order['submitted'],order['id'],dict(order),bar))
        for _, _, _, order, bar in sorted(timeline,key=lambda x:x[:3]):
            if db.execute('SELECT status FROM orders WHERE id=?',(order['id'],)).fetchone()[0]!='pending':
                continue
            submitted=timestamp(order['submitted'])
            # Hard contract even when a provider implementation is replaced.
            opened, closed = timestamp(bar['open_time']), timestamp(bar['close_time'])
            if not (submitted < opened < closed <= now) or bar.get('tradable') is not True:
                continue
            if latest_filled_open and opened < latest_filled_open:
                db.execute("UPDATE orders SET status='rejected',message='历史行情后到，已有更晚成交，需人工复盘' WHERE id=?",(order['id'],))
                self.event(db,a['id'],'order_rejected',{'id':order['id'],'reason':'late_history_would_reorder_ledger'})
                continue
            qty, side = order['qty'], order['side']
            lots = list(db.execute('SELECT * FROM lots WHERE account=? AND symbol=? AND remaining>0 ORDER BY id', (a['id'],order['symbol'])))
            sellable = [l for l in lots if a['market']=='us' or l['acquired_day'] < bar['session_day']]
            if side=='sell' and sum(l['remaining'] for l in sellable) < qty:
                continue  # A股T+1：仍等待后续交易日，不回填当天成交。
            price = money(Decimal(str(bar['open'])) * Decimal('1.0005' if side=='buy' else '.9995'))
            if price<=0: continue
            if a['market']=='cn':
                limits=bar.get('constraint_evidence',{})
                if not limits.get('lower_limit',float('inf'))<=price<=limits.get('upper_limit',0): continue
            fee = costs(a['market'],side,qty,price)
            amount = money(qty*price)
            current_cash = db.execute('SELECT cash FROM accounts WHERE id=?',(a['id'],)).fetchone()[0]
            other_reserved = db.execute("SELECT COALESCE(SUM(reserve),0) FROM orders WHERE account=? AND status='pending' AND side='buy' AND id!=?",(a['id'],order['id'])).fetchone()[0]
            if side=='buy' and money(amount+fee) > money(current_cash-other_reserved):
                db.execute("UPDATE orders SET status='rejected',message='跳空后资金不足' WHERE id=?",(order['id'],))
                self.event(db,a['id'],'order_rejected',{'id':order['id'],'reason':'insufficient_cash_at_open'})
                continue
            realized = 0
            if side=='buy':
                db.execute('INSERT INTO lots(account,symbol,qty,remaining,cost,basis_remaining,acquired_day) VALUES(?,?,?,?,?,?,?)',
                           (a['id'],order['symbol'],qty,qty,(amount+fee)/qty,money(amount+fee),bar['session_day']))
                cash = money(current_cash-amount-fee)
            else:
                need, basis = qty, 0
                for lot in sellable:
                    take = min(need,lot['remaining'])
                    allocated = money(Decimal(str(lot['basis_remaining']))*Decimal(take)/Decimal(lot['remaining']))
                    basis += allocated
                    db.execute('UPDATE lots SET remaining=remaining-?,basis_remaining=? WHERE id=?',
                               (take,money(lot['basis_remaining']-allocated),lot['id']))
                    need -= take
                    if not need: break
                realized = money(amount-fee-basis)
                cash = money(current_cash+amount-fee)
            db.execute('UPDATE accounts SET cash=? WHERE id=?',(cash,a['id']))
            db.execute("UPDATE orders SET status='filled',message='按后续已完成K线开盘价模拟成交' WHERE id=?",(order['id'],))
            self.event(db,a['id'],'fill',{'order_id':order['id'],'symbol':order['symbol'],'side':side,'qty':qty,
                'price':price,'fee':fee,'realized_pnl':realized,'market_bar':bar,
                'recorded_at':now.isoformat(),'model':'paper-v1-5bps'},at=opened)
            latest_filled_open = opened
            continue
    def state(self, token):
        with self.db() as db:
            a = self.account(db, token)
            self.reconcile(db, a)
            a = self.account(db, token)
            positions = self.positions(db,a['id'])
            valid, marks, value = True, [], a['cash']
            for position in positions:
                quote = self.market_data.quote(a['market'],position['symbol'],self.clock())
                position['quote'] = quote
                position['value'] = money(position['qty']*quote['price']) if quote else None
                position['unrealized_pnl'] = money(position['value']-position['basis']) if quote else None
                if quote and quote.get('fresh'):
                    value += position['value']; marks.append(quote['time'])
                else: valid = False
            value = money(value) if valid else None
            fills = [json.loads(r['payload']) for r in db.execute("SELECT payload FROM events WHERE account=? AND kind='fill' ORDER BY id",(a['id'],))]
            latest_fill = max((f['market_bar']['close_time'] for f in fills), default=a['created'])
            mark_time = min(marks) if marks else self.clock().isoformat()
            if marks and timestamp(mark_time) < timestamp(latest_fill): valid=False; value=None
            benchmark = self.market_data.benchmark(a['market'],self.clock())
            if valid and (not marks or max(timestamp(x) for x in marks)-min(timestamp(x) for x in marks) <= timedelta(minutes=5)):
                # Empty cash accounts are sampled only on refreshed benchmark bars.
                point_time = mark_time if marks else (benchmark or {}).get('time')
                if point_time and timestamp(point_time) > timestamp(a['created']) and timestamp(point_time)>=timestamp(latest_fill):
                    bench_price = benchmark['price'] if benchmark and benchmark.get('fresh') and abs((timestamp(benchmark['time'])-timestamp(point_time)).total_seconds())<=300 else None
                    db.execute('INSERT OR IGNORE INTO equity(account,time,value,benchmark) VALUES(?,?,?,?)',(a['id'],point_time,value,bench_price))
            curve = [dict(r) for r in db.execute('SELECT time,value,benchmark FROM equity WHERE account=? ORDER BY time',(a['id'],))]
            peak, drawdown = a['initial'], 0
            for point in curve:
                peak=max(peak,point['value']); drawdown=max(drawdown,(peak-point['value'])/peak)
            exits = [f['realized_pnl'] for f in fills if f['side']=='sell']
            wins, losses = [x for x in exits if x>0], [x for x in exits if x<0]
            comparable = [p for p in curve if p['benchmark']]
            comparison = None
            if len(comparable)>=2:
                first,last=comparable[0],comparable[-1]
                comparison={'since':first['time'],'as_of':last['time'],'benchmark_return_pct':(last['benchmark']/first['benchmark']-1)*100,
                            'account_return_pct':(last['value']/first['value']-1)*100}
            orders = [dict(r) for r in db.execute('SELECT * FROM orders WHERE account=? ORDER BY submitted DESC,rowid DESC',(a['id'],))]
            reserved = money(sum(o['reserve'] for o in orders if o['status']=='pending' and o['side']=='buy'))
            events = [{'id':r['id'],'time':r['time'],'kind':r['kind'],'payload':json.loads(r['payload'])}
                      for r in db.execute('SELECT * FROM events WHERE account=? ORDER BY id',(a['id'],))]
            return {'market':a['market'],'currency':'USD' if a['market']=='us' else 'CNY','initial':a['initial'],'created':a['created'],
                'cash':a['cash'],'available_cash':money(a['cash']-reserved),'equity':value,'valuation_status':'known' if valid else 'unknown',
                'return_pct':(value/a['initial']-1)*100 if value is not None else None,'max_drawdown_pct':drawdown*100,
                'drawdown_basis':'observed_snapshots_only','positions':positions,'orders':orders,'fills':fills,'curve':curve,
                'win_rate_pct':len(wins)/len(exits)*100 if exits else None,'closed_exits':len(exits),
                'payoff_ratio':(sum(wins)/len(wins))/abs(sum(losses)/len(losses)) if wins and losses else None,
                'fees':money(sum(f['fee'] for f in fills)),'benchmark_comparison':comparison,'events':events,'server_time':self.clock().isoformat()}

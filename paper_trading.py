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
    def __init__(self, path, market_data, clock=None, *, markets=('us',)):
        self.markets = tuple(markets)
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
            CREATE TABLE IF NOT EXISTS managed_accounts(account TEXT PRIMARY KEY, strategy_id TEXT UNIQUE);
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
            # Compatible migration: old plan_stop values stay records, never auto-arm.
            if 'auto_stop' not in {r[1] for r in con.execute('PRAGMA table_info(orders)')}:
                con.execute('ALTER TABLE orders ADD COLUMN auto_stop INTEGER NOT NULL DEFAULT 0')
            con.execute("""CREATE TABLE IF NOT EXISTS protective_stops(
                id TEXT PRIMARY KEY,account TEXT,lot_id INTEGER UNIQUE,symbol TEXT,price REAL,
                active_after TEXT,last_checked TEXT,status TEXT,trigger_json TEXT,fill_after TEXT,message TEXT)""")
            con.execute('CREATE INDEX IF NOT EXISTS stops_account_status ON protective_stops(account,status)')
            con.execute('CREATE INDEX IF NOT EXISTS orders_account_status ON orders(account,status)')
            con.execute('CREATE INDEX IF NOT EXISTS lots_account ON lots(account)')
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
        if db.execute('SELECT 1 FROM managed_accounts WHERE account=?',(row['id'],)).fetchone():
            raise PaperError('策略账户只读，不能手动操作')
        if row['market'] not in self.markets:
            raise PaperError('此练习盘目前仅支持美股')
        return dict(row)

    def create(self, market, initial):
        if market not in self.markets:
            raise PaperError('此练习盘目前仅支持美股')
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
        with self.action_db(token) as (db,a):
            return self._submit_order(db,a,payload)

    def _submit_order(self, db, a, payload, *, observation=None):
        key = payload.get('request_key')
        if not isinstance(key, str) or not 16 <= len(key) <= 100 or key.startswith('stop-'):
            raise PaperError('缺少订单幂等编号')
        old = db.execute('SELECT * FROM orders WHERE account=? AND request_key=?', (a['id'], key)).fetchone()
        if old:
            if any(payload.get(k) != old[k] for k in ('symbol', 'side', 'qty', 'reason', 'plan_stop')):
                raise PaperError('同一幂等编号不能更改订单')
            if bool(payload.get('auto_stop',False))!=bool(old['auto_stop']): raise PaperError('同一幂等编号不能更改自动止损')
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
                raise PaperError('止损须为低于参考价的正数')
        auto_stop=payload.get('auto_stop',False)
        if type(auto_stop) is not bool or (auto_stop and (a['market']!='us' or side!='buy' or stop is None)):
            raise PaperError('自动止损只适用于填写止损价的美股买单')
        if auto_stop and money(stop)!=stop: raise PaperError('自动止损价最多两位小数')
        oid, now = secrets.token_hex(16), self.clock().isoformat()
        snapshot = observation if observation is not None else self.market_data.signal_snapshot(a['market'], symbol)
        db.execute('INSERT INTO orders(id,account,request_key,symbol,side,qty,submitted,status,reserve,reason,plan_stop,signal_json,message,auto_stop) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (oid,a['id'],key,symbol,side,qty,now,'pending',p['reserve'] if side=='buy' else 0,
                    reason,stop,json.dumps(snapshot,ensure_ascii=False),'等待提交后的可成交行情',int(auto_stop)))
        self.event(db,a['id'],'order_submitted',{'id':oid,'symbol':symbol,'side':side,'qty':qty,
                   'reason':reason,'plan_stop':stop,'auto_stop':auto_stop,'signal_snapshot':snapshot,'preview':p})
        return dict(db.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone())


    def preview_order(self, token, payload):
        with self.action_db(token) as (db,a):
            return self.preview(db,self.account(db,token),payload.get('symbol'),payload.get('side'),payload.get('qty'))

    def cancel(self, token, oid):
        with self.action_db(token) as (db,a):
            row = db.execute('SELECT * FROM orders WHERE id=? AND account=?',(oid,a['id'])).fetchone()
            if row is not None and row['request_key'].startswith('stop-'):
                raise PaperError('自动止损已触发，不能通过普通撤单撤销')
            if row is None or row['status'] != 'pending':
                raise PaperError('该订单已成交或不可撤销')
            db.execute("UPDATE orders SET status='canceled',message='用户撤单' WHERE id=?",(oid,))
            self.event(db,a['id'],'order_canceled',{'id':oid})

    @contextmanager
    def action_db(self, token):
        # Market effects survive a rejected user action, e.g. cancel after a stop fill.
        with self.db() as db:
            a=self.account(db,token)
            self.reconcile(db,a)
            a=self.account(db,token)
            db.execute('SAVEPOINT user_action')
            try:
                yield db,a
            except PaperError:
                db.execute('ROLLBACK TO user_action')
                db.execute('RELEASE user_action')
                db.commit()
                raise
            else:
                db.execute('RELEASE user_action')

    def update_stop(self, token, lot_id, price):
        with self.action_db(token) as (db,a):
            if a['market']!='us': raise PaperError('自动止损仅支持美股模拟盘')
            lot=db.execute('SELECT * FROM lots WHERE id=? AND account=? AND remaining>0',(lot_id,a['id'])).fetchone()
            if not lot: raise PaperError('模拟持仓批次不存在')
            old=db.execute('SELECT * FROM protective_stops WHERE lot_id=?',(lot_id,)).fetchone()
            if old and old['status']=='triggered': raise PaperError('止损已触发，不能撤销或修改等待中的卖出')
            if old and old['status']=='active':
                safe=getattr(self.market_data,'stop_amendment_safe',None)
                if not safe or not safe(a['market'],lot['symbol'],timestamp(old['last_checked'] or old['active_after']),self.clock()):
                    raise PaperError('行情不完整，无法确认止损未触发，暂不能修改或停用')
            now=self.clock().isoformat()
            if price is None:
                if old and old['status']=='active':
                    db.execute("UPDATE protective_stops SET status='canceled',message='用户停用' WHERE id=?",(old['id'],))
                    self.event(db,a['id'],'stop_canceled',{'stop_id':old['id'],'reason':'user_disabled'})
                return {'status':'canceled'}
            quote=self.market_data.quote(a['market'],lot['symbol'],self.clock())
            if type(price) not in (int,float) or not quote or not quote.get('fresh') or not 0<price<quote['price'] or money(price)!=price:
                raise PaperError('自动止损价须为低于当前参考价的正数，最多两位小数')
            if old:
                db.execute("UPDATE protective_stops SET price=?,active_after=?,last_checked=NULL,status='active',trigger_json=NULL,fill_after=NULL,message='自动止损已启用' WHERE id=?",(price,now,old['id']))
                sid=old['id']
            else:
                sid=secrets.token_hex(16)
                db.execute('INSERT INTO protective_stops(id,account,lot_id,symbol,price,active_after,status,message) VALUES(?,?,?,?,?,?,?,?)',
                           (sid,a['id'],lot_id,lot['symbol'],price,now,'active','自动止损已启用'))
            self.event(db,a['id'],'stop_set',{'stop_id':sid,'lot_id':lot_id,'price':price,'active_after':now})
            return {'id':sid,'status':'active'}

    def sync_all(self):
        # Called by the feature's own scheduler; never uses browser/account credentials.
        with self.db() as db:
            accounts=[dict(r) for r in db.execute("SELECT * FROM accounts WHERE market='us' AND (id IN (SELECT account FROM orders WHERE status='pending') OR id IN (SELECT account FROM protective_stops WHERE status IN ('active','triggered')))")]
        for a in accounts:
            try:
                with self.db() as db: self.reconcile(db,a)
            except Exception:
                import logging
                logging.getLogger('paper').exception('paper background reconciliation failed')
        return {'accounts_checked':len(accounts)}

    def reconcile(self, db, a):
        import heapq
        now=self.clock()
        fills=[json.loads(r['payload']) for r in db.execute("SELECT payload FROM events WHERE account=? AND kind='fill'",(a['id'],))]
        latest=max((timestamp(f['market_bar']['open_time']) for f in fills),default=None)
        timeline=[]
        serial=0
        def queue(at,priority,kind,identifier,bar):
            nonlocal serial
            serial+=1
            heapq.heappush(timeline,(at,priority,serial,kind,identifier,bar))
        def schedule_stop(stop):
            since=timestamp(stop['last_checked'] or stop['active_after'])
            bars,note=self.market_data.stop_bars(a['market'],stop['symbol'],since,now)
            db.execute('UPDATE protective_stops SET message=? WHERE id=?',(note,stop['id']))
            for bar in bars:
                opened,closed=timestamp(bar['open_time']),timestamp(bar['close_time'])
                if opened<timestamp(stop['active_after']) or closed<=since or closed>now: continue
                queue(opened,1,'stop_open',stop['id'],bar)
                queue(closed,0,'stop_close',stop['id'],bar)
        for stop in db.execute("SELECT * FROM protective_stops WHERE account=? AND status IN ('active','triggered')",(a['id'],)).fetchall():
            schedule_stop(dict(stop))
        for order in db.execute("SELECT * FROM orders WHERE account=? AND status='pending' AND request_key NOT LIKE 'stop-%' ORDER BY submitted,rowid",(a['id'],)).fetchall():
            submitted=timestamp(order['submitted'])
            if (now-submitted).total_seconds()>7*86400:
                db.execute("UPDATE orders SET status='rejected',message='订单7天到期' WHERE id=?",(order['id'],))
                self.event(db,a['id'],'order_rejected',{'id':order['id'],'reason':'expired'})
                continue
            bars,note=self.market_data.execution_bars(a['market'],order['symbol'],submitted,now)
            db.execute('UPDATE orders SET message=? WHERE id=?',(note,order['id']))
            for bar in bars: queue(timestamp(bar['open_time']),2,'manual',order['id'],bar)
        while timeline:
            at,_,_,kind,identifier,bar=heapq.heappop(timeline)
            opened,closed=timestamp(bar['open_time']),timestamp(bar['close_time'])
            if not opened<closed<=now: continue
            if kind=='manual':
                order=db.execute('SELECT * FROM orders WHERE id=?',(identifier,)).fetchone()
                if order['status']!='pending' or not timestamp(order['submitted'])<opened or bar.get('tradable') is not True: continue
                if latest and opened<latest:
                    db.execute("UPDATE orders SET status='rejected',message='历史行情后到，已有更晚成交，需人工复盘' WHERE id=?",(identifier,))
                    self.event(db,a['id'],'order_rejected',{'id':identifier,'reason':'late_history_would_reorder_ledger'})
                    continue
                stop=self.fill(db,a,dict(order),bar)
                if stop is not False:
                    latest=opened
                    if stop: schedule_stop(stop)
                continue
            stop=db.execute('SELECT * FROM protective_stops WHERE id=?',(identifier,)).fetchone()
            if not stop or stop['status'] not in ('active','triggered'): continue
            stop=dict(stop)
            lot=db.execute('SELECT * FROM lots WHERE id=? AND remaining>0',(stop['lot_id'],)).fetchone()
            if not lot:
                db.execute("UPDATE protective_stops SET status='canceled',message='该批次已平仓' WHERE id=?",(identifier,))
                continue
            if kind=='stop_close':
                if stop['status']=='active' and bar.get('low',float('inf'))<=stop['price']:
                    self.trigger_stop(db,a,stop,bar,'intrabar',closed,now)
                db.execute('UPDATE protective_stops SET last_checked=? WHERE id=?',(bar['close_time'],identifier))
                continue
            # Gap is observable at open; intrabar low is only known after that bar closes.
            if stop['status']=='active' and bar['open']<=stop['price']:
                self.trigger_stop(db,a,stop,bar,'gap_open',opened if bar.get('tradable') else closed,now)
                stop=dict(db.execute('SELECT * FROM protective_stops WHERE id=?',(identifier,)).fetchone())
            if stop['status']!='triggered' or opened<timestamp(stop['fill_after']) or bar.get('tradable') is not True: continue
            if latest and opened<latest:
                db.execute("UPDATE protective_stops SET fill_after=?,message='历史行情后到，等待当前时刻之后的开盘' WHERE id=?",(now.isoformat(),identifier))
                self.event(db,a['id'],'stop_deferred',{'stop_id':identifier,'reason':'late_history','eligible_after':now.isoformat()})
                continue
            # Protective exit wins at the same open, and cancels queued manual sells.
            for sell in db.execute("SELECT id FROM orders WHERE account=? AND symbol=? AND side='sell' AND status='pending' AND request_key NOT LIKE 'stop-%'",(a['id'],stop['symbol'])).fetchall():
                db.execute("UPDATE orders SET status='canceled',message='自动止损优先，撤销同标的待卖单' WHERE id=?",(sell['id'],))
                self.event(db,a['id'],'order_canceled',{'id':sell['id'],'reason':'protective_stop_priority'})
            if money(Decimal(str(bar['open']))*Decimal('.9995'))<=0: continue
            oid='stop-'+identifier
            db.execute('INSERT OR IGNORE INTO orders(id,account,request_key,symbol,side,qty,submitted,status,reserve,reason,plan_stop,signal_json,message,auto_stop) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (oid,a['id'],oid,stop['symbol'],'sell',lot['remaining'],stop['active_after'],'pending',0,'自动止损',None,'{}','自动止损卖出',0))
            order=dict(db.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone())
            if self.fill(db,a,order,bar,stop=stop) is not False:
                db.execute("UPDATE protective_stops SET status='filled',message='自动止损已卖出' WHERE id=?",(identifier,))
                latest=opened

    def trigger_stop(self, db, a, stop, bar, origin, eligible_after, now):
        evidence={'origin':origin,'interval_open':bar['open_time'],'interval_close':bar['close_time'],
                  'exact_intrabar_time':None,'observed_at':now.isoformat(),'stop_price':stop['price'],'bar':bar}
        db.execute("UPDATE protective_stops SET status='triggered',trigger_json=?,fill_after=?,message='止损已触发，等待可成交开盘' WHERE id=?",
                   (json.dumps(evidence),eligible_after.isoformat(),stop['id']))
        self.event(db,a['id'],'stop_triggered',{'stop_id':stop['id'],**evidence})

    def fill(self, db, a, order, bar, *, stop=None):
        qty,side=order['qty'],order['side']
        lots=list(db.execute('SELECT * FROM lots WHERE account=? AND symbol=? AND remaining>0 ORDER BY id',(a['id'],order['symbol'])))
        sellable=[l for l in lots if (not stop or l['id']==stop['lot_id']) and (a['market']=='us' or l['acquired_day']<bar['session_day'])]
        if side=='sell' and sum(l['remaining'] for l in sellable)<qty: return False
        price=money(Decimal(str(bar['open']))*Decimal('1.0005' if side=='buy' else '.9995'))
        if price<=0: return False
        if a['market']=='cn':
            limits=bar.get('constraint_evidence',{})
            if not limits.get('lower_limit',float('inf'))<=price<=limits.get('upper_limit',0): return False
        if side=='buy' and order.get('auto_stop') and order['plan_stop']>=min(price,bar['open']):
            db.execute("UPDATE orders SET status='rejected',message='开盘买入价已低于自动止损，取消入场' WHERE id=?",(order['id'],))
            self.event(db,a['id'],'order_rejected',{'id':order['id'],'reason':'entry_below_stop'})
            return False
        fee=costs(a['market'],side,qty,price)
        amount=money(qty*price)
        # 只对持久化的V2 managed买单复核冻结预算，不读取成交之后的行情。
        try: snapshot=json.loads(order['signal_json'])
        except (ValueError,TypeError): snapshot={}
        plan=snapshot.get('risk_plan') if isinstance(snapshot,dict) else None
        managed=db.execute('SELECT strategy_id FROM managed_accounts WHERE account=?',(a['id'],)).fetchone()
        if side=='buy' and managed and managed['strategy_id']=='us-daily-30m-v2-risk':
            from strategy_risk import planned_loss
            import math
            valid_plan=isinstance(plan,dict) and plan.get('schema')=='us-risk-plan-v2' and all(
                type(plan.get(k)) in (int,float) and math.isfinite(plan[k]) and plan[k]>0 for k in ('max_loss_usd','notional_budget_usd'))
            if (not valid_plan
                    or planned_loss(qty,price,order['plan_stop'])>plan['max_loss_usd']
                    or money(amount+fee)>plan['notional_budget_usd']):
                db.execute("UPDATE orders SET status='rejected',message='开盘超过冻结风险或资金预算，取消入场' WHERE id=?",(order['id'],))
                self.event(db,a['id'],'order_rejected',{'id':order['id'],'reason':'risk_budget_at_open','price':price,'risk_plan':plan})
                return False
        cash=db.execute('SELECT cash FROM accounts WHERE id=?',(a['id'],)).fetchone()[0]
        reserved=db.execute("SELECT COALESCE(SUM(reserve),0) FROM orders WHERE account=? AND status='pending' AND side='buy' AND id!=?",(a['id'],order['id'])).fetchone()[0]
        if side=='buy' and money(amount+fee)>money(cash-reserved):
            db.execute("UPDATE orders SET status='rejected',message='跳空后资金不足' WHERE id=?",(order['id'],))
            self.event(db,a['id'],'order_rejected',{'id':order['id'],'reason':'insufficient_cash_at_open'})
            return False
        realized,new_stop=0,None
        fill_lot_id,allocations=None,[]
        if side=='buy':
            cursor=db.execute('INSERT INTO lots(account,symbol,qty,remaining,cost,basis_remaining,acquired_day) VALUES(?,?,?,?,?,?,?)',
                              (a['id'],order['symbol'],qty,qty,(amount+fee)/qty,money(amount+fee),bar['session_day']))
            fill_lot_id=cursor.lastrowid
            cash=money(cash-amount-fee)
            if order.get('auto_stop'):
                sid=secrets.token_hex(16)
                db.execute('INSERT INTO protective_stops(id,account,lot_id,symbol,price,active_after,status,message) VALUES(?,?,?,?,?,?,?,?)',
                           (sid,a['id'],cursor.lastrowid,order['symbol'],order['plan_stop'],bar['close_time'],'active','自动止损已启用'))
                new_stop=dict(db.execute('SELECT * FROM protective_stops WHERE id=?',(sid,)).fetchone())
                self.event(db,a['id'],'stop_set',{'stop_id':sid,'lot_id':cursor.lastrowid,'price':order['plan_stop'],'active_after':bar['close_time']})
        else:
            need,basis=qty,0
            for lot in sellable:
                take=min(need,lot['remaining'])
                allocated=money(Decimal(str(lot['basis_remaining']))*Decimal(take)/Decimal(lot['remaining']))
                basis+=allocated
                allocations.append({'lot_id':lot['id'],'qty':take,'basis':allocated})
                db.execute('UPDATE lots SET remaining=remaining-?,basis_remaining=? WHERE id=?',(take,money(lot['basis_remaining']-allocated),lot['id']))
                need-=take
                if not need: break
            realized=money(amount-fee-basis);cash=money(cash+amount-fee)
        db.execute('UPDATE accounts SET cash=? WHERE id=?',(cash,a['id']))
        db.execute("UPDATE orders SET status='filled',message=? WHERE id=?",('自动止损卖出' if stop else '按后续已完成K线开盘价模拟成交',order['id']))
        self.event(db,a['id'],'fill',{'order_id':order['id'],'symbol':order['symbol'],'side':side,'qty':qty,
                   'price':price,'fee':fee,'realized_pnl':realized,'market_bar':bar,'recorded_at':self.clock().isoformat(),
                   'model':'paper-v2-autostop' if stop else 'paper-v3-strategy' if order['request_key'].startswith('strategy-') else 'paper-v1-5bps',
                   'execution_reason':'automatic_stop' if stop else 'automatic_signal' if order['request_key'].startswith('strategy-') else 'manual',
                   'lot_id':fill_lot_id,'lot_allocations':allocations,
                   'entry_signal_type':(snapshot.get('signal') or {}).get('type') if side=='buy' and isinstance(snapshot,dict) else None,
                   'initial_stop':order['plan_stop'] if side=='buy' else None,
                   'initial_risk_usd':self._initial_risk(qty,price,order['plan_stop']) if side=='buy' and a['market']=='us' else None,
                   'stop_id':stop['id'] if stop else None,'trigger_evidence':json.loads(stop['trigger_json']) if stop else None},at=timestamp(bar['open_time']))
        for empty in db.execute("SELECT s.id FROM protective_stops s JOIN lots l ON s.lot_id=l.id WHERE s.account=? AND l.remaining=0 AND s.status IN ('active','triggered')",(a['id'],)).fetchall():
            if stop and empty['id']==stop['id']: continue
            db.execute("UPDATE protective_stops SET status='canceled',message='该批次已平仓' WHERE id=?",(empty['id'],))
            self.event(db,a['id'],'stop_canceled',{'stop_id':empty['id'],'reason':'lot_closed'})
        return new_stop

    @staticmethod
    def _initial_risk(qty, price, stop):
        if stop is None or stop>=price: return None
        from strategy_risk import planned_loss
        return planned_loss(qty,price,stop)

    def state(self, token):
        with self.db() as db:
            return self._state(db,self.account(db,token))

    def _state(self, db, a, *, reconcile=True, event_limit=None):
        if reconcile:
            self.reconcile(db,a)
        a=dict(db.execute('SELECT * FROM accounts WHERE id=?',(a['id'],)).fetchone())
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
        event_rows = db.execute('SELECT * FROM events WHERE account=? ORDER BY id',(a['id'],)) if event_limit is None else reversed(
            db.execute('SELECT * FROM events WHERE account=? ORDER BY id DESC LIMIT ?',(a['id'],event_limit)).fetchall())
        events = [{'id':r['id'],'time':r['time'],'kind':r['kind'],'payload':json.loads(r['payload'])} for r in event_rows]
        stops=[dict(r) for r in db.execute('SELECT s.*,l.remaining qty FROM protective_stops s JOIN lots l ON l.id=s.lot_id WHERE s.account=? ORDER BY l.id',(a['id'],))]
        lots=[dict(r) for r in db.execute('SELECT id,symbol,remaining qty FROM lots WHERE account=? AND remaining>0 ORDER BY id',(a['id'],))]
        return {'stops':stops,'lots':lots,'market':a['market'],'currency':'USD' if a['market']=='us' else 'CNY','initial':a['initial'],'created':a['created'],
            'cash':a['cash'],'available_cash':money(a['cash']-reserved),'equity':value,'valuation_status':'known' if valid else 'unknown',
            'return_pct':(value/a['initial']-1)*100 if value is not None else None,'max_drawdown_pct':drawdown*100,
            'drawdown_basis':'observed_snapshots_only','positions':positions,'orders':orders,'fills':fills,'curve':curve,
            'win_rate_pct':len(wins)/len(exits)*100 if exits else None,'closed_exits':len(exits),
            'payoff_ratio':(sum(wins)/len(wins))/abs(sum(losses)/len(losses)) if wins and losses else None,
            'fees':money(sum(f['fee'] for f in fills)),'benchmark_comparison':comparison,'events':events,'server_time':self.clock().isoformat()}

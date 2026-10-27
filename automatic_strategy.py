"""服务器自动模拟账户。没有券商连接；观察、决策、撮合均有独立证据。"""
import copy
import hashlib
import json
import math
import secrets

from chan2 import STOP_PCT
from paper_trading import PaperError, money, timestamp

STRATEGY_ID = 'us-daily-30m-v1'
RULES = dict(version=STRATEGY_ID, market='us', initial=100000, buy_types=['2B','3B'],
             sell_types=['1S','2S','3S'], daily_direction='up', environment='non_bear',
             position_fraction=.10, max_positions=5, stop_fraction=STOP_PCT,
             stop_basis='signal_extreme_price', finality_buffer_minutes=15,
             max_source_age_minutes=45, signal_scope='confirmed_classic_only',
             execution='server_observation_then_next_regular_5m_open',
             backfill=False, performance_verified=False)
RULES_V2 = {**RULES, 'version':'us-daily-30m-v2-risk', 'trade_risk_fraction':.005,
            'portfolio_risk_fraction':.02, 'risk_group_contract':'manual-risk-groups-v1',
            'risk_budget_scope':'decision_snapshot_and_frozen_fill_budget'}


def signal_key(symbol, signal):
    # PRE→confirmed 共享身份；不因确认变化而伪造新的极值或反复入场。
    identity = [symbol, signal['type'].removeprefix('PRE_'), signal.get('kind','chan'),
                signal['signal_bar_time'], signal['price'], signal.get('zd'), signal.get('zg')]
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


class AutomaticStrategy:
    def __init__(self, store, source, *, rules=None):
        self.store, self.source = store, source
        self.rules = copy.deepcopy(RULES if rules is None else rules)
        self.strategy_id = self.rules["version"]

    def setup(self, db):
        db.execute('''CREATE TABLE IF NOT EXISTS strategy_runtime(
            strategy_id TEXT PRIMARY KEY,last_source TEXT,last_tick TEXT,status TEXT,detail TEXT)''')
        db.execute('''CREATE TABLE IF NOT EXISTS strategy_symbols(
            strategy_id TEXT,symbol TEXT,baseline_time TEXT,PRIMARY KEY(strategy_id,symbol))''')
        db.execute('''CREATE TABLE IF NOT EXISTS strategy_observations(
            strategy_id TEXT,signal_id TEXT,symbol TEXT,first_seen TEXT,first_confirmed TEXT,
            confirmed INTEGER,present INTEGER,consumed INTEGER,signal_json TEXT,order_id TEXT,
            PRIMARY KEY(strategy_id,signal_id))''')
        row = db.execute('SELECT a.* FROM accounts a JOIN managed_accounts m ON a.id=m.account WHERE m.strategy_id=?',
                         (self.strategy_id,)).fetchone()
        if row: return dict(row)
        aid, now = secrets.token_hex(16), self.store.clock().isoformat()
        # 从不发放凭据；即使内部凭据泄露，PaperStore.account 也拒绝手动操作。
        db.execute('INSERT INTO accounts VALUES(?,?,?,?,?,?)',
                   (aid, hashlib.sha256(secrets.token_bytes(48)).hexdigest(), 'us', now, self.rules['initial'], self.rules['initial']))
        db.execute('INSERT INTO managed_accounts VALUES(?,?)', (aid, self.strategy_id))
        db.execute('INSERT INTO equity(account,time,value) VALUES(?,?,?)', (aid,now,self.rules['initial']))
        self.store.event(db, aid, 'strategy_created', {'rules':self.rules,'meaning':'forward_only_simulation'})
        db.execute('INSERT INTO strategy_runtime VALUES(?,?,?,?,?)',
                   (self.strategy_id,None,None,'warming_up','等待首次完整行情建立基线'))
        return dict(db.execute('SELECT * FROM accounts WHERE id=?',(aid,)).fetchone())

    def log(self, db, a, symbol, action, reason, **evidence):
        self.store.event(db,a['id'],'strategy_decision',dict(symbol=symbol,action=action,reason=reason,**evidence))

    def tick(self):
        now = self.store.clock()
        snapshot = self.source.read(now)
        now = self.store.clock()  # 完成计算后的真实观察时间，不回填极值时间。
        with self.store.db() as db:
            a = self.setup(db)
            self.store.reconcile(db,a)
            self.record_marks(db,a)
            a = dict(db.execute('SELECT * FROM accounts WHERE id=?',(a['id'],)).fetchone())
            runtime = db.execute('SELECT * FROM strategy_runtime WHERE strategy_id=?',(self.strategy_id,)).fetchone()
            if snapshot.get('error'):
                detail, status = snapshot['error'], 'data_unknown'
                if runtime['status'] != status or runtime['detail'] != detail:
                    self.log(db,a,None,'skip',detail)
            elif runtime['last_source'] == snapshot['id']:
                db.execute('UPDATE strategy_runtime SET last_tick=? WHERE strategy_id=?',(now.isoformat(),self.strategy_id))
                self.store._state(db,a,reconcile=False,event_limit=0)
                return
            else:
                for symbol, data in sorted(snapshot['symbols'].items()):
                    if not data.get('valid'):
                        self.log(db,a,symbol,'skip',data.get('reason','行情未知'),source_id=snapshot['id'])
                        continue
                    self.observe(db,a,symbol,data,snapshot,now)
                    a = dict(db.execute('SELECT * FROM accounts WHERE id=?',(a['id'],)).fetchone())
                environment = snapshot.get('context',{}).get('new_long_environment','unknown')
                unknown = environment == 'unknown'
                valid = sum(bool(d.get('valid')) for d in snapshot['symbols'].values())
                status = 'data_unknown' if not valid else 'environment_unknown' if unknown else 'environment_blocked' if environment=='blocked' else 'running'
                detail = ('没有完整标的行情' if not valid else '市场环境未知，暂停新买入；卖出及止损继续'
                          if unknown else '熊市环境，暂停新买入；卖出及止损继续' if environment=='blocked'
                          else '自动观察信号、提交模拟订单；卖出和止损独立运行')
            db.execute('UPDATE strategy_runtime SET last_source=?,last_tick=?,status=?,detail=? WHERE strategy_id=?',
                       (snapshot.get('id'),now.isoformat(),status,detail,self.strategy_id))
            self.store._state(db,a,reconcile=False,event_limit=0)

    def observe(self, db, a, symbol, data, snapshot, now):
        baseline = not db.execute('SELECT 1 FROM strategy_symbols WHERE strategy_id=? AND symbol=?',
                                 (self.strategy_id,symbol)).fetchone()
        if baseline:
            db.execute('INSERT INTO strategy_symbols VALUES(?,?,?)',(self.strategy_id,symbol,now.isoformat()))
            self.log(db,a,symbol,'baseline','已有历史信号仅建立基线，不补做历史交易',source_id=snapshot['id'])
        old = {r['signal_id']:dict(r) for r in db.execute('SELECT * FROM strategy_observations WHERE strategy_id=? AND symbol=?',
                                                       (self.strategy_id,symbol))}
        present, candidates = set(), []
        for signal in data.get('signals',[]):
            sid = signal_key(symbol,signal)
            present.add(sid)
            confirmed = bool(signal.get('confirmed')) and signal.get('kind','chan')=='chan' and not signal['type'].startswith('PRE_')
            prior = old.get(sid)
            if not prior:
                db.execute('INSERT INTO strategy_observations VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (self.strategy_id,sid,symbol,now.isoformat(),now.isoformat() if confirmed else None,
                     int(confirmed),1,int(baseline),json.dumps(signal,ensure_ascii=False),None))
            else:
                db.execute('UPDATE strategy_observations SET confirmed=?,present=1,first_confirmed=COALESCE(first_confirmed,?),signal_json=? '
                           'WHERE strategy_id=? AND signal_id=?',
                           (int(confirmed),now.isoformat() if confirmed else None,json.dumps(signal,ensure_ascii=False),self.strategy_id,sid))
                if prior['confirmed'] and not confirmed:
                    self.invalidate(db,a,prior,'结构确认已撤回，保留此前观察及成交记录')
            consumed = baseline or (prior and prior['consumed'])
            if confirmed and not consumed:
                candidates.append((sid,signal))
        for sid, prior in old.items():
            if sid not in present and prior['present']:
                db.execute('UPDATE strategy_observations SET present=0 WHERE strategy_id=? AND signal_id=?',(self.strategy_id,sid))
                self.invalidate(db,a,prior,'信号从新快照中消失，保留此前记录，不回写收益')
        # 同一快照仅处理最新的有效经典信号；卖出优先，避免历史候选集中追单。
        sells = [(sid,s) for sid,s in candidates if s['type'] in self.rules['sell_types']]
        buys = [(sid,s) for sid,s in candidates if s['type'] in self.rules['buy_types']]
        selected = max(sells or buys,key=lambda x:(x[1]['signal_bar_time'],x[1]['type']),default=None)
        for sid, signal in candidates:
            db.execute('UPDATE strategy_observations SET consumed=1 WHERE strategy_id=? AND signal_id=?',(self.strategy_id,sid))
            if selected is None or sid != selected[0]:
                self.log(db,a,symbol,'skip','信号不在本版本范围或有更新/更优先的退出信号',signal_id=sid)
                continue
            self.decide(db,a,symbol,sid,signal,data,snapshot)

    def invalidate(self, db, a, prior, reason):
        self.log(db,a,prior['symbol'],'repaint',reason,signal_id=prior['signal_id'])
        # 只撤销尚未撮合的入场；已成交不因事后重绘消失。
        order = db.execute("SELECT * FROM orders WHERE id=? AND status='pending' AND side='buy'",(prior['order_id'],)).fetchone()
        if order:
            db.execute("UPDATE orders SET status='canceled',message=? WHERE id=?",('信号撤回后自动取消未成交入场',order['id']))
            self.store.event(db,a['id'],'order_canceled',{'id':order['id'],'reason':'signal_repaint'})

    def decide(self, db, a, symbol, sid, signal, data, snapshot):
        side = 'sell' if signal['type'] in self.rules['sell_types'] else 'buy'
        try:
            risk_plan=None
            owned = sum(p['qty'] for p in self.store.positions(db,a['id']) if p['symbol']==symbol)
            pending = [dict(r) for r in db.execute("SELECT * FROM orders WHERE account=? AND status='pending'",(a['id'],))]
            if side == 'sell':
                # 卖点先取消未成交入场；不会因缺少持仓而把买单留在后台。
                for order in pending:
                    if order['symbol']==symbol and order['side']=='buy':
                        db.execute("UPDATE orders SET status='canceled',message='新卖点取消入场' WHERE id=?",(order['id'],))
                        self.store.event(db,a['id'],'order_canceled',{'id':order['id'],'reason':'new_sell_signal'})
                if not owned: raise PaperError('没有持仓；已取消该标的待成交买单')
                qty = owned-sum(o['qty'] for o in pending if o['symbol']==symbol and o['side']=='sell')
                if qty <= 0: raise PaperError('该标的已有退出订单')
                stop = None
            else:
                if snapshot.get('context',{}).get('new_long_environment') != 'permitted':
                    raise PaperError('市场环境为熊市或未知，暂停新买入')
                if data.get('direction') != self.rules['daily_direction']: raise PaperError('已完成日线方向不是向上')
                latest_sell = max((s['signal_bar_time'] for s in data.get('signals',[]) if s.get('confirmed') and s['type'] in self.rules['sell_types']), default='')
                if latest_sell >= signal['signal_bar_time']: raise PaperError('存在时间不早于买点的已确认卖点')
                if owned or any(o['symbol']==symbol for o in pending): raise PaperError('已有持仓或待成交订单，不重复加仓')
                symbols = {p['symbol'] for p in self.store.positions(db,a['id'])} | {o['symbol'] for o in pending if o['side']=='buy'}
                if len(symbols) >= self.rules['max_positions']: raise PaperError('已达到5只标的上限')
                quote = self.store.market_data.quote('us',symbol,self.store.clock())
                if not quote or not quote.get('fresh'): raise PaperError('用于执行的5分钟行情未知或过期')
                reserved = sum(o['reserve'] for o in pending if o['side']=='buy')
                budget = min(a['initial']*self.rules['position_fraction'],(a['cash']-reserved-2)/1.05)
                qty = math.floor((budget-2)/quote['price'])
                if qty < 1: raise PaperError('模拟资金不足以买入1股')
                stop = money(signal['price']*(1-self.rules['stop_fraction']))
                if not 0 < stop < quote['price']: raise PaperError('当前价格已低于信号止损线，不追补入场')
                if self.rules.get('trade_risk_fraction'):
                    from strategy_risk import size_entry
                    qty,risk_plan=size_entry(self.store,db,a,symbol,quote,stop,budget,self.rules)
            observation = db.execute('SELECT * FROM strategy_observations WHERE strategy_id=? AND signal_id=?',(self.strategy_id,sid)).fetchone()
            reason = f"{self.strategy_id} · 30分钟{signal['type']} · 首次确认观察 {observation['first_confirmed']}"
            # 使用本次实际观察的独立证据，不将网站的回算时间冒充可交易时间。
            evidence = dict(signal=signal,first_seen_time=observation['first_seen'],confirmed_time=observation['first_confirmed'],
                            source_id=snapshot['id'],source_observed_at=snapshot.get('observed_at'),
                            completed_cutoff=snapshot.get('cutoff'),regime=snapshot.get('regime'),rules=self.rules,
                            timing_evidence='live_monitor_observation',
                            confirmation_scope='structure_observed_in_closed_prefix',
                            historical_first_recognition_unknown=True)
            if risk_plan is not None: evidence['risk_plan']=risk_plan
            order = self.store._submit_order(db,a,dict(request_key='strategy-'+sid,symbol=symbol,side=side,qty=qty,
                reason=reason,plan_stop=stop,auto_stop=side=='buy'),observation=evidence)
            db.execute('UPDATE strategy_observations SET order_id=? WHERE strategy_id=? AND signal_id=?',(order['id'],self.strategy_id,sid))
            self.log(db,a,symbol,side,reason,signal_id=sid,order_id=order['id'],qty=qty,plan_stop=stop,**evidence)
        except PaperError as exc:
            self.log(db,a,symbol,'skip',str(exc),signal_id=sid)

    def record_marks(self, db, a):
        # 只追加实际看到的持仓估值点，不回填日内极值；旧买入缺少lot关联时留空。
        db.execute('''CREATE TABLE IF NOT EXISTS strategy_position_marks(
            account TEXT,lot_id INTEGER,bar_time TEXT,observed_at TEXT,price REAL,
            PRIMARY KEY(account,lot_id,bar_time))''')
        for lot in db.execute('SELECT * FROM lots WHERE account=? AND remaining>0',(a['id'],)).fetchall():
            quote=self.store.market_data.quote('us',lot['symbol'],self.store.clock())
            if not quote or not quote.get('fresh'): continue
            entry=db.execute("SELECT payload FROM events WHERE account=? AND kind='fill' AND json_extract(payload,'$.lot_id')=?",
                             (a['id'],lot['id'])).fetchone()
            if not entry or timestamp(quote['time'])<timestamp(json.loads(entry['payload'])['market_bar']['close_time']): continue
            db.execute('INSERT OR IGNORE INTO strategy_position_marks VALUES(?,?,?,?,?)',
                       (a['id'],lot['id'],quote['time'],self.store.clock().isoformat(),quote['price']))

    def report(self):
        with self.store.db() as db:
            a = self.setup(db)
            runtime = dict(db.execute('SELECT * FROM strategy_runtime WHERE strategy_id=?',(self.strategy_id,)).fetchone())
            state = self.store._state(db,a,reconcile=False,event_limit=300)
            from strategy_review import review, common_comparison
            risk=None
            if self.rules.get('trade_risk_fraction'):
                from strategy_risk import portfolio_risk
                try: risk=portfolio_risk(self.store,db,a,self.rules)
                except PaperError as exc: risk=dict(known=False,reason=str(exc))
            baseline_count=db.execute('SELECT COUNT(*) FROM strategy_symbols WHERE strategy_id=?',(self.strategy_id,)).fetchone()[0]
            return dict(rules=self.rules,runtime=runtime,account=state,risk=risk,review=review(db,a,state),comparison=common_comparison(db),baseline_symbols=baseline_count,
                        decisions=[e for e in state['events'] if e['kind']=='strategy_decision'][-200:])


class StrategyGroup:
    def __init__(self,*strategies): self.strategies=strategies

    def tick(self):
        import logging
        for strategy in self.strategies:
            try: strategy.tick()
            except Exception:
                logging.getLogger(__name__).exception('Automatic simulation failed: %s',strategy.strategy_id)

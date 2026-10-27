import copy
import hashlib
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from automatic_strategy import AutomaticStrategy, STRATEGY_ID
from paper_trading import PaperStore, PaperError, timestamp
from strategy_routes import strategy_router
import tests.test_paper_trading as fixtures


class Source:
    def __init__(self): self.serial=0; self.data={}
    def publish(self, signals=(), *, direction='up', context='permitted', symbol='AAPL', valid=True):
        self.serial+=1
        self.data=dict(id=str(self.serial),observed_at='2026-10-27T14:20:00Z',cutoff='2026-10-27T14:05:00Z',
            context={'new_long_environment':context},regime={'bear':False,'known':context!='unknown'},
            symbols={symbol:dict(valid=valid,direction=direction,signals=list(signals),reason='行情缺失')})
    def read(self, now): return copy.deepcopy(self.data)


def signal(kind='2B', *, label='2026-10-27T13:30:00Z', confirmed=True, **extras):
    return dict(type=kind,kind='chan',signal_bar_time=label,price=100.,confirmed=confirmed,**extras)


class AutomaticTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.clock=fixtures.Clock();self.market=fixtures.Market(self.clock)
        self.store=PaperStore(Path(self.tmp.name)/'ledger.sqlite',self.market,self.clock)
        self.source=Source();self.engine=AutomaticStrategy(self.store,self.source)
        self.source.publish();self.engine.tick()
    def tearDown(self): self.tmp.cleanup()
    def report(self): return self.engine.report()['account']
    def buy(self):
        self.source.publish([signal()]);self.engine.tick()
    def fill(self):
        self.market.bar();self.clock.now=timestamp('2026-10-27T14:41:00Z');self.engine.tick()

    def test_initial_history_is_baseline_never_backfilled(self):
        source=Source();source.publish([signal()]);engine=AutomaticStrategy(self.store,source)
        # 使用另一个干净账本，验证真正首次启动。
        store=PaperStore(Path(self.tmp.name)/'clean.sqlite',self.market,self.clock)
        engine=AutomaticStrategy(store,source);engine.tick()
        self.assertEqual(engine.report()['account']['orders'],[])
        with store.db() as db:
            observation=db.execute('SELECT * FROM strategy_observations').fetchone()
            self.assertEqual(observation['first_seen'],self.clock().isoformat())
            self.assertNotEqual(observation['first_seen'],signal()['signal_bar_time'])
        source.publish([signal()]);engine.tick()
        self.assertEqual(engine.report()['account']['orders'],[])

    def test_signal_automatically_enters_and_new_sell_exits_without_browser(self):
        self.buy()
        account=self.report();self.assertEqual(len(account['orders']),1);self.assertEqual(account['fills'],[])
        order=account['orders'][0]
        self.assertEqual(order['side'],'buy');self.assertTrue(order['auto_stop']);self.assertEqual(order['plan_stop'],97)
        evidence=json.loads(order['signal_json'])
        self.assertEqual(evidence['first_seen_time'],self.clock().isoformat())
        self.assertEqual(evidence['confirmed_time'],self.clock().isoformat())
        self.assertEqual(order['submitted'],self.clock().isoformat())
        self.fill()
        self.assertEqual(self.report()['fills'][0]['execution_reason'],'automatic_signal')
        self.source.publish([signal(),signal('3S',label='2026-10-27T14:00:00Z')],context='unknown',direction='down')
        self.engine.tick()
        self.assertEqual(self.report()['orders'][0]['side'],'sell')
        self.market.bar(start='2026-10-27T14:45:00Z',price=110)
        self.clock.now=timestamp('2026-10-27T14:51:00Z');self.engine.tick()
        account=self.report()
        self.assertEqual(account['positions'],[]);self.assertEqual(len(account['fills']),2)
        self.assertGreater(account['return_pct'],0)  # 人工行情仅验证账务，不是收益验证。

    def test_automatic_stop_works_with_no_report_or_browser(self):
        self.buy();self.fill()
        self.market.bar(start='2026-10-27T14:45:00Z',price=90)
        self.clock.now=timestamp('2026-10-27T14:51:00Z');self.store.sync_all()
        with self.store.db() as db:
            fills=[json.loads(r['payload']) for r in db.execute("SELECT payload FROM events WHERE kind='fill'")]
            self.assertEqual(len(fills),2)
            self.assertEqual(fills[-1]['execution_reason'],'automatic_stop')
        self.assertEqual(self.report()['positions'],[])

    def test_observer_read_cannot_cause_fills(self):
        self.buy();self.market.bar();self.clock.now=timestamp('2026-10-27T14:41:00Z')
        self.assertEqual(self.report()['fills'],[])
        self.engine.tick()
        self.assertEqual(len(self.report()['fills']),1)

    def test_repeat_restart_concurrency_and_repaint_do_not_duplicate_entry(self):
        self.source.publish([signal()])
        with ThreadPoolExecutor(max_workers=2) as pool: list(pool.map(lambda _:self.engine.tick(),range(2)))
        self.assertEqual(len(self.report()['orders']),1)
        self.engine=AutomaticStrategy(self.store,self.source);self.engine.tick()
        self.source.publish([]);self.engine.tick()
        self.assertEqual(self.report()['orders'][0]['status'],'canceled')
        self.source.publish([signal()]);self.engine.tick()
        self.assertEqual(len(self.report()['orders']),1)
        self.assertTrue(any(e['payload']['action']=='repaint' for e in self.engine.report()['decisions']))

    def test_repaint_does_not_erase_fill_or_profit_history(self):
        self.buy();self.fill();original=self.report()['fills']
        self.source.publish([]);self.engine.tick()
        self.assertEqual(self.report()['fills'],original)
        self.assertEqual(len(self.report()['positions']),1)

    def test_unknown_missing_downtrend_and_unconfirmed_are_not_buyable(self):
        cases=[dict(context='unknown'),dict(context='blocked'),dict(direction='down'),dict(valid=False)]
        for i, case in enumerate(cases):
            self.source.publish([signal(label=f'2026-10-26T{10+i}:00:00Z')],**case);self.engine.tick()
        self.source.publish([signal('PRE_2B',confirmed=False),signal('ZD_B',kind_unused=True)])
        self.source.data['symbols']['AAPL']['signals'][-1]['kind']='pivot_edge'
        self.engine.tick();self.assertEqual(self.report()['orders'],[])
        self.source.publish([signal()]);self.engine.tick()  # PRE→confirmed是真实新增确认。
        self.assertEqual(len(self.report()['orders']),1)

    def test_rejected_environment_is_not_retroactively_retried(self):
        self.source.publish([signal()],context='unknown');self.engine.tick()
        self.source.publish([signal()],context='permitted');self.engine.tick()
        self.assertEqual(self.report()['orders'],[])

    def test_newer_sell_blocks_buy_and_cancels_pending_entry(self):
        self.buy()
        self.source.publish([signal(),signal('2S',label='2026-10-27T14:00:00Z')]);self.engine.tick()
        self.assertEqual(self.report()['orders'][0]['status'],'canceled')
        self.source.publish([signal('3B',label='2026-10-27T13:45:00Z'),signal('2S',label='2026-10-27T14:00:00Z')]);self.engine.tick()
        self.assertEqual(len(self.report()['orders']),1)

    def test_max_positions_and_cash_reservations(self):
        for i in range(6):
            self.source.publish(symbol=f'TEST{i}');self.engine.tick()
            self.source.publish([signal()],symbol=f'TEST{i}');self.engine.tick()
        orders=self.report()['orders'];self.assertEqual(len(orders),5)
        self.assertTrue(all(o['qty']*100 <= 10000 for o in orders))
        self.assertGreater(self.report()['available_cash'],0)

    def test_new_symbol_after_missing_data_gets_own_baseline(self):
        self.source.publish([signal()],valid=False,symbol='NEW');self.engine.tick()
        self.source.publish([signal()],symbol='NEW');self.engine.tick()
        self.assertEqual(self.report()['orders'],[])

    def test_source_error_pauses_new_decisions_but_not_stops(self):
        self.buy();self.fill()
        self.source.data={'id':None,'error':'offline','symbols':{}};self.engine.tick()
        self.assertEqual(self.engine.report()['runtime']['status'],'data_unknown')
        self.assertEqual(len(self.report()['fills']),1)
        self.market.bar(start='2026-10-27T14:45:00Z',price=90)
        self.clock.now=timestamp('2026-10-27T14:51:00Z');self.engine.tick()
        self.assertEqual(self.report()['positions'],[])

    def test_observer_api_cannot_trade_or_read_other_accounts(self):
        token=self.store.create('us',100000)['token'];self.buy()
        app=FastAPI();app.include_router(strategy_router(self.engine));client=TestClient(app)
        response=client.get('/api/strategy/us?account=forged');self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertNotIn('token_hash',response.text);self.assertNotIn(token,response.text)
        self.assertEqual(client.post('/api/strategy/us',json={'side':'buy'}).status_code,405)
        self.assertEqual(self.store.state(token)['orders'],[])
        # 即使管理员误发managed账户凭据，也不能通过旧手动API操作。
        stolen='x'*40
        with self.store.db() as db:
            db.execute('UPDATE accounts SET token_hash=? WHERE id IN (SELECT account FROM managed_accounts WHERE strategy_id=?)',
                       (hashlib.sha256(stolen.encode()).hexdigest(),STRATEGY_ID))
        with self.assertRaisesRegex(PaperError,'只读'): self.store.state(stolen)
        disabled=FastAPI();disabled.include_router(strategy_router(self.engine,enabled=lambda:False))
        self.assertEqual(TestClient(disabled).get('/api/strategy/us').status_code,503)


if __name__=='__main__': unittest.main()

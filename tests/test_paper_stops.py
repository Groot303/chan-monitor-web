import unittest
from datetime import timedelta
import sqlite3
import ast
import asyncio
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch, Mock
from paper_trading import PaperError, timestamp
import tests.test_paper_trading as fixtures


class StopTests(unittest.TestCase):
    setUp=fixtures.StoreTests.setUp
    tearDown=fixtures.StoreTests.tearDown
    order=fixtures.StoreTests.order

    def buy(self,**kw):
        self.order(auto_stop=True,**kw)
        entry=self.market.bar()
        self.clock.now=timestamp('2026-10-27T14:41:00Z')
        self.store.sync_all()
        return entry

    def bar(self,start,price=100,low=None):
        bar=self.market.bar(start='2026-10-27T'+start+'Z',price=price)
        if low is not None:bar['low']=low
        self.clock.now=timestamp(bar['close_time'])+timedelta(minutes=1)
        return bar

    def test_opt_in_old_plan_only_and_migration(self):
        self.order()
        self.market.bar();self.clock.now=timestamp('2026-10-27T14:41:00Z')
        self.assertEqual(self.store.state(self.token)['stops'],[])
        # Existing v1 databases receive the new flag as false, without activation.
        with self.store.db() as db: db.execute('ALTER TABLE orders DROP COLUMN auto_stop')
        state=self.store.state(self.token)
        self.assertFalse(state['orders'][0]['auto_stop'])
        self.assertEqual(state['stops'],[])

    def test_gap_exit_is_automatic_without_account_refresh(self):
        self.buy()
        self.bar('14:45:00',price=85)
        self.store.sync_all()
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT SUM(remaining) FROM lots').fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='fill'").fetchone()[0],2)
        state=self.store.state(self.token)
        self.assertEqual(state['fills'][-1]['price'],84.96)
        self.assertEqual(state['fills'][-1]['execution_reason'],'automatic_stop')
        self.assertEqual(state['fills'][-1]['trigger_evidence']['origin'],'gap_open')
        self.assertEqual(state['stops'][0]['status'],'filled')
        self.store.sync_all();self.store.state(self.token)
        self.assertEqual(len(self.store.state(self.token)['fills']),2)

    def test_intrabar_detection_waits_for_a_later_completed_bar(self):
        self.buy()
        self.bar('14:45:00',low=89)
        state=self.store.state(self.token)
        self.assertEqual(state['stops'][0]['status'],'triggered')
        self.assertEqual(len(state['fills']),1)
        event=next(e for e in state['events'] if e['kind']=='stop_triggered')['payload']
        self.assertIsNone(event['exact_intrabar_time'])
        self.assertEqual(event['observed_at'],self.clock().isoformat())
        self.bar('14:50:00',price=95)
        self.store.sync_all()
        self.assertEqual(self.store.state(self.token)['fills'][-1]['price'],94.95)

    def test_entry_bar_low_does_not_trigger_a_retroactive_exit(self):
        self.order(auto_stop=True)
        self.market.bar()['low']=80
        self.clock.now=timestamp('2026-10-27T14:41:00Z')
        state=self.store.state(self.token)
        self.assertEqual(state['stops'][0]['status'],'active')
        self.assertEqual(len(state['fills']),1)

    def test_entry_below_stop_is_rejected(self):
        self.order(auto_stop=True)
        self.market.bar(price=85);self.clock.now=timestamp('2026-10-27T14:41:00Z')
        state=self.store.state(self.token)
        self.assertEqual(state['orders'][0]['status'],'rejected')
        self.assertEqual(state['positions'],[])

    def test_partial_manual_exit_and_protective_priority(self):
        self.buy()
        self.order(side='sell',qty=3,plan_stop=None)
        self.bar('14:45:00')
        self.store.state(self.token)
        self.order(side='sell',qty=5,plan_stop=None)
        self.bar('14:55:00',price=85)
        state=self.store.state(self.token)
        self.assertEqual(state['fills'][-1]['qty'],7)
        self.assertEqual(state['positions'],[])
        self.assertTrue(any(o['status']=='canceled' and o['qty']==5 for o in state['orders']))

    def test_lot_isolation_protects_only_the_matching_entry(self):
        self.buy()
        self.order(auto_stop=True,qty=5,plan_stop=95)
        self.bar('14:45:00')
        self.store.state(self.token)
        self.bar('14:55:00',price=94)
        state=self.store.state(self.token)
        self.assertEqual(state['fills'][-1]['qty'],5)
        self.assertEqual(state['positions'][0]['qty'],10)
        self.assertEqual(state['positions'][0]['basis'],1001.5)

    def test_edit_and_disable_before_trigger_and_owner_scope(self):
        self.buy()
        state=self.store.state(self.token);lot=state['lots'][0]['id']
        other=self.store.create('us',100000)['token']
        with self.assertRaises(PaperError):self.store.update_stop(other,lot,92)
        self.store.update_stop(self.token,lot,92)
        self.store.update_stop(self.token,lot,None)
        self.bar('14:45:00',price=85)
        self.assertEqual(len(self.store.state(self.token)['fills']),1)

    def test_trigger_cannot_be_canceled_and_invalid_action_keeps_market_events(self):
        self.buy()
        lot=self.store.state(self.token)['lots'][0]['id']
        self.bar('14:45:00',low=89)
        with self.assertRaises(PaperError):self.store.update_stop(self.token,lot,None)
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT status FROM protective_stops').fetchone()[0],'triggered')
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='stop_triggered'").fetchone()[0],1)

    def test_missing_stop_history_does_not_fake_a_fill(self):
        self.buy()
        self.market.stop_bars=lambda *args:([],'missing data')
        self.market.stop_amendment_safe=lambda *args:False
        self.bar('14:45:00',price=85)
        state=self.store.state(self.token)
        self.assertEqual(len(state['fills']),1)
        self.assertEqual(state['stops'][0]['status'],'active')
        with self.assertRaises(PaperError):self.store.update_stop(self.token,state['lots'][0]['id'],None)

    def test_same_sync_can_enter_then_stop_on_later_bars(self):
        self.order(auto_stop=True)
        self.market.bar()
        self.bar('14:45:00',price=85)
        self.store.sync_all()
        state=self.store.state(self.token)
        self.assertEqual([f['side'] for f in state['fills']],['buy','sell'])
        self.assertEqual(state['positions'],[])

    def test_flat_gap_waits_for_tradable_bar(self):
        self.buy()
        flat=self.bar('14:45:00',price=85);flat.update(high=85,low=85,tradable=False)
        self.assertEqual(len(self.store.state(self.token)['fills']),1)
        self.bar('14:50:00',price=84)
        self.assertEqual(self.store.state(self.token)['fills'][-1]['price'],83.96)

    def test_late_history_defers_to_a_future_open_without_reordering_fills(self):
        self.buy()
        self.order(symbol='NVDA',plan_stop=None)
        self.market.bar('NVDA','2026-10-27T14:55:00Z')
        self.clock.now=timestamp('2026-10-27T15:01:00Z')
        self.store.state(self.token)
        self.bar('14:45:00',price=85)
        self.clock.now=timestamp('2026-10-27T15:01:00Z')
        state=self.store.state(self.token)
        self.assertEqual(len(state['fills']),2)
        self.assertEqual(state['stops'][0]['status'],'triggered')
        self.bar('15:05:00',price=80)
        state=self.store.state(self.token)
        self.assertEqual(state['fills'][-1]['market_bar']['open_time'],'2026-10-27T15:05:00+00:00')

    def test_stop_api_requires_owner_and_new_orders_validate_opt_in(self):
        self.buy()
        lot=self.store.state(self.token)['lots'][0]['id']
        app=fixtures.FastAPI();app.include_router(fixtures.router_for(self.store));client=fixtures.TestClient(app)
        endpoint=f'/api/paper/stops/{lot}'
        self.assertEqual(client.post(endpoint,json={'price':92}).status_code,401)
        headers={'Authorization':'Bearer '+self.token}
        self.assertEqual(client.post(endpoint,headers=headers,json={'price':92}).status_code,200)
        self.assertEqual(client.post(endpoint,headers=headers,json={'price':101}).status_code,400)
        with self.assertRaises(PaperError):self.order(auto_stop=True,side='sell',plan_stop=None)

    def test_regular_stop_history_keeps_flat_bars_for_trigger_evidence(self):
        # Adapter and core share the no-gap gate; flattened bars cannot disappear.
        with fixtures.tempfile.TemporaryDirectory() as tmp:
            root=fixtures.Path(tmp);(root/'charts').mkdir()
            (root/'signals.json').write_text('{"symbols":{"AAPL":{}}}')
            first={'time':timestamp('2026-10-27T14:35:00Z').timestamp(),'open':85,'high':85,'low':85,'close':85}
            (root/'charts/AAPL.json').write_text(fixtures.json.dumps({'levels':{'5m':{'ohlc':[first,{**first,'time':timestamp('2026-10-27T14:40:00Z').timestamp()}]}}}))
            source=fixtures.FileMarketData(root,fixtures.Sessions())
            bars,_=source.stop_bars('us','AAPL',timestamp('2026-10-27T14:40:00Z'),timestamp('2026-10-27T14:46:00Z'))
            self.assertEqual(len(bars),1)
            self.assertIs(bars[0]['tradable'],False)
            self.assertTrue(source.stop_amendment_safe('us','AAPL',timestamp('2026-10-27T14:40:00Z'),timestamp('2026-10-27T14:46:00Z')))
            self.assertFalse(source.stop_amendment_safe('us','AAPL',timestamp('2026-10-27T14:40:00Z'),timestamp('2026-10-27T14:51:00Z')))

    def test_production_startup_schedules_feature_only_when_enabled(self):
        fn=next(n for n in ast.parse(fixtures.Path('api.py').read_text()).body
                if isinstance(n,ast.AsyncFunctionDef) and n.name=='on_startup')
        fn.decorator_list=[]
        class Scheduler:
            def __init__(self,**kw):self.jobs=[]
            def add_job(self,func,*args,**kw):self.jobs.append((func,kw))
            def start(self):pass
        fake=ModuleType('apscheduler.schedulers.asyncio');fake.AsyncIOScheduler=Scheduler
        thread=ModuleType('threading');thread.Thread=lambda **kw:SimpleNamespace(start=lambda:None)
        for enabled,auto_enabled in (('','1'),('1','1'),('1','0')):
            scope={'os':SimpleNamespace(environ={'PAPER_TRADING_ENABLED':enabled,'US_STRATEGY_ENABLED':auto_enabled}),
                   'CN_SYMS':[],'log':Mock(),'run_pipeline':Mock(),'fetch_ibkr_positions':Mock(),
                   '_paper_store':self.store,'_automatic_strategy':SimpleNamespace(tick=Mock()),'_cn_research':SimpleNamespace(collect=Mock()),
                   'datetime':fixtures.datetime,'timezone':fixtures.timezone,'timedelta':timedelta}
            exec(compile(ast.Module(body=[fn],type_ignores=[]),'api.py','exec'),scope)
            with patch.dict(sys.modules,{'apscheduler':ModuleType('apscheduler'),
                    'apscheduler.schedulers':ModuleType('apscheduler.schedulers'),
                    'apscheduler.schedulers.asyncio':fake,'threading':thread}):
                asyncio.run(scope['on_startup']())
            jobs=[(func,kw) for func,kw in scope['scheduler'].jobs if kw.get('id')=='paper_reconcile']
            self.assertEqual(len(jobs),int(bool(enabled)))
            auto=[(func,kw) for func,kw in scope['scheduler'].jobs if kw.get('id')=='us_strategy']
            self.assertEqual(len(auto),int(bool(enabled) and auto_enabled=='1'))
            cn=[(func,kw) for func,kw in scope['scheduler'].jobs if kw.get('id')=='cn_research']
            self.assertEqual(len(cn),1,'A股采集独立于美股模拟开关')
            self.assertEqual(cn[0][0],scope['_cn_research'].collect)
            self.assertEqual(cn[0][1]['seconds'],60)
            if auto:
                self.assertEqual(auto[0][0],scope['_automatic_strategy'].tick)
                self.assertEqual(auto[0][1]['seconds'],60)
                self.assertEqual(auto[0][1]['max_instances'],1)
            if jobs:
                self.assertEqual(jobs[0][0],self.store.sync_all)
                self.assertEqual(jobs[0][1]['seconds'],60)
                self.assertEqual(jobs[0][1]['max_instances'],1)


if __name__=='__main__':unittest.main()

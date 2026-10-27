import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient
from paper_trading import PaperStore, PaperError, timestamp, costs
from paper_market import FileMarketData, ExchangeSessions
from paper_routes import router_for


class Clock:
    def __init__(self): self.now=timestamp('2026-10-27T14:31:00Z')
    def __call__(self): return self.now


class Market:
    def __init__(self,clock): self.clock=clock;self.bars={};self.price=100.;self.fresh=True
    def quote(self,market,symbol,now): return {'price':self.price,'time':now.isoformat(),'fresh':self.fresh}
    def signal_snapshot(self,market,symbol): return {'symbol':symbol,'first_seen_time':None,'time':'2020-01-01'}
    def benchmark(self,market,now): return {'price':100.,'time':now.isoformat(),'fresh':True}
    def execution_bars(self,market,symbol,submitted,now): return self.bars.get(symbol,[]),'waiting'
    def bar(self,symbol='AAPL',start='2026-10-27T14:35:00Z',price=100.,day='2026-10-27'):
        opened=timestamp(start)
        bar={'open_time':opened.isoformat(),'close_time':(opened+timedelta(minutes=5)).isoformat(),
             'open':price,'close':price,'session_day':day,'tradable':True,'constraint_evidence':{'lower_limit':1.,'upper_limit':2000.}}
        self.bars.setdefault(symbol,[]).append(bar)
        return bar


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.clock=Clock();self.market=Market(self.clock)
        self.store=PaperStore(Path(self.tmp.name)/'paper.sqlite',self.market,self.clock,markets=('us','cn'))
        self.token=self.store.create('us',100000)['token']
    def tearDown(self): self.tmp.cleanup()
    def order(self,**kw):
        self.serial=getattr(self,'serial',0)+1
        p=dict(symbol='AAPL',side='buy',qty=10,reason='日线方向与回踩练习',plan_stop=90.,request_key=f'test-order-key-{self.serial:04d}')
        p.update(kw);return self.store.order(self.token,p)
    def fill_buy(self):
        order=self.order();self.market.bar();self.clock.now=timestamp('2026-10-27T14:41:00Z')
        return order,self.store.state(self.token)

    def test_receipt_time_and_future_bar_only_then_idempotent(self):
        order=self.order(submitted='2020-01-01',price=1)
        self.market.bar(start='2026-10-27T14:25:00Z',price=1)
        self.market.bar()
        state=self.store.state(self.token)
        self.assertEqual(state['fills'],[])
        self.assertEqual(state['orders'][0]['submitted'],self.clock().isoformat())
        self.clock.now=timestamp('2026-10-27T14:41:00Z')
        state=self.store.state(self.token)
        self.assertEqual(state['fills'][0]['price'],100.05)
        self.assertEqual(state['fills'][0]['fee'],1)
        self.assertEqual(state['cash'],98998.5)
        self.assertEqual(state['positions'][0]['qty'],10)
        self.store.order(self.token,dict(symbol='AAPL',side='buy',qty=10,reason='日线方向与回踩练习',plan_stop=90.,request_key=order['request_key']))
        self.assertEqual(len(self.store.state(self.token)['fills']),1)
        with self.assertRaises(PaperError): self.store.cancel(self.token,order['id'])

    def test_fifo_partial_sell_net_cost_and_no_short(self):
        self.fill_buy()
        self.market.price=110
        self.order(side='sell',qty=5,plan_stop=None)
        self.market.bar(start='2026-10-27T14:45:00Z',price=110)
        self.clock.now=timestamp('2026-10-27T14:51:00Z')
        state=self.store.state(self.token)
        self.assertEqual(state['fills'][-1]['realized_pnl'],48.)
        self.assertEqual(state['positions'][0]['qty'],5)
        self.assertEqual(state['fees'],2.)
        self.assertEqual(state['closed_exits'],1)
        self.assertEqual(state['win_rate_pct'],100)
        with self.assertRaises(PaperError): self.order(side='sell',qty=6,plan_stop=None)

    def test_reserved_funds_and_gap_rejection(self):
        self.order(qty=900)
        with self.assertRaises(PaperError): self.order(qty=100)
        self.market.bar(price=200)
        self.clock.now=timestamp('2026-10-27T14:41:00Z')
        state=self.store.state(self.token)
        self.assertEqual(state['cash'],100000)
        self.assertEqual(state['orders'][0]['status'],'rejected')
        self.assertEqual(state['fills'],[])

    def test_cancel_and_owner_isolation_and_immutable_events(self):
        order=self.order()
        other=self.store.create('us',100000)['token']
        with self.assertRaises(PaperError): self.store.cancel(other,order['id'])
        self.store.cancel(self.token,order['id'])
        self.market.bar();self.clock.now=timestamp('2026-10-27T14:41:00Z')
        self.assertEqual(self.store.state(self.token)['fills'],[])
        with self.store.db() as db:
            with self.assertRaises(sqlite3.IntegrityError): db.execute('DELETE FROM events')
        with self.assertRaises(PaperError): self.store.state('invalid')

    def test_cn_t_plus_one_and_lot_and_fee(self):
        self.token=self.store.create('cn',100000)['token'];self.market.price=10
        with self.assertRaises(PaperError): self.order(symbol='万向钱潮',qty=1,plan_stop=9)
        self.order(symbol='万向钱潮',qty=100,plan_stop=9)
        self.market.bar(symbol='万向钱潮',price=10)
        self.clock.now=timestamp('2026-10-27T14:41:00Z')
        self.store.state(self.token)
        self.order(symbol='万向钱潮',side='sell',qty=100,plan_stop=None)
        self.market.bar(symbol='万向钱潮',start='2026-10-27T14:45:00Z',price=10)
        self.clock.now=timestamp('2026-10-27T14:51:00Z')
        self.assertEqual(len(self.store.state(self.token)['fills']),1)
        self.market.bar(symbol='万向钱潮',start='2026-10-28T14:35:00Z',price=10,day='2026-10-28')
        self.clock.now=timestamp('2026-10-28T14:41:00Z')
        self.assertEqual(len(self.store.state(self.token)['fills']),2)
        self.assertEqual(costs('cn','sell',100,10),5.5)

    def test_stale_marks_do_not_fabricate_equity(self):
        self.fill_buy();self.market.fresh=False
        state=self.store.state(self.token)
        self.assertIsNone(state['equity']);self.assertIsNone(state['return_pct'])
        self.assertEqual(state['valuation_status'],'unknown')
        with self.assertRaises(PaperError): self.order()

    def test_cross_order_fills_are_chronological(self):
        self.order(symbol='AAPL');self.clock.now+=timedelta(seconds=1);self.order(symbol='NVDA')
        self.market.bar('AAPL','2026-10-27T14:45:00Z')
        self.market.bar('NVDA','2026-10-27T14:35:00Z')
        self.clock.now=timestamp('2026-10-27T14:51:00Z')
        self.assertEqual([f['symbol'] for f in self.store.state(self.token)['fills']],['NVDA','AAPL'])

    def test_concurrent_requests_cannot_double_reserve(self):
        def submit(i):
            try:
                return self.store.order(self.token,dict(symbol='AAPL',side='buy',qty=900,reason='并发测试',
                    request_key=f'concurrent-test-{i:04d}'))['id']
            except PaperError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(submit,[1,2]))
        self.assertEqual(sum(bool(x) for x in results),1)
        self.assertGreaterEqual(self.store.state(self.token)['available_cash'],0)

    def test_late_revisions_cannot_backfill_before_existing_fills(self):
        self.order(symbol='AAPL');self.order(symbol='NVDA')
        self.market.bar('NVDA','2026-10-27T14:45:00Z')
        self.clock.now=timestamp('2026-10-27T14:51:00Z')
        self.store.state(self.token)
        self.market.bar('AAPL','2026-10-27T14:35:00Z')
        state=self.store.state(self.token)
        self.assertEqual([f['symbol'] for f in state['fills']],['NVDA'])
        self.assertTrue(any(o['status']=='rejected' for o in state['orders'] if o['symbol']=='AAPL'))

    def test_price_revision_does_not_rewrite_a_fill_and_expiry(self):
        self.fill_buy()
        self.market.bars['AAPL'][0]['open']=500
        self.assertEqual(self.store.state(self.token)['fills'][0]['price'],100.05)
        self.order(symbol='NVDA')
        self.clock.now+=timedelta(days=8)
        state=self.store.state(self.token)
        self.assertTrue(any(o['status']=='rejected' for o in state['orders'] if o['symbol']=='NVDA'))

    def test_idempotency_payload_mismatch_and_nonfinite_funding(self):
        order=self.order()
        with self.assertRaises(PaperError):
            self.order(request_key=order['request_key'],qty=20)
        for value in (float('nan'),float('inf'),-1,True):
            with self.assertRaises(PaperError):self.store.create('us',value)

    def test_stale_benchmark_cannot_backdate_post_sale_cash(self):
        self.fill_buy()
        self.order(side='sell',qty=10,plan_stop=None)
        self.market.bar(start='2026-10-27T14:45:00Z')
        self.clock.now=timestamp('2026-10-27T14:51:00Z')
        self.market.benchmark=lambda market,now:{'price':100,'fresh':True,'time':'2026-10-27T14:43:00+00:00'}
        state=self.store.state(self.token)
        self.assertFalse(any(p['time']=='2026-10-27T14:43:00+00:00' for p in state['curve']))

    def test_partial_lot_rounding_preserves_all_cost_cents(self):
        self.order(qty=3);self.market.bar();self.clock.now=timestamp('2026-10-27T14:41:00Z')
        self.store.state(self.token)
        for minute in (45,55,65):
            self.order(side='sell',qty=1,plan_stop=None)
            opened=timestamp('2026-10-27T14:00:00Z')+timedelta(minutes=minute)
            self.market.bar(start=opened.isoformat(),price=110)
            self.clock.now=opened+timedelta(minutes=6)
            self.store.state(self.token)
        state=self.store.state(self.token)
        self.assertEqual(state['positions'],[])
        self.assertEqual(state['cash'],100025.70)
        self.assertAlmostEqual(sum(f['realized_pnl'] for f in state['fills']),state['cash']-state['initial'],places=2)

    def test_api_auth_validation_and_server_snapshot(self):
        app=FastAPI();app.include_router(router_for(self.store));client=TestClient(app)
        self.assertEqual(client.get('/api/paper/account').status_code,401)
        headers={'Authorization':'Bearer '+self.token}
        result=client.post('/api/paper/orders',headers=headers,json={'symbol':'AAPL','side':'buy','qty':10,'reason':'手动选择','request_key':'api-order-key-00001','signal_json':'forged','submitted':'2000-01-01'})
        self.assertEqual(result.status_code,200)
        self.assertNotEqual(result.json()['signal_json'],'forged')
        self.assertEqual(client.post('/api/paper/orders',headers=headers,json={'qty':-1}).status_code,400)
        self.assertEqual(client.get('/api/paper/account',headers={'Authorization':'Bearer '+'x'*40}).status_code,401)
        response=client.get('/api/paper/account',headers=headers)
        self.assertEqual(response.status_code,200)
        self.assertNotIn('token_hash',response.text)

    def test_feature_is_closed_when_not_enabled(self):
        app=FastAPI();app.include_router(router_for(self.store,enabled=lambda:False))
        client=TestClient(app)
        self.assertEqual(client.post('/api/paper/accounts',json={'market':'us','initial':100000}).status_code,503)

    def test_product_defaults_to_us_only_and_rejects_cn_credentials(self):
        scoped=PaperStore(self.store.path,self.market,self.clock)
        app=FastAPI();app.include_router(router_for(scoped));client=TestClient(app)
        response=client.post('/api/paper/accounts',json={'market':'cn','initial':100000})
        self.assertEqual(response.status_code,400)
        self.assertIn('仅支持美股',response.json()['detail'])
        legacy_cn=self.store.create('cn',100000)['token']
        with self.assertRaises(PaperError):scoped.state(legacy_cn)
        with self.assertRaises(PaperError):scoped.order(legacy_cn,{'request_key':'legacy-cn-order-0001'})


class Sessions:
    def valid(self,market,opened,closed): return opened.date().isoformat() if opened.hour==14 else None
    def fresh(self,market,closed,now): return now-closed<=timedelta(minutes=30)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        for folder in ('charts','charts_cn'): (self.root/folder).mkdir()
        self.data=FileMarketData(self.root,Sessions());self.now=timestamp('2026-10-27T14:51:00Z')
        self.write('signals.json',{'symbols':{'AAPL':{},'纳指':{}}})
        self.write('signals_cn.json',{'symbols':{'万向钱潮':{},'上证指数':{}}})
    def tearDown(self): self.tmp.cleanup()
    def write(self,name,data): (self.root/name).write_text(json.dumps(data))
    def chart(self,name,time):
        self.write(name,{'levels':{'5m':{'ohlc':[{'time':timestamp(time).timestamp(),'open':10,'high':10.1,'low':9.9,'close':10}]}}})
    def test_completed_bar_labels_and_indices(self):
        self.chart('charts/AAPL.json','2026-10-27T14:50:00Z')
        self.assertIsNone(self.data.quote('us','AAPL',self.now))
        self.chart('charts/AAPL.json','2026-10-27T14:40:00Z')
        self.assertEqual(self.data.quote('us','AAPL',self.now)['time'],'2026-10-27T14:45:00+00:00')
        self.assertIsNone(self.data.quote('us','纳指',self.now))
        self.assertFalse(self.data.allowed('cn','上证指数'))
    def test_cn_limits_suspension_and_timestamp_evidence(self):
        self.chart('charts_cn/万向钱潮.json','2026-10-27T14:40:00Z')
        bars=self.data.bars('cn','万向钱潮',self.now)
        self.assertEqual(bars[0]['open_time'],'2026-10-27T14:35:00+00:00')
        # Include a preceding bar to establish that the bounded history covers submission.
        data=json.loads((self.root/'charts_cn/万向钱潮.json').read_text())
        data['levels']['5m']['ohlc'].insert(0,{**data['levels']['5m']['ohlc'][0],'time':timestamp('2026-10-27T14:30:00Z').timestamp()})
        self.write('charts_cn/万向钱潮.json',data)
        submitted=timestamp('2026-10-27T14:31:00Z')
        self.assertEqual(self.data.execution_bars('cn','万向钱潮',submitted,self.now)[0],[])
        rule={'upper_limit':11.,'lower_limit':9.,'suspended':False,'source':'test fixture','observed_at':'2026-10-27T14:00:00Z'}
        for extra,expected in [({},1),({'suspended':True},0),({'upper_limit':10.},0),({'observed_at':'2026-10-27T15:00:00Z'},0)]:
            self.write('paper_cn_rules.json',{'2026-10-27':{'万向钱潮':{**rule,**extra}}})
            self.assertEqual(len(self.data.execution_bars('cn','万向钱潮',submitted,self.now)[0]),expected)
    def test_calendar_failure_closes_matching(self):
        from unittest.mock import patch
        with patch('builtins.__import__',side_effect=ImportError('calendar offline')):
            self.assertIsNone(ExchangeSessions().session('us','2026-10-27'))

    def test_missing_first_future_bar_cannot_be_replaced_by_a_later_price(self):
        self.chart('charts/AAPL.json','2026-10-27T14:45:00Z')
        data=json.loads((self.root/'charts/AAPL.json').read_text())
        data['levels']['5m']['ohlc'].insert(0,{**data['levels']['5m']['ohlc'][0],'time':timestamp('2026-10-27T14:25:00Z').timestamp()})
        self.write('charts/AAPL.json',data)
        bars,note=self.data.execution_bars('us','AAPL',timestamp('2026-10-27T14:31:00Z'),self.now)
        self.assertEqual(bars,[])
        self.assertIn('缺口',note)
    def test_session_break_holiday_and_early_close(self):
        class Calendar(ExchangeSessions):
            def session(self,market,day):
                if day!='2026-10-27':return None
                return timestamp(day+'T14:00:00Z'),timestamp(day+'T18:00:00Z'),(timestamp(day+'T16:00:00Z'),timestamp(day+'T17:00:00Z'))
        calendar=Calendar()
        self.assertIsNone(calendar.valid('us',timestamp('2026-10-28T14:00:00Z'),timestamp('2026-10-28T14:05:00Z')))
        self.assertIsNone(calendar.valid('us',timestamp('2026-10-27T16:00:00Z'),timestamp('2026-10-27T16:05:00Z')))
        self.assertIsNone(calendar.valid('us',timestamp('2026-10-27T18:00:00Z'),timestamp('2026-10-27T18:05:00Z')))
        self.assertTrue(calendar.fresh('us',timestamp('2026-10-27T16:00:00Z'),timestamp('2026-10-27T16:30:00Z')))


if __name__=='__main__': unittest.main()

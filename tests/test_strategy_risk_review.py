import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from automatic_strategy import AutomaticStrategy, StrategyGroup, RULES_V2
from paper_trading import PaperStore, PaperError, timestamp
from strategy_risk import planned_loss, portfolio_risk, budget_money
from strategy_routes import strategy_router
from tests.test_automatic_strategy import Source, signal
import tests.test_paper_trading as fixtures


class RiskTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.clock=fixtures.Clock();self.market=fixtures.Market(self.clock)
        self.store=PaperStore(Path(self.tmp.name)/'ledger.sqlite',self.market,self.clock)
        self.source=Source();self.engine=AutomaticStrategy(self.store,self.source,rules=RULES_V2)
        self.source.publish();self.engine.tick()
    def tearDown(self):self.tmp.cleanup()
    def state(self):return self.engine.report()['account']
    def enter(self,symbol='AAPL',*,extreme=90,kind='2B'):
        if symbol!='AAPL':self.source.publish(symbol=symbol);self.engine.tick()
        candidate=signal(kind);candidate['price']=extreme
        self.source.publish([candidate],symbol=symbol);self.engine.tick()
    def fill(self,symbol='AAPL',price=100):
        self.market.bar(symbol=symbol,price=price);self.clock.now=timestamp('2026-10-27T14:41:00Z');self.engine.tick()
    def exits(self,price=110):
        self.source.publish([signal('3S',label='2026-10-27T14:00:00Z')]);self.engine.tick()
        self.market.bar(start='2026-10-27T14:45:00Z',price=price)
        self.clock.now=timestamp('2026-10-27T14:51:00Z');self.engine.tick()

    def test_risk_sizing_includes_costs_and_accounts_use_current_equity(self):
        self.enter();order=self.state()['orders'][0];plan=json.loads(order['signal_json'])['risk_plan']
        self.assertLess(order['qty'],99)
        self.assertLessEqual(planned_loss(order['qty'],100.05,87.3),500)
        self.assertEqual(plan['max_loss_usd'],500)
        self.assertGreater(planned_loss(order['qty']+1,100.05,87.3),500)
        self.fill();self.exits(price=90)
        self.market.price=100;self.clock.now=timestamp('2026-10-27T14:52:00Z')
        self.enter('MRNA');orders=self.state()['orders']
        new=next(o for o in orders if o['symbol']=='MRNA')
        plan=json.loads(new['signal_json'])['risk_plan']
        self.assertLess(plan['single_trade_limit_usd'],500)
        self.assertEqual(plan['single_trade_limit_usd'],budget_money(self.state()['cash'],.005))

    def test_gap_risk_rejects_without_reading_future_marks(self):
        self.enter();self.market.bar(price=110);self.clock.now=timestamp('2026-10-27T14:41:00Z')
        # 仅撮合；未来quote会抛错，证明成交风险复核只用冻结证据和当根open。
        with self.store.db() as db:
            a=self.engine.setup(db)
            with patch.object(self.market,'quote',side_effect=AssertionError('future quote')):
                self.store.reconcile(db,a)
        self.assertEqual(self.state()['fills'],[])
        self.assertEqual(self.state()['orders'][0]['status'],'rejected')
        self.assertIn('预算',self.state()['orders'][0]['message'])

    def test_nominal_cap_after_gap_and_tampered_plan_fail_closed(self):
        self.enter(extreme=100);self.market.bar(price=101);self.clock.now=timestamp('2026-10-27T14:41:00Z');self.engine.tick()
        self.assertEqual(self.state()['orders'][0]['status'],'rejected')
        self.assertEqual(self.state()['positions'],[])

    def test_missing_frozen_risk_evidence_rejects_buy(self):
        self.enter()
        with self.store.db() as db:
            row=db.execute("SELECT * FROM orders WHERE side='buy'").fetchone()
            evidence=json.loads(row['signal_json']);evidence['risk_plan']={'schema':'us-risk-plan-v2'}
            db.execute('UPDATE orders SET signal_json=? WHERE id=?',(json.dumps(evidence),row['id']))
        self.fill()
        self.assertEqual(self.state()['orders'][0]['status'],'rejected')
        self.assertEqual(self.state()['fills'],[])

    def test_pending_risk_reservations_are_released_on_repaint(self):
        self.enter();self.assertEqual(self.engine.report()['risk']['used_risk_usd'],500)
        self.source.publish();self.engine.tick()
        self.assertEqual(self.engine.report()['risk']['used_risk_usd'],0)

    def test_fractional_cents_are_never_rounded_above_budget(self):
        self.assertEqual(budget_money(100001.99,.005),500)
        self.assertLessEqual(budget_money(100001.99,.02),100001.99*.02)

    def test_unknown_groups_and_same_sector_pending_are_blocked(self):
        self.enter('NVDA');self.enter('AMD');self.enter('MU');self.enter('SPCX')
        self.assertEqual({o['symbol'] for o in self.state()['orders']},{'NVDA','AMD'})
        reasons=[e['payload']['reason'] for e in self.engine.report()['decisions'] if e['payload']['action']=='skip']
        self.assertTrue(any('集中度' in r for r in reasons));self.assertTrue(any('分组' in r for r in reasons))

    def test_correlated_group_and_portfolio_budget_include_pending(self):
        self.enter('NVDA');self.enter('AAPL');self.enter('TSLA');self.enter('META')
        self.assertEqual(len(self.state()['orders']),3)  # 同属科技成长，即使细分组不同。
        self.enter('MRNA');self.assertEqual(len(self.state()['orders']),4)
        self.enter('NOK');self.assertEqual(len(self.state()['orders']),4)
        risk=self.engine.report()['risk'];self.assertEqual(risk['used_risk_usd'],2000)

    def test_stale_held_quotes_missing_stop_and_triggered_stop_block_buys(self):
        self.enter();self.fill();self.market.fresh=False;self.enter('MRNA')
        self.assertEqual(len(self.state()['orders']),1)
        self.market.fresh=True
        with self.store.db() as db:db.execute("UPDATE protective_stops SET status='triggered' WHERE status='active'")
        self.assertFalse(self.engine.report()['risk']['known'])
        self.assertIn('保护',self.engine.report()['risk']['reason'])

    def test_versions_have_separate_baselines_accounts_and_legacy_api_default(self):
        v1=AutomaticStrategy(self.store,self.source);v1.tick();self.enter()
        self.assertEqual(v1.report()['account']['orders'],[])
        self.assertEqual(len(self.state()['orders']),1)
        app=FastAPI();app.include_router(strategy_router(v1,variants={'v1':v1,'v2':self.engine}))
        client=TestClient(app)
        self.assertEqual(client.get('/api/strategy/us').json()['rules']['version'],'us-daily-30m-v1')
        self.assertEqual(client.get('/api/strategy/us?version=v2').json()['rules']['version'],RULES_V2['version'])
        self.assertEqual(client.get('/api/strategy/us?version=other').status_code,400)
        self.assertEqual(client.post('/api/strategy/us?version=v2').status_code,405)
        with self.store.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM managed_accounts').fetchone()[0],2)

    def test_exit_remains_allowed_in_unknown_environment(self):
        self.enter();self.fill()
        self.source.publish([signal('3S',label='2026-10-27T14:00:00Z')],context='unknown',direction='down');self.engine.tick()
        self.assertEqual(self.state()['orders'][0]['side'],'sell')

    def test_review_round_trip_r_and_exit_group_reconcile_to_cash(self):
        self.enter();self.fill();self.exits()
        report=self.engine.report();review=report['review'];trade=review['trades'][0]
        self.assertEqual(review['summary']['closed_trades'],1)
        self.assertEqual(review['by_entry']['2B']['closed_trades'],1)
        self.assertEqual(review['by_exit']['3S']['closed_trades'],1)
        self.assertAlmostEqual(trade['realized_pnl'],self.state()['cash']-100000,places=2)
        self.assertAlmostEqual(trade['r_multiple'],trade['realized_pnl']/trade['initial_risk_usd'])
        self.assertGreater(trade['holding_hours'],0)
        self.assertGreater(trade['observed_mfe_pct'],0)
        self.assertIn('not_intrabar',trade['excursion_basis'])
        self.assertEqual(trade['observed_mae_pct'],min(0,trade['observed_mae_pct']))

    def test_partial_exits_count_as_one_trade_and_preserve_cost_cents(self):
        self.enter();self.fill();qty=self.state()['positions'][0]['qty']
        with self.store.db() as db:
            a=self.engine.setup(db)
            self.store._submit_order(db,a,dict(request_key='strategy-partial-test-0001',symbol='AAPL',side='sell',
                qty=qty//2,reason='test partial',plan_stop=None),observation={'signal':{'type':'2S'}})
        self.market.bar(start='2026-10-27T14:45:00Z',price=110)
        self.clock.now=timestamp('2026-10-27T14:51:00Z');self.engine.tick()
        self.assertEqual(self.engine.report()['review']['summary']['closed_trades'],0)
        self.source.publish([signal('3S',label='2026-10-27T14:00:00Z')]);self.engine.tick()
        self.market.bar(start='2026-10-27T14:55:00Z',price=105)
        self.clock.now=timestamp('2026-10-27T15:01:00Z');self.engine.tick()
        report=self.engine.report();self.assertEqual(report['review']['summary']['closed_trades'],1)
        self.assertEqual(report['review']['by_exit']['mixed']['closed_trades'],1)
        self.assertAlmostEqual(report['review']['summary']['realized_pnl'],self.state()['cash']-100000,places=2)

    def test_stop_review_and_legacy_data_are_not_fabricated(self):
        self.enter();self.fill()
        self.market.bar(start='2026-10-27T14:45:00Z',price=80)
        self.clock.now=timestamp('2026-10-27T14:51:00Z');self.engine.tick()
        self.assertEqual(self.engine.report()['review']['by_exit']['automatic_stop']['closed_trades'],1)
        # 旧事件缺少lot关联时应明确缺失，不猜造一笔完整交易或R。
        from strategy_review import review
        state=copy.deepcopy(self.state())
        for fill in state['fills']:fill.pop('lot_id',None);fill.pop('lot_allocations',None)
        with self.store.db() as db:result=review(db,self.engine.setup(db),state)
        self.assertEqual(result['summary']['closed_trades'],0)
        self.assertIsNone(result['summary']['average_r'])
        self.assertEqual(result['unattributed_legacy_fills'],2)

    def test_version_failure_does_not_stop_other_version(self):
        old=unittest.mock.Mock(strategy_id='old');new=unittest.mock.Mock(strategy_id='new')
        old.tick.side_effect=RuntimeError('test')
        with self.assertLogs('automatic_strategy',level='ERROR'): StrategyGroup(old,new).tick()
        new.tick.assert_called_once()

    def test_comparison_uses_shared_interval_not_different_initial_values(self):
        from strategy_review import common_comparison
        v1=AutomaticStrategy(self.store,self.source);v1.tick()
        with self.store.db() as db:
            old=v1.setup(db);new=self.engine.setup(db)
            db.execute('INSERT INTO equity(account,time,value) VALUES(?,?,?)',(old['id'],'2026-10-27T15:00:00+00:00',110000))
            db.execute('INSERT INTO equity(account,time,value) VALUES(?,?,?)',(new['id'],'2026-10-27T15:00:00+00:00',100000))
            db.execute('INSERT INTO equity(account,time,value) VALUES(?,?,?)',(old['id'],'2026-10-27T16:00:00+00:00',111100))
            db.execute('INSERT INTO equity(account,time,value) VALUES(?,?,?)',(new['id'],'2026-10-27T16:00:00+00:00',100500))
            # 两个账户真实启动不同；共同窗口必须晚于较新的启动时点。
            db.execute('UPDATE accounts SET created=? WHERE id=?',('2026-10-27T14:40:00+00:00',new['id']))
            result=common_comparison(db)
            self.assertEqual(result['since'],'2026-10-27T15:00:00+00:00')
            self.assertAlmostEqual(result['returns'][v1.strategy_id],1)
            self.assertAlmostEqual(result['returns'][self.engine.strategy_id],.5)


if __name__=='__main__':unittest.main()

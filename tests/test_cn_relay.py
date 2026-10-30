"""题材接力的真实采样时序契约；全部为明确夹具，不使用行情收益。"""
import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from cn_relay import analyze
from cn_research import CNResearch, dump
from cn_routes import research_router

DAY='2026-10-29'
ANCHOR=datetime(2026,10,29,2,30,tzinfo=timezone.utc)
SESSION=(ANCHOR.replace(hour=1,minute=30),ANCHOR.replace(hour=7,minute=0),
         (ANCHOR.replace(hour=3,minute=30),ANCHOR.replace(hour=5,minute=0)))


def stock(code,name,theme,state='sealed'):
    return dict(code=code,name=name,state=state,boards=1,price=10,change_pct=10,
        theme=dict(id=theme,name='机器人' if theme=='robot' else '商业航天',source='kaipanla',trade_date=DAY) if theme else None,
        concepts=[],source_event_time=(ANCHOR-timedelta(minutes=30)).isoformat())


def timeline():
    frames=[]
    for minute in range(-30,31):
        now=ANCHOR+timedelta(minutes=minute)
        rows=[stock('000001','机器人甲','robot','sealed' if minute < -1 else 'broken'),
              stock('000002','机器人乙','robot','sealed' if minute < 0 else 'broken'),
              stock('600001','航天甲','space'),stock('600003','航天回封','space','sealed' if minute>=2 else 'broken')]
        if minute>=1:rows.append(stock('600002','航天新见一','space'))
        if minute>=4:rows.append(stock('600004','航天新见二','space'))
        pools={'up':[s for s in rows if s['state']=='sealed'],'broken':[s for s in rows if s['state']=='broken']}
        sources={key:dict(status='ok',trade_date=DAY,observed_at=now.isoformat()) for key in ('up','broken')}
        frames.append(dict(trade_date=DAY,observed_at=now.isoformat(),pools=pools,sources=sources,coherent=True))
    return frames


def event(report):return next(e for e in report['events'] if e['theme']['id']=='robot')
def window(report,n=5):return next(w for w in event(report)['windows'] if w['minutes']==n)
def space(w):return next(g for g in w['rows'] if g['id']=='space')


class RelayTests(unittest.TestCase):
    def setUp(self):self.frames=timeline();self.now=ANCHOR+timedelta(minutes=30)
    def report(self):return analyze(self.frames,DAY,self.now,SESSION)

    def test_event_anchor_and_three_completed_windows(self):
        d=self.report();e=event(d)
        self.assertEqual(e['observed_at'],ANCHOR.isoformat());self.assertEqual(len(e['opened']),2)
        for n in (5,15,30):
            w=window(d,n);g=space(w)
            self.assertEqual(w['status'],'complete');self.assertEqual(g['net_delta'],3)
            self.assertEqual(g['before_delta'],0);self.assertEqual(g['acceleration'],3)
            self.assertEqual(len(g['new_seen']),2);self.assertEqual(len(g['resealed']),1)
            self.assertEqual(len(g['gained']),3);self.assertEqual(g['lost'],[])
            self.assertEqual(w['pool_net_delta'],3);self.assertEqual(w['pool_before_delta'],-2)
            self.assertFalse(w['partial']);self.assertEqual(w['scope'],'fixed_verified_cohort')

    def test_future_snapshots_do_not_complete_pending_windows(self):
        self.now=ANCHOR+timedelta(minutes=4)
        for w in event(self.report())['windows']:
            self.assertEqual(w['status'],'pending');self.assertEqual(w['rows'],[])

    def test_completed_result_does_not_change_when_future_attribution_changes(self):
        early=analyze(self.frames,DAY,ANCHOR+timedelta(minutes=5),SESSION)
        for f in self.frames:
            if datetime.fromisoformat(f['observed_at'])>ANCHOR+timedelta(minutes=5):
                for rows in f['pools'].values():
                    for s in rows:s['theme']={'id':'future','name':'未来题材','source':'kaipanla','trade_date':DAY}
        self.assertEqual(window(early),window(self.report()))

    def test_gap_and_invalid_pool_do_not_become_zero_growth(self):
        original=copy.deepcopy(self.frames)
        for kind in ('gap','invalid'):
            self.frames=copy.deepcopy(original)
            if kind=='gap':self.frames.pop(32)
            else:self.frames[32]['coherent']=False
            w=window(self.report());self.assertEqual(w['status'],'incomplete');self.assertEqual(w['rows'],[])

    def test_missing_prior_window_does_not_fake_acceleration(self):
        self.frames.pop(10)
        w=window(self.report(),30)
        self.assertEqual(w['status'],'complete');self.assertEqual(w['before_status'],'insufficient')
        self.assertEqual(space(w)['net_delta'],3);self.assertIsNone(space(w)['acceleration'])

    def test_reclassification_does_not_inflate_net_counts(self):
        for f in self.frames:
            for key in ('up','broken'):
                f['pools'][key]=[s for s in f['pools'][key] if s['code'] not in ('600002','600003','600004')]
                for s in f['pools'][key]:
                    if s['code']=='600001' and f['observed_at']>ANCHOR.isoformat():s['theme']['id']='changed'
        w=window(self.report());self.assertEqual(space(w)['net_delta'],0)
        self.assertEqual(w['fixed_theme_changes'],1);self.assertFalse(any(g['id']=='changed' for g in w['rows']))

    def test_late_known_theme_does_not_convert_existing_sealed_stock_to_inflow(self):
        for f in self.frames:
            s=stock('300001','晚归因','space' if f['observed_at']>ANCHOR.isoformat() else None)
            f['pools']['up'].append(s)
        w=window(self.report());self.assertTrue(w['partial']);self.assertEqual(w['unknown_stocks'],1)
        self.assertEqual(space(w)['net_delta'],3)

    def test_repeated_opening_of_one_stock_cannot_trigger_concentration(self):
        for f in self.frames:
            minute=round((datetime.fromisoformat(f['observed_at'])-ANCHOR).total_seconds()/60)
            rows=sum(f['pools'].values(),[])
            for s in rows:
                if s['code']=='000001':s['state']='broken' if minute in (-1,1,3) else 'sealed'
                if s['code']=='000002':s['state']='sealed'
            f['pools']={key:[s for s in rows if s['state']==state] for key,state in [('up','sealed'),('broken','broken')]}
        self.assertEqual(self.report()['events'],[])

    def test_repeated_reseal_does_not_inflate_net_or_unique_counts(self):
        for f in self.frames:
            minute=round((datetime.fromisoformat(f['observed_at'])-ANCHOR).total_seconds()/60)
            rows=sum(f['pools'].values(),[])
            rows=[s for s in rows if s['code'] not in ('600002','600003','600004')]
            for s in rows:
                if s['code']=='600001':s['state']='broken' if minute in (1,3) else 'sealed'
            f['pools']={key:[s for s in rows if s['state']==state] for key,state in [('up','sealed'),('broken','broken')]}
        g=space(window(self.report()))
        self.assertEqual(g['net_delta'],0);self.assertEqual(len(g['opened']),1)
        self.assertEqual(len(g['resealed']),1);self.assertEqual(g['gained'],[])

    def test_partial_stale_or_wrong_day_source_cannot_supply_trigger_evidence(self):
        for kind in ('partial','future_receive','wrong_day'):
            frames=timeline();f=frames[29]
            if kind=='partial':f['sources']['up']['status']='partial'
            if kind=='future_receive':f['sources']['up']['observed_at']=(ANCHOR+timedelta(minutes=10)).isoformat()
            if kind=='wrong_day':f['sources']['broken']['trade_date']='2026-10-28'
            self.assertEqual(analyze(frames,DAY,self.now,SESSION)['events'],[])

    def test_initial_broken_baseline_and_renamed_or_unattributed_triggers_are_not_signals(self):
        for kind in ('baseline','unknown','rename'):
            frames=timeline()
            for f in frames:
                if kind=='baseline':f['pools']['up']=[]
                else:
                    for rows in f['pools'].values():
                        for s in rows:
                            if s['code']=='000001':
                                if kind=='unknown':s['theme']=None
                                elif s['state']=='broken':s['name']='错误名字'
            self.assertEqual(analyze(frames,DAY,self.now,SESSION)['events'],[])

    def test_lunch_close_and_other_day_are_not_joined(self):
        shifted=copy.deepcopy(self.frames)
        offset=timedelta(minutes=56)  # 11:26观察到事件
        for f in shifted:
            f['observed_at']=(datetime.fromisoformat(f['observed_at'])+offset).isoformat()
            for source in f['sources'].values():source['observed_at']=f['observed_at']
        d=analyze(shifted,DAY,self.now+offset,SESSION)
        self.assertTrue(all(w['status']=='session_break' for w in event(d)['windows']))
        for f in shifted:f['trade_date']='2026-10-28'
        self.assertEqual(analyze(shifted,DAY,self.now+offset,SESSION)['events'],[])

    def test_no_endpoint_or_calendar_is_unknown(self):
        self.frames=self.frames[:35]  # 最后快照为触发后4分钟
        self.assertEqual(window(self.report())['status'],'incomplete')
        self.assertEqual(analyze(self.frames,DAY,self.now,None)['status'],'unavailable')
        self.assertEqual(analyze([],DAY,self.now,SESSION)['events'],[])

    def test_store_read_only_api_validation_and_legacy_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Calendar:
                def context(self,now):return {'trade_date':DAY}
                def session(self,day):return SESSION
            store=CNResearch(Path(tmp)/'research.sqlite',calendar=Calendar(),clock=lambda:self.now)
            with store.db() as db:
                for f in self.frames:db.execute('INSERT INTO snapshots(date,observed_at,payload) VALUES(?,?,?)',(DAY,f['observed_at'],dump(f)))
                before=db.total_changes
            app=FastAPI();app.include_router(research_router(store));client=TestClient(app)
            response=client.get('/api/cn/relay');self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers['cache-control'],'no-store');self.assertEqual(space(window(response.json()))['net_delta'],3)
            self.assertEqual(client.post('/api/cn/relay').status_code,405)
            for value in ('today','2026-02-30','../etc/passwd'):
                self.assertEqual(client.get('/api/cn/relay',params={'date':value}).status_code,400)
            self.assertEqual(client.get('/api/cn/relay?date=2026-10-28').json()['status'],'unavailable')
            with store.db() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0],len(self.frames))
                self.assertEqual(db.execute('SELECT COUNT(*) FROM observation_events').fetchone()[0],0)


if __name__=='__main__':unittest.main()

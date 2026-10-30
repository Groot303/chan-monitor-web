import ast
import copy
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from cn_limitup_source import build_snapshot,normalize_pool,normalize_attributions,ResearchClock
from cn_research import CNResearch
from cn_routes import research_router


class Clock:
    def __init__(self):self.now=datetime(2026,10,29,6,tzinfo=timezone.utc)
    def __call__(self):return self.now


class Calendar:
    def context(self,now):return dict(trade_date='2026-10-29',active=True,phase='trading',expected_at=now.isoformat(),session_close='2026-10-29T07:00:00+00:00')


def raw_stock(code='000559',name='测试甲',boards=2):
    return dict(c=code,n=name,p=10000,zdp=10.,lbc=boards,ylbc=boards-1,amount=1230000,hs=5.,fund=800000,
                fbt=93001,lbt=100002,zbc=1,hybk='汽车零部件',zttj={'days':boards,'ct':boards})


def fixtures(clock):
    up=[raw_stock(),raw_stock('002050','测试乙',3)]
    broken=[raw_stock('603938','测试丙',1)]
    previous=[raw_stock(),raw_stock('002050','测试乙',3),raw_stock('600110','测试丁',2)]
    envelopes=[]
    for key,rows in dict(up=up,broken=broken,previous=previous,down=[]).items():
        envelopes.append(dict(key=key,started_at=clock().isoformat(),received_at=clock().isoformat(),
            payload=dict(rc=0,data=dict(qdate=20261029,tc=len(rows),pool=rows))))
    rows=[]
    for s in up+broken:
        row=[None]*23;row[0]=s['c'];row[1]=s['n'];row[4]=clock().timestamp();row[5]='机器人';row[12]='机器人、其他概念';row[19]='801159';rows.append(row)
    envelopes.append(dict(key='attribution1',received_at=clock().isoformat(),payload={'errcode':'0','info':[rows]}))
    return envelopes


class Source:
    def __init__(self,clock):self.clock=clock;self.rows=fixtures(clock);self.calls=0
    def fetch(self,day):
        self.calls+=1;data=copy.deepcopy(self.rows)
        for item in data:item['received_at']=self.clock().isoformat()
        return data


class CNResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.clock=Clock();self.source=Source(self.clock)
        self.research=CNResearch(Path(self.tmp.name)/'cn.sqlite',self.source,Calendar(),self.clock)
    def tearDown(self):self.tmp.cleanup()
    def advance(self):self.clock.now+=timedelta(minutes=1)
    def snapshot(self):return build_snapshot(self.source.fetch('2026-10-29'),Calendar().context(self.clock()),self.clock())

    def test_pool_fields_leading_zero_and_theme_not_industry(self):
        data=self.snapshot();stock=data['pools']['up'][0]
        self.assertEqual(stock['code'],'000559');self.assertEqual(stock['price'],10)
        self.assertEqual(stock['seal_amount'],800000)
        self.assertEqual(stock['industry'],'汽车零部件');self.assertEqual(stock['theme']['name'],'机器人')
        self.assertEqual(stock['concepts'],['机器人','其他概念'])
        self.assertEqual(stock['first_seal'],'09:30:01')
        self.assertEqual(data['summary']['down_count'],0)
        self.assertEqual(data['summary']['sealed_count'],2)

    def test_only_sealed_attribution_cannot_imply_zero_broken_in_every_theme(self):
        # 复现线上：归因接口只返回封板股；炸板池有数据，但全被归到待核验。
        self.source.rows[-1]['payload']['info'][0].pop()
        self.research.collect();data=self.research.report()
        group=next(g for g in data['themes'] if g['id']!='unclassified')
        self.assertEqual(data['summary']['broken_count'],1)
        self.assertEqual(data['summary']['attributed_broken'],0)
        self.assertEqual(data['summary']['unattributed_broken'],1)
        self.assertIsNone(group['broken_count']);self.assertEqual(group['known_broken_count'],0)
        self.assertFalse(group['broken_count_complete']);self.assertEqual(data['status'],'partial')

    def test_same_day_attribution_survives_opening_and_preserves_evidence_time(self):
        self.research.collect();first=self.clock().isoformat();self.advance()
        moved=self.source.rows[0]['payload']['data']['pool'].pop(0);self.source.rows[0]['payload']['data']['tc']=1
        self.source.rows[1]['payload']['data']['pool'].append(moved);self.source.rows[1]['payload']['data']['tc']=2
        self.source.rows[-1]['payload']['info'][0]=[r for r in self.source.rows[-1]['payload']['info'][0] if r[0]!=moved['c']]
        self.research.collect();data=self.research.report()
        stock=next(s for s in data['pools']['broken'] if s['code']==moved['c'])
        self.assertEqual(stock['theme']['name'],'机器人');self.assertEqual(stock['attribution_basis'],'earlier_today')
        self.assertEqual(stock['attribution_observed_at'],first)
        self.assertEqual(data['summary']['attributed_broken'],2)
        self.assertEqual(data['themes'][0]['broken_count'],2)

    def test_upgrade_recovers_only_retained_evidence_and_does_not_rewrite_history(self):
        self.research.collect()
        with self.research.db() as db:
            db.execute('DELETE FROM theme_memory')
            before=db.execute('SELECT payload FROM snapshots ORDER BY id LIMIT 1').fetchone()['payload']
        self.advance();self.source.rows[-1]['payload']['info'][0]=[]
        self.research.collect();data=self.research.report()
        self.assertEqual(data['summary']['attributed_broken'],1)
        self.assertEqual(data['pools']['broken'][0]['attribution_basis'],'earlier_today')
        with self.research.db() as db:
            self.assertEqual(db.execute('SELECT payload FROM snapshots ORDER BY id LIMIT 1').fetchone()['payload'],before)

    def test_old_snapshot_zero_is_exposed_as_unknown_without_backfilling_theme(self):
        self.source.rows[-1]['payload']['info'][0].pop();self.research.collect()
        with self.research.db() as db:
            raw=json.loads(db.execute('SELECT payload FROM daily').fetchone()['payload'])
            for group in raw['themes']:group.update(broken_count=0)
            raw['summary'].pop('attributed_broken')
            db.execute('UPDATE daily SET payload=?',(json.dumps(raw),))
        data=self.research.report('2026-10-29')
        self.assertIsNone(data['themes'][0]['broken_count'])
        self.assertIsNone(data['pools']['broken'][0]['theme'])

    def test_upgrade_refreshes_legacy_snapshot_once_during_lunch(self):
        self.research.collect();self.advance()
        class Pause:
            def context(self,now):return {**Calendar().context(now),'active':False}
        self.research.calendar=Pause();self.research.collect()
        self.assertEqual(self.source.calls,1,'已升级快照在午休不重复采集')
        with self.research.db() as db:
            raw=json.loads(db.execute('SELECT payload FROM snapshots ORDER BY id DESC LIMIT 1').fetchone()['payload'])
            raw.pop('attribution_contract')
            db.execute('UPDATE snapshots SET payload=?',(json.dumps(raw),))
        self.research.collect()
        self.assertEqual(self.source.calls,2,'旧版本升级需要一次真实刷新，而非修改旧快照')
        self.advance();self.research.collect();self.assertEqual(self.source.calls,2)

    def test_prior_attribution_rejects_other_day_future_evidence_and_name_mismatch(self):
        self.research.collect()
        with self.research.db() as db:prior=self.research.attributions(db,'2026-10-29',self.clock())
        self.source.rows[-1]['payload']['info'][0]=[]
        for kind in ('day','future','name'):
            notes=copy.deepcopy(prior)
            for note in notes.values():
                if kind=='day':note['theme']['trade_date']='2026-10-28'
                if kind=='future':note['attribution_observed_at']=(self.clock()+timedelta(minutes=5)).isoformat()
                if kind=='name':note['name']='同代码错误名称'
            data=build_snapshot(self.source.fetch('2026-10-29'),Calendar().context(self.clock()),self.clock(),notes)
            self.assertTrue(all(s['theme'] is None for rows in data['pools'].values() for s in rows))

    def test_placeholder_reason_and_conflicting_current_attribution_are_unknown(self):
        for label in ('无','--','暂无'):
            p=copy.deepcopy(self.source.rows[-1]['payload'])
            for row in p['info'][0]:row[5]=label
            self.assertEqual(normalize_attributions(p,'2026-10-29'),{})
        conflict=copy.deepcopy(self.source.rows[-1]);conflict['key']='attribution2'
        for row in conflict['payload']['info'][0]:row[5]='相互冲突';row[19]='conflict'
        repeat=copy.deepcopy(self.source.rows[-1]);repeat['key']='attribution3'
        self.source.rows.extend([conflict,repeat])
        self.assertEqual(self.snapshot()['summary']['attributed_sealed'],0,'后续相同记录不能冲掉冲突标记')

    def test_yesterday_attribution_is_never_mixed_into_today(self):
        for row in self.source.rows[-1]['payload']['info'][0]:row[4]-=86400
        data=self.snapshot()
        self.assertTrue(all(s['theme'] is None for s in data['pools']['up']))
        self.assertEqual(data['summary']['attributed_sealed'],0)
        self.assertEqual(data['themes'][0]['id'],'unclassified')

    def test_source_day_duplicate_partial_and_bad_price_are_rejected(self):
        original=self.source.rows[0]['payload']
        for patch in ('day','duplicate','price'):
            d=copy.deepcopy(original)
            if patch=='day':d['data']['qdate']=20261028
            if patch=='duplicate':d['data']['pool'].append(d['data']['pool'][0])
            if patch=='price':d['data']['pool'][0]['p']=float('nan')
            with self.assertRaises(ValueError):normalize_pool(d,'up','2026-10-29')
        d=copy.deepcopy(original);d['data']['tc']=100
        _,quality=normalize_pool(d,'up','2026-10-29');self.assertFalse(quality['complete'])

    def test_missing_pool_is_unknown_not_zero(self):
        self.source.rows[1]={'key':'broken','received_at':self.clock().isoformat(),'error':'offline'}
        data=self.snapshot()
        self.assertIsNone(data['summary']['broken_count']);self.assertIsNone(data['summary']['snapshot_open_ratio_pct'])
        self.assertFalse(data['coherent'])
        self.assertTrue(all(g['broken_count'] is None for g in data['themes']))

    def test_empty_valid_pools_are_zero_and_missing_pools_are_not(self):
        for envelope in self.source.rows[:4]:envelope['payload']['data'].update(pool=[],tc=0)
        data=self.snapshot()
        self.assertEqual(data['summary']['sealed_count'],0)
        self.assertEqual(data['summary']['broken_count'],0)
        self.assertEqual(data['themes'],[])
        self.assertIsNone(data['summary']['snapshot_open_ratio_pct'])

    def test_research_clock_uses_sessions_and_pauses_at_lunch(self):
        class Sessions:
            def session(self,market,day):
                if day not in ('2026-10-28','2026-10-29'):return None
                stamp=lambda t:datetime.fromisoformat(day+'T'+t+'+00:00')
                return stamp('01:30:00'),stamp('07:00:00'),(stamp('03:30:00'),stamp('05:00:00'))
        calendar=ResearchClock(Sessions())
        stamp=lambda t:datetime.fromisoformat(t+'+00:00')
        before=calendar.context(stamp('2026-10-29T01:00:00'))
        self.assertEqual(before['trade_date'],'2026-10-28');self.assertFalse(before['active'])
        lunch=calendar.context(stamp('2026-10-29T04:00:00'))
        self.assertFalse(lunch['active']);self.assertEqual(lunch['expected_at'],'2026-10-29T03:30:00+00:00')
        self.assertTrue(calendar.context(stamp('2026-10-29T05:30:00'))['active'])
        closed=calendar.context(stamp('2026-10-31T05:30:00'))
        self.assertFalse(closed['active']);self.assertEqual(closed['trade_date'],'2026-10-29')
        self.assertEqual(closed['expected_at'],'2026-10-29T07:05:00+00:00')

    def test_overlap_and_sampling_skew_do_not_create_transition_evidence(self):
        self.source.rows[1]['payload']['data']['pool'].append(raw_stock());self.source.rows[1]['payload']['data']['tc']=2
        data=self.snapshot();self.assertFalse(data['coherent']);self.assertIsNone(data['summary']['snapshot_open_ratio_pct'])
        self.research.collect();self.assertEqual(self.research.report()['events'],[])
        envelopes=fixtures(self.clock);envelopes[1]['received_at']=(self.clock()-timedelta(minutes=2)).isoformat()
        data=build_snapshot(envelopes,Calendar().context(self.clock()),self.clock());self.assertFalse(data['coherent'])

    def test_snapshot_transitions_and_first_observation_are_not_backfilled(self):
        self.research.collect();first=self.research.report();stock=first['pools']['up'][0]
        self.assertEqual(stock['first_observed_at'],self.clock().isoformat())
        self.assertNotIn(stock['first_seal'],stock['first_observed_at'])
        self.assertTrue(all(e['kind']=='baseline' for e in first['events']))
        self.advance();moved=self.source.rows[0]['payload']['data']['pool'].pop(0)
        self.source.rows[0]['payload']['data']['tc']=1
        self.source.rows[1]['payload']['data']['pool'].append(moved);self.source.rows[1]['payload']['data']['tc']=2
        self.research.collect();self.assertEqual(self.research.report()['events'][0]['kind'],'observed_open')
        self.advance();self.source.rows[1]['payload']['data']['pool'].pop();self.source.rows[1]['payload']['data']['tc']=1
        self.source.rows[0]['payload']['data']['pool'].append(moved);self.source.rows[0]['payload']['data']['tc']=2
        self.research.collect();event=self.research.report()['events'][0]
        self.assertEqual(event['kind'],'observed_reseal');self.assertIsNone(event['exact_event_time'])
        with self.research.db() as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM observation_events')

    def test_empty_baseline_then_new_stock_is_first_observed(self):
        for envelope in self.source.rows[:2]:envelope['payload']['data'].update(pool=[],tc=0)
        self.research.collect();self.advance()
        self.source.rows[0]['payload']['data'].update(pool=[raw_stock()],tc=1)
        self.research.collect();self.assertEqual(self.research.report()['events'][0]['kind'],'first_observed')

    def test_failure_keeps_previous_snapshot_and_reports_stale_then_recovers(self):
        self.research.collect();original=self.research.report();self.advance();saved=self.source.rows
        self.source.rows=[dict(key=e['key'],received_at=self.clock().isoformat(),error='offline') for e in saved]
        self.research.collect();result=self.research.report()
        self.assertEqual(result['status'],'stale');self.assertEqual(result['observed_at'],original['observed_at'])
        self.assertEqual(result['summary']['sealed_count'],2)
        self.advance();self.source.rows=saved;self.research.collect();self.assertEqual(self.research.report()['status'],'current')

    def test_historical_selection_and_missing_day_are_explicit(self):
        self.research.collect();self.assertEqual(self.research.report('2026-10-28')['status'],'unavailable')
        self.assertIn('2026-10-29',self.research.report()['available_dates'])
        self.clock.now+=timedelta(days=1)
        class NextDay:
            def context(self,now):return {**Calendar().context(now),'trade_date':'2026-10-30'}
        self.research.calendar=NextDay()
        self.assertEqual(self.research.report()['status'],'stale')
        self.assertEqual(self.research.report('2026-10-29')['status'],'historical')

    def test_progression_is_intraday_observation_not_final_promotion(self):
        data=self.snapshot();first=data['progression'][0]
        self.assertEqual(first['from_boards'],1);self.assertEqual(first['candidates'],2)
        self.assertEqual(first['currently_advanced'],1);self.assertEqual(first['rate_pct'],50)

    def test_read_only_api_and_date_validation(self):
        app=FastAPI();app.include_router(research_router(self.research));client=TestClient(app)
        response=client.get('/api/cn/research');self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['status'],'unavailable');self.assertEqual(self.source.calls,0)
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertEqual(client.post('/api/cn/research',json={'buy':True}).status_code,405)
        for date in ['../../etc/passwd','2026-02-30','today']:
            self.assertEqual(client.get('/api/cn/research',params={'date':date}).status_code,400)

    def test_calendar_failure_is_unknown_and_no_network_request(self):
        calendar=ResearchClock(type('Offline',(),{'session':lambda *args:None})())
        self.research.calendar=calendar;self.research.collect()
        self.assertEqual(self.source.calls,0);self.assertEqual(self.research.report()['status'],'unavailable')

    def test_poll_is_throttled_and_report_does_not_poll(self):
        self.research.collect();self.research.collect();self.research.report()
        self.assertEqual(self.source.calls,1)
        self.advance();self.research.collect();self.assertEqual(self.source.calls,2)

    def test_legacy_cn_endpoints_are_retired_and_runtime_no_cn_strategy(self):
        tree=ast.parse(Path('api.py').read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='api_signals_cn')
        fn.decorator_list=[]
        from fastapi import HTTPException
        scope={'HTTPException':HTTPException};exec(compile(ast.Module(body=[fn],type_ignores=[]),'api.py','exec'),scope)
        with self.assertRaises(HTTPException) as result:scope['api_signals_cn']()
        self.assertEqual(result.exception.status_code,410)
        pipeline=Path('scripts/vps_pipeline.sh').read_text();self.assertNotIn('run_cn.py',pipeline)
        notifier=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='notify_telegram')
        self.assertNotIn('signals_cn.json',ast.unparse(notifier))


if __name__=='__main__':unittest.main()

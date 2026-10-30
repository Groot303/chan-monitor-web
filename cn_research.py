"""独立A股连板研究快照与观察日志，不调用任何买卖点检测器或交易接口。"""
import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cn_limitup_source import PublicLimitupSource, ResearchClock, build_snapshot, attribution_summary, valid_attribution


def dump(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'))


class CNResearch:
    def __init__(self,path,source=None,calendar=None,clock=None):
        self.path=Path(path);self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.source=source or PublicLimitupSource(self.clock);self.calendar=calendar or ResearchClock()
        self.lock=threading.Lock()

    @contextmanager
    def db(self):
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        db=sqlite3.connect(self.path,timeout=10);self.path.chmod(0o600);db.row_factory=sqlite3.Row
        try:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY,date TEXT,observed_at TEXT,payload TEXT);
            CREATE TABLE IF NOT EXISTS raw_sources(id INTEGER PRIMARY KEY,source TEXT,date TEXT,received_at TEXT,digest TEXT,payload TEXT,UNIQUE(source,date,digest));
            CREATE TABLE IF NOT EXISTS daily(date TEXT PRIMARY KEY,observed_at TEXT,payload TEXT);
            CREATE TABLE IF NOT EXISTS observations(date TEXT,code TEXT,state TEXT,first_seen TEXT,last_seen TEXT,payload TEXT,PRIMARY KEY(date,code));
            CREATE TABLE IF NOT EXISTS observation_events(id INTEGER PRIMARY KEY,date TEXT,code TEXT,observed_at TEXT,kind TEXT,payload TEXT);
            CREATE TABLE IF NOT EXISTS runtime(id INTEGER PRIMARY KEY CHECK(id=1),last_attempt TEXT,error TEXT);
            CREATE TABLE IF NOT EXISTS theme_memory(date TEXT,code TEXT,note TEXT,PRIMARY KEY(date,code));
            CREATE TRIGGER IF NOT EXISTS cn_events_no_update BEFORE UPDATE ON observation_events BEGIN SELECT RAISE(ABORT,'immutable observations'); END;
            CREATE TRIGGER IF NOT EXISTS cn_events_no_delete BEFORE DELETE ON observation_events BEGIN SELECT RAISE(ABORT,'immutable observations'); END;
            CREATE INDEX IF NOT EXISTS cn_snapshots_date ON snapshots(date,id);
            CREATE INDEX IF NOT EXISTS cn_events_date ON observation_events(date,id);
            ''')
            db.execute('BEGIN IMMEDIATE');yield db;db.commit()
        except Exception:db.rollback();raise
        finally:db.close()

    def collect(self):
        if not self.lock.acquire(blocking=False):return
        try:
            now=self.clock();context=self.calendar.context(now)
            with self.db() as db:
                previous=db.execute('SELECT * FROM snapshots ORDER BY id DESC LIMIT 1').fetchone()
                runtime=db.execute('SELECT * FROM runtime WHERE id=1').fetchone()
                if runtime and (now-datetime.fromisoformat(runtime['last_attempt'])).total_seconds()<45:return
                if (previous and not context['active'] and context.get('trade_date')==previous['date']
                        and json.loads(previous['payload']).get('attribution_contract')==2
                        and datetime.fromisoformat(previous['observed_at'])>=datetime.fromisoformat(context['expected_at'])-timedelta(minutes=3)):
                    return
                prior=self.attributions(db,context.get('trade_date'),now)
            if context.get('error'):
                with self.db() as db:db.execute('INSERT OR REPLACE INTO runtime VALUES(1,?,?)',(now.isoformat(),context['error']))
                return
            try:
                envelopes=self.source.fetch(context['trade_date'])
                observed=self.clock();snapshot=build_snapshot(envelopes,context,observed,prior)
                with self.db() as db:
                    for envelope in envelopes:
                        if 'payload' not in envelope:continue
                        raw=dump(envelope['payload']);digest=hashlib.sha256(raw.encode()).hexdigest()
                        db.execute('INSERT OR IGNORE INTO raw_sources(source,date,received_at,digest,payload) VALUES(?,?,?,?,?)',
                                   (envelope['key'],context['trade_date'],envelope['received_at'],digest,dump(envelope)))
                    # 来源请求失败不会覆盖最近成功快照；错误状态仍单独持久化并对外展示。
                    if not snapshot['pools']:
                        db.execute('INSERT OR REPLACE INTO runtime VALUES(1,?,?)',
                            (observed.isoformat(),'行情来源暂不可用，未用空列表覆盖历史快照'))
                        return
                    self.remember_attributions(db,snapshot)
                    self.observe(db,snapshot)
                    payload=dump(snapshot)
                    db.execute('INSERT INTO snapshots(date,observed_at,payload) VALUES(?,?,?)',(snapshot['trade_date'],snapshot['observed_at'],payload))
                    db.execute('INSERT OR REPLACE INTO daily VALUES(?,?,?)',(snapshot['trade_date'],snapshot['observed_at'],payload))
                    db.execute('INSERT OR REPLACE INTO runtime VALUES(1,?,NULL)',(observed.isoformat(),))
                    # 原始响应和分钟快照保留7个自然日；每日最后快照保留60个自然日。
                    db.execute('DELETE FROM snapshots WHERE observed_at<?',((observed-timedelta(days=7)).isoformat(),))
                    db.execute('DELETE FROM raw_sources WHERE received_at<?',((observed-timedelta(days=7)).isoformat(),))
                    db.execute('DELETE FROM daily WHERE date<?',((observed-timedelta(days=60)).date().isoformat(),))
                    db.execute('DELETE FROM theme_memory WHERE date<?',((observed-timedelta(days=7)).date().isoformat(),))
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning('CN research collection unavailable: %s',type(exc).__name__)
                with self.db() as db:db.execute('INSERT OR REPLACE INTO runtime VALUES(1,?,?)',
                    (self.clock().isoformat(),'本轮采集未完成：'+str(exc)[:120]))
        finally:self.lock.release()

    def remember_attributions(self,db,snapshot):
        day=snapshot['trade_date'];observed=datetime.fromisoformat(snapshot['observed_at'])
        for rows in snapshot['pools'].values():
            for stock in rows:
                note={key:stock.get(key) for key in ('name','theme','concepts','source_event_time')}
                # 旧快照真实接收时间可作归因证据时间，不冒充来源事件或首次发现时间。
                note['attribution_observed_at']=stock.get('attribution_observed_at') or snapshot['observed_at']
                if valid_attribution(note,day,observed):
                    db.execute('INSERT INTO theme_memory VALUES(?,?,?) ON CONFLICT(date,code) DO UPDATE SET note=excluded.note',
                        (day,stock['code'],dump(note)))

    def attributions(self,db,day,now):
        if not day:return {}
        if not db.execute('SELECT 1 FROM theme_memory WHERE date=? LIMIT 1',(day,)).fetchone():
            # 升级首次使用时，只从已保存的同日真实快照恢复证据；不查询今日来源补造历史归因。
            for row in db.execute('SELECT payload FROM snapshots WHERE date=? AND observed_at<=? ORDER BY id',(day,now.isoformat())):
                self.remember_attributions(db,json.loads(row['payload']))
        return {row['code']:json.loads(row['note']) for row in db.execute('SELECT code,note FROM theme_memory WHERE date=?',(day,))}

    def observe(self,db,snapshot):
        if not snapshot['coherent']:return
        day,observed=snapshot['trade_date'],snapshot['observed_at']
        baseline=not db.execute('SELECT 1 FROM daily WHERE date=?',(day,)).fetchone()
        old={r['code']:dict(r) for r in db.execute('SELECT * FROM observations WHERE date=?',(day,))}
        current={s['code']:s for key in ('up','broken') for s in snapshot['pools'].get(key,[])}
        for code in sorted(set(old)|set(current)):
            stock=current.get(code);prior=old.get(code)
            state=stock['state'] if stock else 'out_of_pool'
            # 初次观测本身不是新封板事件；之后只记录两次采样间观察到的变化。
            kind=('baseline' if baseline else 'first_observed') if prior is None else (
                'observed_reseal' if prior['state']=='broken' and state=='sealed' else
                'observed_open' if prior['state']=='sealed' and state=='broken' else 'state_changed')
            payload=stock or json.loads(prior['payload'])
            if prior is None or prior['state']!=state:
                db.execute('INSERT INTO observation_events(date,code,observed_at,kind,payload) VALUES(?,?,?,?,?)',
                    (day,code,observed,kind,dump(dict(name=payload['name'],from_state=prior['state'] if prior else None,
                        to_state=state,source_first_seal=payload.get('first_seal'),source_last_seal=payload.get('last_seal'),
                        exact_event_time=None,timing_evidence='observed_snapshot_transition'))))
            db.execute('INSERT OR REPLACE INTO observations VALUES(?,?,?,?,?,?)',
                (day,code,state,prior['first_seen'] if prior else observed,observed,dump(payload)))

    def report(self,date=None):
        now=self.clock();context=self.calendar.context(now)
        with self.db() as db:
            record=db.execute('SELECT * FROM daily WHERE date=?',(date,)).fetchone() if date else db.execute('SELECT * FROM snapshots ORDER BY id DESC LIMIT 1').fetchone()
            runtime=db.execute('SELECT * FROM runtime WHERE id=1').fetchone()
            days=[r['date'] for r in db.execute('SELECT date FROM daily ORDER BY date DESC LIMIT 30')]
            if not record:
                return dict(schema='cn-limitup-research-v1',market='cn',mode='research_only',status='unavailable',
                    trade_date=date or context.get('trade_date'),observed_at=None,server_time=now.isoformat(),
                    error='所选交易日暂无已采集快照' if date else (context.get('error') or (runtime['error'] if runtime else None) or '等待首次连板研究数据采集'),sources={},pools={},themes=[],progression=[],events=[],available_dates=days)
            result=json.loads(record['payload']);historical=bool(date and date!=context.get('trade_date'))
            # 旧数据重算覆盖率和“未知”标记，不改变原始快照或事后补入题材。
            result['themes'],coverage=attribution_summary(result['pools'],result['sources'],result['coherent'])
            result['summary'].update(coverage)
            age=(now-datetime.fromisoformat(result['observed_at'])).total_seconds()
            expected=context.get('expected_at')
            stale=(not historical and (not context.get('trade_date') or result['trade_date']!=context['trade_date'] or not expected
                or (datetime.fromisoformat(expected)-datetime.fromisoformat(result['observed_at'])).total_seconds()>180))
            partial=(not result['coherent'] or any(result['sources'].get(k,{}).get('status')!='ok' for k in ('up','broken','previous','down'))
                     or result['summary']['attributed_sealed']<result['summary']['attribution_total']
                     or not result['summary']['broken_attribution_complete'])
            result.update(status='historical' if historical else 'stale' if stale else 'partial' if partial else 'current' if context['active'] else 'closed',
                server_time=now.isoformat(),age_seconds=max(age,0),current_market_context=context,available_dates=days,
                last_attempt=runtime['last_attempt'] if runtime else None,collection_error=runtime['error'] if runtime and not historical else None)
            if result['collection_error'] and not historical:result['status']='stale'
            result['events']=[dict(id=r['id'],code=r['code'],observed_at=r['observed_at'],kind=r['kind'],**json.loads(r['payload']))
                for r in db.execute('SELECT * FROM observation_events WHERE date=? ORDER BY id DESC LIMIT 80',(result['trade_date'],))]
            for rows in result['pools'].values():
                for stock in rows:
                    seen=db.execute('SELECT first_seen FROM observations WHERE date=? AND code=?',(result['trade_date'],stock['code'])).fetchone()
                    stock['first_observed_at']=seen['first_seen'] if seen else None
            return result

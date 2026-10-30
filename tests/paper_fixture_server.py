"""Local browser-test fixture only. Never included by api.py."""
import json
import tempfile
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from paper_routes import router_for
from paper_trading import PaperStore, timestamp
from tests.test_paper_trading import Clock, Market
from tests.test_automatic_strategy import Source, signal
from automatic_strategy import AutomaticStrategy, StrategyGroup, RULES_V2
from strategy_routes import strategy_router
from cn_research import CNResearch
from cn_routes import research_router
import tests.test_cn_research as cn_fixtures
from datetime import timedelta

app=FastAPI()
clock=Clock()
market=Market(clock)
site=Path(__file__).resolve().parents[1]/'site'
tmp=tempfile.TemporaryDirectory()
store=PaperStore(Path(tmp.name)/'ledger.sqlite',market,clock)
app.include_router(router_for(store))
source=Source();source.publish(symbol='NVDA')
engine=AutomaticStrategy(store,source);engine.tick()
engine_v2=AutomaticStrategy(store,source,rules=RULES_V2);engine_v2.tick()
group=StrategyGroup(engine,engine_v2)
app.include_router(strategy_router(engine,variants={'v1':engine,'v2':engine_v2}))
cn_clock=cn_fixtures.Clock();cn_clock.now-=timedelta(days=1)
class CNCalendar:
    def context(self,now):return {**cn_fixtures.Calendar().context(now),'trade_date':now.date().isoformat()}
cn_source=cn_fixtures.Source(cn_clock)
for item in cn_source.rows[:4]:item['payload']['data']['qdate']=20261028
cn_research=CNResearch(Path(tmp.name)/'research.sqlite',cn_source,CNCalendar(),cn_clock);cn_research.collect()
cn_clock.now+=timedelta(days=1);cn_source.rows=cn_fixtures.fixtures(cn_clock);cn_research.collect()
app.include_router(research_router(cn_research))

@app.post('/test/cn-open')
def cn_open():
    cn_clock.now+=timedelta(minutes=1)
    moved=cn_source.rows[0]['payload']['data']['pool'].pop(0);cn_source.rows[0]['payload']['data']['tc']=1
    cn_source.rows[1]['payload']['data']['pool'].append(moved);cn_source.rows[1]['payload']['data']['tc']=2
    cn_research.collect();return {'ok':True}

@app.post('/test/cn-reseal')
def cn_reseal():
    cn_clock.now+=timedelta(minutes=1)
    moved=cn_source.rows[1]['payload']['data']['pool'].pop();cn_source.rows[1]['payload']['data']['tc']=1
    cn_source.rows[0]['payload']['data']['pool'].append(moved);cn_source.rows[0]['payload']['data']['tc']=2
    cn_research.collect();return {'ok':True}

@app.post('/test/cn-offline')
def cn_offline():
    cn_clock.now+=timedelta(minutes=1)
    cn_source.rows=[dict(key=e['key'],received_at=cn_clock().isoformat(),error='test offline') for e in cn_source.rows]
    cn_research.collect();return {'ok':True}

@app.post('/test/cn-attribution-gap')
def cn_attribution_gap(known:bool=True):
    cn_clock.now+=timedelta(minutes=1)
    rows=cn_source.rows[1]['payload']['data']
    sample=cn_fixtures.raw_stock('000777','待核验样本')
    rows['pool']=([s for s in rows['pool'] if s['c']!='000777'] if known else [])+[sample]
    rows['tc']=len(rows['pool'])
    cn_research.collect();return {'ok':True}

@app.post('/test/signal')
def new_signal():
    source.publish([signal()],symbol='NVDA');group.tick()
    return {'orders':len(engine_v2.report()['account']['orders'])}

@app.post('/test/advance')
def advance():
    market.bar('NVDA','2026-10-27T14:35:00Z',100)
    clock.now=timestamp('2026-10-27T14:41:00Z')
    group.tick()
    return {'ok':True}

@app.post('/test/stop-advance')
def stop_advance():
    market.bar('NVDA','2026-10-27T14:45:00Z',85)
    clock.now=timestamp('2026-10-27T14:51:00Z')
    store.sync_all()
    with store.db() as db:
        a=engine_v2.setup(db)
        count=db.execute("SELECT COUNT(*) FROM protective_stops WHERE status='filled' AND account=?",(a['id'],)).fetchone()[0]
    return {'automatic_stops_filled':count}

@app.get('/api/signals')
def signals(): return json.loads((site/'data/signals.json').read_text())

@app.get('/api/signals_cn')
def signals_cn(): return json.loads((site/'data/signals_cn.json').read_text())

@app.get('/api/macro')
def macro(): return {'generated':'2026-10-27','indicators':{},'failures':{}}

app.mount('/api/charts',StaticFiles(directory=site/'data/charts'))
app.mount('/api/charts_cn',StaticFiles(directory=site/'data/charts_cn'))
app.mount('/',StaticFiles(directory=site,html=True))

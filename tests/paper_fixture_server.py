"""Local browser-test fixture only. Never included by api.py."""
import json
import tempfile
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from paper_routes import router_for
from paper_trading import PaperStore, timestamp
from tests.test_paper_trading import Clock, Market

app=FastAPI()
clock=Clock()
market=Market(clock)
site=Path(__file__).resolve().parents[1]/'site'
tmp=tempfile.TemporaryDirectory()
store=PaperStore(Path(tmp.name)/'ledger.sqlite',market,clock)
app.include_router(router_for(store))

@app.post('/test/advance')
def advance():
    market.bar('NVDA','2026-10-27T14:35:00Z',100)
    clock.now=timestamp('2026-10-27T14:41:00Z')
    return {'ok':True}

@app.post('/test/stop-advance')
def stop_advance():
    market.bar('NVDA','2026-10-27T14:45:00Z',85)
    clock.now=timestamp('2026-10-27T14:51:00Z')
    store.sync_all()
    with store.db() as db:
        count=db.execute("SELECT COUNT(*) FROM protective_stops WHERE status='filled'").fetchone()[0]
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

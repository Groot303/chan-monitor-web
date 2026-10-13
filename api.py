"""chan-monitor-web API backend: FastAPI + APScheduler.
Runs the data pipeline every 15 min in-process, serves signals/charts via REST.
Deploy: systemd service (see api.service), data in /opt/chan-monitor/api_data/.
"""
import json
import os
import subprocess
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("chan-api")

BASE = Path("/opt/chan-monitor")
REPO = BASE / "repo"
DATA_DIR = BASE / "api_data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="chan-monitor-web API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- job status ----
job_status = {
    "last_run": None,
    "last_result": None,
    "last_duration_s": None,
    "running": False,
    "run_count": 0,
}


def run_pipeline():
    """Run the data pipeline synchronously. Called by scheduler and manual trigger."""
    if job_status["running"]:
        log.warning("pipeline already running, skip")
        return {"status": "already_running"}
    job_status["running"] = True
    t0 = datetime.now(timezone.utc)
    job_status["last_run"] = t0.isoformat()
    log.info("pipeline start")
    try:
        env = {**os.environ, "API_MODE": "1", "API_DATA_DIR": str(DATA_DIR)}
        r = subprocess.run(
            [str(BASE / "run_pipeline.sh")],
            capture_output=True, text=True, timeout=900,
            cwd=str(REPO), env=env,
        )
        dur = (datetime.now(timezone.utc) - t0).total_seconds()
        job_status["last_duration_s"] = round(dur, 1)
        job_status["run_count"] += 1
        if r.returncode == 0:
            job_status["last_result"] = "ok"
            log.info(f"pipeline ok in {dur:.1f}s")
        else:
            err = (r.stderr or "")[-800:]
            job_status["last_result"] = f"failed(rc={r.returncode}): {err}"
            log.error(f"pipeline failed: {err}")
    except subprocess.TimeoutExpired:
        job_status["last_result"] = "timeout(900s)"
        log.error("pipeline timeout")
    except Exception as e:
        job_status["last_result"] = f"error: {str(e)[:500]}"
        log.exception("pipeline error")
    finally:
        job_status["running"] = False
    return {"status": job_status["last_result"]}


# ---- scheduler ----
scheduler = None

@app.on_event("startup")
async def on_startup():
    global scheduler
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scheduler = AsyncIOScheduler(timezone="UTC")
        scheduler.add_job(run_pipeline, "interval", minutes=15, id="pipeline",
                          max_instances=1, coalesce=True)
        scheduler.start()
        log.info("APScheduler started (every 15 min)")
        # Run once on startup (in background thread to not block)
        import threading
        threading.Thread(target=run_pipeline, daemon=True).start()
    except ImportError:
        log.warning("apscheduler not installed, scheduler disabled")

@app.on_event("shutdown")
async def on_shutdown():
    if scheduler:
        scheduler.shutdown()


# ---- API ----
@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/jobs")
def jobs():
    d = dict(job_status)
    if scheduler:
        nxt = scheduler.get_job("pipeline").next_run_time
        d["next_run"] = nxt.isoformat() if nxt else None
    return d


@app.post("/api/jobs/run")
def trigger():
    import threading
    if job_status["running"]:
        return {"status": "already_running"}
    threading.Thread(target=run_pipeline, daemon=True).start()
    return {"status": "started"}


def _read_json(name):
    # build_data.py outputs to api_data/data/<name>
    p = DATA_DIR / "data" / name
    if not p.exists():
        # fallback: top level (legacy)
        p = DATA_DIR / name
    if not p.exists():
        raise HTTPException(status_code=503, detail=f"{name} not ready yet")
    try:
        return JSONResponse(content=json.loads(p.read_text(encoding="utf-8")))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])


@app.get("/api/signals")
def api_signals():
    return _read_json("signals.json")


@app.get("/api/signals_cn")
def api_signals_cn():
    return _read_json("signals_cn.json")


# static: images and interactive chart data
for _sub in ("img", "img_cn", "charts", "charts_cn"):
    _d = DATA_DIR / _sub
    _d.mkdir(parents=True, exist_ok=True)
    app.mount(f"/api/{_sub}", StaticFiles(directory=str(_d)), name=_sub)

"""chan-monitor-web API backend: FastAPI + APScheduler.
Runs the data pipeline every 15 min in-process, serves signals/charts via REST.
Deploy: systemd service (see api.service), data in /opt/chan-monitor/api_data/.
"""
import json
import os
import subprocess
import secrets
import sys
import logging
from scripts.notification_state import notification_state_path
from cn_symbols import CN_SYMS
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("chan-api")

BASE = Path("/opt/chan-monitor")
REPO = BASE / "repo"
DATA_DIR = BASE / "api_data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_dotenv():
    """Load /opt/chan-monitor/.env into os.environ (setdefault: real env wins)."""
    p = BASE / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip("'\"")
        if k and k not in os.environ:
            os.environ[k] = v


load_dotenv()

app = FastAPI(title="chan-monitor-web API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Cache control: StaticFiles emits ETag/Last-Modified but no Cache-Control,
# so WebKit/iOS Safari falls back to heuristic caching and can serve stale
# index.html / app.js indefinitely. Force revalidation on the entry document,
# assets and data files (cheap 304 via ETag when unchanged).
@app.middleware("http")
async def _no_cache_static(request: Request, call_next):
    resp = await call_next(request)
    p = request.url.path
    if p == "/" or p.endswith((".html", ".js", ".css", ".json", ".png", ".svg", ".ico")):
        resp.headers["Cache-Control"] = "no-cache"
    return resp

# ---- job status ----
job_status = {
    "last_run": None,
    "last_result": None,
    "last_duration_s": None,
    "running": False,
    "run_count": 0,
}

ibkr_status = {
    "last_run": None,
    "last_result": None,
    "running": False,
    "symbols": [],
}


def notify_telegram():
    """Send Telegram notifications for new signals (US + CN) after a pipeline run.

    Runs scripts/notify_telegram.py twice (US signals.json, CN signals_cn.json),
    sharing a runtime state file under api_data/state for dedup. Token/chat come from env (VPS .env).
    Also delivers the one-off announcement file (state/announcement.txt) if
    present. Never raises; failures are logged only.
    """
    script = REPO / "scripts" / "notify_telegram.py"
    if not script.exists():
        return
    state_file = notification_state_path(REPO, DATA_DIR)
    announce_file = REPO / "state" / "announcement.txt"
    for name in ("signals.json", "signals_cn.json"):
        try:
            env = {
                **os.environ,
                "SIGNALS_FILE": str(DATA_DIR / "data" / name),
                "STATE_FILE": str(state_file),
                "ANNOUNCE_FILE": str(announce_file),
            }
            r = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True, text=True, timeout=120,
                cwd=str(REPO), env=env,
            )
            out = (r.stdout or "").strip()
            if out:
                log.info(f"notify[{name}]: {out[:300]}")
        except Exception as e:
            log.warning(f"notify[{name}] failed: {e}")


def run_pipeline():
    """Run the data pipeline synchronously. Called by scheduler and manual trigger."""
    git_pull_ff()      # keep code fresh for self-update; ff-only, never diverges
    check_self_update()
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
            notify_telegram()
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


API_PY = Path(__file__).resolve()
API_PY_MTIME = API_PY.stat().st_mtime if API_PY.exists() else None


def check_self_update():
    """Restart via systemd if api.py changed on disk.

    CI/CD (GitHub Actions -> deploy.sh) keeps the repo fresh; this backend
    is a long-running process, so it must reload itself to pick up api.py
    changes. py_compile gate prevents restart-loops on broken pushes.
    """
    global API_PY_MTIME
    try:
        mtime = API_PY.stat().st_mtime
    except OSError:
        return
    if API_PY_MTIME is None:
        API_PY_MTIME = mtime
        return
    if mtime == API_PY_MTIME:
        return
    log.warning("api.py changed on disk, verifying before restart")
    r = subprocess.run([sys.executable, "-m", "py_compile", str(API_PY)],
                       capture_output=True, timeout=30)
    if r.returncode == 0:
        log.warning("new api.py compiles, exiting for systemd restart")
        os._exit(42)
    log.error("new api.py does NOT compile, staying on current version")
    API_PY_MTIME = mtime  # don't spam the log


def fetch_ibkr_positions():
    """Pull IBKR open positions via Flex Web Service (every 6h).

    Writes api_data/data/positions_ibkr.json (served at /api/positions) and
    a symbols-only copy to repo site/data/positions_ibkr.json (run2.py SYMS
    merge + web badge; public-safe).
    """
    if ibkr_status["running"]:
        log.warning("ibkr fetch already running, skip")
        return
    ibkr_status["running"] = True
    t0 = datetime.now(timezone.utc)
    ibkr_status["last_run"] = t0.isoformat()
    log.info("ibkr fetch start")
    try:
        out_path = DATA_DIR / "data" / "positions_ibkr.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "POSITIONS_OUT": str(out_path)}
        r = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "fetch_ibkr_positions.py")],
            capture_output=True, text=True, timeout=600,
            cwd=str(REPO), env=env,
        )
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout or "unknown error")[-500:])
        if out_path.exists():
            d = json.loads(out_path.read_text(encoding="utf-8"))
            ibkr_status["symbols"] = d.get("symbols", [])
            # site/data gets symbols ONLY (public-safe for Pages backup);
            # full qty/cost/P&L stays in api_data (token-protected /api/positions).
            dst = REPO / "site" / "data" / "positions_ibkr.json"
            dst.parent.mkdir(parents=True, exist_ok=True)
            public = {"generated": d.get("generated"), "symbols": d.get("symbols", [])}
            dst.write_text(json.dumps(public, indent=1), encoding="utf-8")
        ibkr_status["last_result"] = "ok"
        log.info(f"ibkr fetch ok: {ibkr_status['symbols']}")
    except Exception as e:
        ibkr_status["last_result"] = f"error: {str(e)[:300]}"
        log.error(f"ibkr fetch failed: {e}")
    finally:
        ibkr_status["running"] = False


GIT_ENV = {**os.environ,
           "GIT_SSH_COMMAND": "ssh -i /opt/chan-monitor/deploy_key -o StrictHostKeyChecking=accept-new"}


def _git(*args, timeout=120):
    return subprocess.run(["git", *args], cwd=str(REPO),
                          capture_output=True, text=True, timeout=timeout, env=GIT_ENV)


def git_pull_ff():
    """Fast-forward pull only. NEVER rebases/resets/force-pushes, so it cannot
    cause divergence (the interrupted-rebase + detached HEAD incident must not
    repeat). Fails safe with a log line if the tree diverged."""
    r = _git("status", "--porcelain", timeout=30)
    dirty = [l for l in r.stdout.splitlines() if not l.startswith("??")]
    if dirty:
        log.warning(f"working tree dirty, skipping pull: {dirty[:3]}")
        return False
    r = _git("pull", "--ff-only", "-q", timeout=120)
    if r.returncode != 0:
        log.error(f"git pull --ff-only failed (diverged?): {(r.stderr or '')[:200]}")
        return False
    log.info("git pull --ff-only ok")
    return True


# ---- scheduler ----
scheduler = None

@app.on_event("startup")
async def on_startup():
    global scheduler
    log.info("A-share universe configured: %s", ", ".join(name for name, _ in CN_SYMS))
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scheduler = AsyncIOScheduler(timezone="UTC")
        scheduler.add_job(run_pipeline, "interval", minutes=15, id="pipeline",
                          max_instances=1, coalesce=True)
        scheduler.add_job(fetch_ibkr_positions, "interval", hours=6, id="ibkr",
                          max_instances=1, coalesce=True,
                          next_run_time=datetime.now(timezone.utc) + timedelta(minutes=2))
        scheduler.start()
        log.info("APScheduler started (pipeline 15m, ibkr 6h); deploys via CI/CD")
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
    d["ibkr"] = dict(ibkr_status)
    if scheduler:
        for jid, key in (("pipeline", "next_run"), ("ibkr", "ibkr_next_run")):
            job = scheduler.get_job(jid)
            nxt = job.next_run_time if job else None
            d[key] = nxt.isoformat() if nxt else None
    return d


def _get_api_token():
    """Read API_TOKEN live from .env (os.environ fallback).

    Read from disk on every check (not just at startup) so rotating the
    token needs no restart, and the scheduler/self-update paths stay untouched.
    """
    try:
        for line in (BASE / ".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("API_TOKEN"):
                k, _, v = line.partition("=")
                if k.strip() == "API_TOKEN" and v.strip():
                    return v.strip().strip("'\"")
    except OSError:
        pass
    return os.environ.get("API_TOKEN", "")


def _require_token(request: Request):
    """Guard write/sensitive endpoints. Token lives in /opt/chan-monitor/.env
    as API_TOKEN (never in the repo)."""
    token = _get_api_token()
    if not token:
        raise HTTPException(status_code=503, detail="API_TOKEN not configured")
    got = request.headers.get("x-api-token", "")
    if not secrets.compare_digest(got, token):
        raise HTTPException(status_code=401, detail="bad token")


@app.post("/api/jobs/run")
def trigger(request: Request):
    _require_token(request)
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


@app.get("/api/macro")
def api_macro():
    # Macro snapshot written by the pipeline to api_data/data/macro.json.
    # (The frontend used to fetch static data/macro.json = site/data/macro.json,
    # which API_MODE never writes -> permanent 404. See 2026-10-15 fix.)
    return _read_json("macro.json")


@app.get("/api/positions")
def api_positions(request: Request):
    # 用户屏蔽持仓页：恢复敏感接口鉴权，后台同步和原始数据继续保留。
    _require_token(request)
    p = DATA_DIR / "data" / "positions_ibkr.json"
    if not p.exists():
        raise HTTPException(status_code=503, detail="positions_ibkr.json not ready yet")
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])
    out = dict(d)
    out.pop("accounts", None)
    out["positions"] = [{k: v for k, v in pos.items() if k != "account"}
                        for pos in d.get("positions", [])]
    return JSONResponse(content=out)


@app.get("/data/positions_ibkr.json")
@app.get("/api/holdings")
def api_holdings(request: Request):
    """持仓标的及旧静态入口同样需要鉴权，不再向匿名访客展示。"""
    _require_token(request)
    p = DATA_DIR / "data" / "positions_ibkr.json"
    if not p.exists():
        raise HTTPException(status_code=503, detail="positions_ibkr.json not ready yet")
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return JSONResponse(content={"symbols": d.get("symbols", []),
                                     "generated": d.get("generated")})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])


# static: images and interactive chart data
# Note: build_data.py writes charts to api_data/data/charts/ (not api_data/charts/)
for _sub, _dirname in (("img", "img"), ("img_cn", "img_cn"),
                       ("charts", "data/charts"), ("charts_cn", "data/charts_cn")):
    _d = DATA_DIR / _dirname
    _d.mkdir(parents=True, exist_ok=True)
    app.mount(f"/api/{_sub}", StaticFiles(directory=str(_d)), name=_sub)


# full-stack: serve the web frontend from the same origin (no CORS / tunnel).
# Mounted last so explicit /api/* routes take precedence.
_site_dir = REPO / "site"
if _site_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_site_dir), html=True), name="site")

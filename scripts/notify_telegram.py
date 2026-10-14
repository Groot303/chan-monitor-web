#!/usr/bin/env python3
"""Telegram notifier for new high-score recent signals. stdlib only.
Never fails the pipeline; never prints the token.

Wired into api.py run_pipeline (after a successful pipeline run):
  SIGNALS_FILE = <api_data>/data/signals.json (US) or signals_cn.json (CN)
  STATE_FILE   = <repo>/state/notified.json (dedup across runs)
  ANNOUNCE_FILE= <repo>/state/announcement.txt (one-off message, sent once
                 per content hash, then skipped on later runs)

Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (VPS .env), SCORE_MIN (default 4.0).
"""
import hashlib, json, os, sys, urllib.request, urllib.parse

SCORE_MIN = float(os.environ.get("SCORE_MIN", "4.0"))
SIGNALS = os.environ.get("SIGNALS_FILE", "site/data/signals.json")
STATE = os.environ.get("STATE_FILE", "state/notified.json")
ANNOUNCE = os.environ.get("ANNOUNCE_FILE", "")
URL = "https://groot303.duckdns.org/"
TYPES = {"1B": "一买", "2B": "二买", "3B": "三买", "1S": "一卖", "2S": "二卖", "3S": "三卖",
         "ZG_S": "中枢上沿卖", "ZD_B": "中枢下沿买",
         "BC_B": "盘整背驰买", "BC_S": "盘整背驰卖",
         "PRE_1B": "预一买", "PRE_2B": "预二买", "PRE_3B": "预三买",
         "PRE_1S": "预一卖", "PRE_2S": "预二卖", "PRE_3S": "预三卖"}
LEVELS = {"weekly": "周线", "daily": "日线", "30m": "30分钟", "5m": "5分钟"}


def key(s):
    return "|".join([s["symbol"], s["level"], s["type"], s["time"]])


def load_state(path=STATE):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state, path=STATE):
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        json.dump(state, open(path, "w"), ensure_ascii=False, indent=1, sort_keys=True)
    except Exception:
        pass


def select(signals, state, score_min=SCORE_MIN):
    """Return signals needing notification: new, or unconfirmed->confirmed."""
    out = []
    for s in signals:
        if not s.get("recent") or s.get("score", 0) < score_min:
            continue
        prev = state.get(key(s))
        if prev is None or (not prev.get("confirmed") and s.get("confirmed")):
            out.append(s)
    return out


def update_state(signals, state):
    for s in signals:
        state[key(s)] = {"confirmed": bool(s.get("confirmed")), "score": s.get("score")}
    return state


def fmt(selected):
    lines = ["缠论信号提醒", ""]
    for s in selected:
        t = TYPES.get(s["type"], s["type"])
        conf = "已确认" if s.get("confirmed") else "未确认(可能重绘)"
        lines.append(f"{s['symbol']} | {LEVELS.get(s['level'], s['level'])} {t} | 分数 {s['score']} | "
                     f"价格 {s['price']:.2f} | 时间 {s['time']} | {conf}")
    lines += ["", f"网页: {URL}", "启发式规则,未回测,不构成投资建议。"]
    return "\n".join(lines)


def send(token, chat, text):
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r).get("ok") is True


def maybe_announce(state):
    """Send one-off announcement file contents once per content hash."""
    if not ANNOUNCE:
        return "no announce file configured"
    try:
        with open(ANNOUNCE, encoding="utf-8") as f:
            text = f.read().strip()
    except FileNotFoundError:
        return "no announce file"
    except Exception:
        return "announce read error"
    if not text:
        return "announce empty"
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    if state.get("announce:" + h):
        return "announce already sent"
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return "announce skipped: token/chat id missing"
    try:
        if send(token, chat, text):
            state["announce:" + h] = True
            save_state(state)
            return "announce sent"
        return "announce: Telegram returned not ok"
    except Exception:
        return "announce send error"


def main(argv):
    dry = "--dry-run" in argv
    baseline = "--baseline" in argv
    try:
        signals = json.load(open(SIGNALS)).get("signals", [])
        state = load_state()
        if baseline:
            update_state(signals, state)
            save_state(state)
            print(f"baseline written: {len(state)} signals")
            return 0
        # one-off announcement first (deduped by content hash)
        ann = maybe_announce(state)
        sel = select(signals, state)
        if not sel:
            print(f"no new signals to notify; {ann}")
            return 0
        text = fmt(sel)
        if dry:
            print("[dry-run] would send:\n" + text)
            print(f"; {ann}")
            return 0
        token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
        if not token or not chat:
            print(f"notify: token/chat id missing, skipped; {ann}")
            return 0
        if send(token, chat, text):
            update_state(sel, state)
            save_state(state)
            print(f"notified {len(sel)} signal(s); {ann}")
        else:
            print(f"notify: Telegram returned not ok; {ann}")
    except Exception as e:
        print(f"notify error: {type(e).__name__}")  # no details: URL contains token
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

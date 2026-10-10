#!/usr/bin/env python3
"""Telegram notifier for new high-score recent signals. stdlib only.
Never fails the workflow; never prints the token."""
import json, os, sys, urllib.request, urllib.parse

SCORE_MIN = float(os.environ.get("SCORE_MIN", "6.0"))
SIGNALS = os.environ.get("SIGNALS_FILE", "site/data/signals.json")
STATE = os.environ.get("STATE_FILE", "state/notified.json")
URL = "https://chan-monitor-web.pages.dev"
TYPES = {"1B": "一买", "2B": "二买", "3B": "三买", "1S": "一卖", "2S": "二卖", "3S": "三卖"}
LEVELS = {"weekly": "周线", "daily": "日线", "30m": "30分钟"}


def key(s):
    return "|".join([s["symbol"], s["level"], s["type"], s["time"]])


def load_state(path=STATE):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


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


def main(argv):
    dry = "--dry-run" in argv
    baseline = "--baseline" in argv
    try:
        signals = json.load(open(SIGNALS)).get("signals", [])
        state = load_state()
        if baseline:
            update_state(signals, state)
            os.makedirs(os.path.dirname(STATE), exist_ok=True)
            json.dump(state, open(STATE, "w"), ensure_ascii=False, indent=1, sort_keys=True)
            print(f"baseline written: {len(state)} signals")
            return 0
        sel = select(signals, state)
        if not sel:
            print("no new signals to notify")
            return 0
        text = fmt(sel)
        if dry:
            print("[dry-run] would send:\n" + text)
            return 0
        token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
        if not token or not chat:
            print("notify: token/chat id missing, skipped")
            return 0
        if send(token, chat, text):
            update_state(sel, state)
            os.makedirs(os.path.dirname(STATE), exist_ok=True)
            json.dump(state, open(STATE, "w"), ensure_ascii=False, indent=1, sort_keys=True)
            print(f"notified {len(sel)} signal(s)")
        else:
            print("notify: Telegram returned not ok")
    except Exception as e:
        print(f"notify error: {type(e).__name__}")  # no details: URL contains token
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

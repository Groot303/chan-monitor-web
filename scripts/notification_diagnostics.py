"""Read-only notification diagnostics; no message sends or credential values."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def telegram_probe(token, chat=None):
    """Only getMe/getChat; return coarse outcomes, never URLs/identifiers."""
    method = "getChat" if chat is not None else "getMe"
    url = "https://api.telegram.org/bot" + token + "/" + method
    if chat is not None:
        url += "?" + urllib.parse.urlencode({"chat_id": chat})
    try:
        with urllib.request.urlopen(url, timeout=8) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        try:
            data = json.load(error)
        except Exception:
            data = {"ok": False, "error_code": error.code}
    except Exception:
        return {"ok": False, "reason": "network_error"}
    if data.get("ok") is True:
        return {"ok": True}
    code = data.get("error_code")
    description = str(data.get("description", "")).lower()
    reason = "telegram_error"
    if code == 401:
        reason = "invalid_bot_token"
    elif "chat not found" in description:
        reason = "chat_not_found"
    elif "blocked" in description:
        reason = "bot_blocked"
    elif "not a member" in description:
        reason = "bot_not_member"
    elif code == 429:
        reason = "rate_limited"
    return {"ok": False, "reason": reason, "error_code": code}


def recent_outcomes(log_path):
    """Read a bounded log tail; output only allowlisted outcome categories."""
    outcomes = {}
    try:
        with Path(log_path).open("rb") as stream:
            stream.seek(max(0, Path(log_path).stat().st_size - 262144))
            lines = stream.read().decode(errors="replace").splitlines()
        for line in lines:
            for name in ("signals.json", "signals_cn.json"):
                marker = "notify[" + name + "]: "
                if marker not in line:
                    continue
                text = line.split(marker, 1)[1]
                if text.startswith("notified "):
                    outcome = "sent"
                elif text.startswith("no new signals"):
                    outcome = "no_new_signals"
                elif "token/chat id missing" in text:
                    outcome = "missing_configuration"
                elif text.startswith("notify error: HTTPError"):
                    outcome = "telegram_http_error"
                elif text.startswith("notify error:"):
                    outcome = "send_error"
                else:
                    outcome = "other"
                outcomes[name] = outcome
    except OSError:
        pass
    return outcomes


def diagnose(repo, data_dir, environ=None, probe=telegram_probe):
    """Inspect existing config/data/state, without altering any of them."""
    env = os.environ if environ is None else environ
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chat = env.get("TELEGRAM_CHAT_ID", "")
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "token_configured": bool(token),
        "chat_configured": bool(chat),
        "message_sent": False,
        "markets": {},
    }
    try:
        threshold = float(env.get("SCORE_MIN", "4.0"))
        if not 0 <= threshold <= 10:
            raise ValueError("invalid threshold")
        result["score_min"] = threshold
    except (TypeError, ValueError):
        result["configuration_error"] = "invalid_score_min"
        return result
    state_path = Path(repo) / "state" / "notified.json"
    try:
        state = json.loads(state_path.read_text())
        if not isinstance(state, dict):
            raise ValueError("invalid state")
        result["dedup_state"] = "available"
    except FileNotFoundError:
        state = {}
        result["dedup_state"] = "missing"
    except (OSError, ValueError):
        state = {}
        result["dedup_state"] = "unreadable"
    for name in ("signals.json", "signals_cn.json"):
        try:
            data = json.loads((Path(data_dir) / "data" / name).read_text())
            eligible = [s for s in data.get("signals", []) if s.get("recent") and s.get("score", 0) >= threshold]
            pending = []
            for signal in eligible:
                key = "|".join(str(signal[k]) for k in ("symbol", "level", "type", "time"))
                previous = state.get(key)
                if previous is None or (not previous.get("confirmed") and signal.get("confirmed")):
                    pending.append(signal)
            result["markets"][name] = {"generated": data.get("generated"), "eligible": len(eligible), "pending": len(pending)}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            result["markets"][name] = {"status": "data_unavailable"}
    result["recent_outcomes"] = recent_outcomes(Path(repo).parent / "logs" / "api.log")
    if token:
        result["bot"] = probe(token)
        if chat and result["bot"].get("ok"):
            result["chat"] = probe(token, chat)
    return result

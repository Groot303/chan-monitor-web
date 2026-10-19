#!/usr/bin/env python3
"""Apply only Telegram settings from deployment stdin; never print credentials."""
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.parse
import urllib.error


KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
ENV_PATH = Path("/opt/chan-monitor/.env")


def validate(payload):
    if not isinstance(payload, dict) or set(payload) != set(KEYS):
        raise ValueError("invalid configuration fields")
    if not isinstance(payload[KEYS[0]], str) or not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", payload[KEYS[0]]):
        raise ValueError("invalid bot token format")
    if not isinstance(payload[KEYS[1]], str) or not re.fullmatch(r"-?[0-9]+|@[A-Za-z0-9_]+", payload[KEYS[1]]):
        raise ValueError("invalid chat identifier format")
    if any(len(payload[k]) > 512 for k in KEYS):
        raise ValueError("configuration value too long")


def atomic_write(path, content, owner=None, mode=0o600):
    fd, name = tempfile.mkstemp(prefix=".telegram-env-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            if owner:
                os.fchown(stream.fileno(), *owner)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def apply(payload, path, restart):
    validate(payload)
    path = Path(path)
    if path.is_symlink():
        raise ValueError("configuration symlink not accepted")
    existed = path.exists()
    old_stat = path.stat() if existed else None
    old = path.read_bytes() if existed else b""
    lines = old.decode("utf-8").splitlines(keepends=True)
    values = {}
    for line in lines:
        key, sep, value = line.strip().partition("=")
        if sep and key.strip() in KEYS:
            values[key.strip()] = value.strip().strip("\"'")
    if values == payload:
        os.chmod(path, 0o600)
        return False
    retained = [line for line in lines if not re.match(r"^\s*(?:export\s+)?(?:TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID)\s*=", line)]
    text = "".join(retained)
    if text and not text.endswith("\n"):
        text += "\n"
    text += "".join(key + "=" + payload[key] + "\n" for key in KEYS)
    owner = (old_stat.st_uid, old_stat.st_gid) if old_stat else None
    atomic_write(path, text.encode(), owner)
    try:
        if not restart():
            raise RuntimeError("service health check failed")
    except Exception:
        if existed:
            atomic_write(path, old, owner, stat.S_IMODE(old_stat.st_mode))
        else:
            path.unlink(missing_ok=True)
        try:
            restart()
        except Exception:
            pass
        raise RuntimeError("configuration restored after failed restart") from None
    return True


def restart_service():
    result = subprocess.run(["systemctl", "restart", "chan-api"], capture_output=True, timeout=30)
    if result.returncode:
        return False
    for _ in range(12):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=2) as response:
                if json.load(response).get("status") == "ok":
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def check_telegram(payload):
    """Validate bot/chat using read-only methods before changing the service."""
    token = payload[KEYS[0]]
    for method, params in (("getMe", None), ("getChat", {"chat_id": payload[KEYS[1]]})):
        url = "https://api.telegram.org/bot" + token + "/" + method
        if params:
            url += "?" + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                if json.load(response).get("ok") is not True:
                    return "telegram_rejected"
        except urllib.error.HTTPError as error:
            if error.code == 401:
                return "invalid_bot_token"
            return "chat_unavailable" if method == "getChat" else "telegram_rejected"
        except Exception:
            return "telegram_network_unavailable"
    return None


def wait_for_delivery(log_path, offset, timeout=180):
    """Observe the normal scheduled/startup pipeline; never invoke a sender."""
    deadline = time.monotonic() + timeout
    seen = {}
    while time.monotonic() < deadline:
        try:
            with Path(log_path).open("rb") as stream:
                if Path(log_path).stat().st_size < offset:
                    offset = 0
                stream.seek(offset)
                lines = stream.read().decode(errors="replace").splitlines()
            for line in lines:
                for name in ("signals.json", "signals_cn.json"):
                    marker = "notify[" + name + "]: "
                    if marker not in line:
                        continue
                    text = line.split(marker, 1)[1]
                    if text.startswith("notified "):
                        match = re.match(r"notified ([0-9]+)", text)
                        seen[name] = "sent:" + (match.group(1) if match else "unknown")
                    elif text.startswith("no new signals"):
                        seen[name] = "no_new_signals"
                    elif "token/chat id missing" in text:
                        seen[name] = "missing_configuration"
                    else:
                        seen[name] = "send_failed"
            if len(seen) == 2:
                return seen
        except OSError:
            pass
        time.sleep(2)
    return seen


def main():
    try:
        raw = sys.stdin.buffer.read(8193)
        if not raw.strip():
            print("telegram configuration: not supplied, unchanged")
            return 0
        if len(raw) > 8192:
            raise ValueError("payload too large")
        payload = json.loads(raw)
        validate(payload)
        error = check_telegram(payload)
        if error:
            print("telegram configuration: " + error + "; server configuration unchanged", file=sys.stderr)
            return 1
        log_path = Path("/opt/chan-monitor/logs/api.log")
        offset = log_path.stat().st_size if log_path.exists() else 0
        changed = apply(payload, ENV_PATH, restart_service)
        print("telegram configuration: applied, service healthy" if changed else "telegram configuration: already current", flush=True)
        if changed:
            outcomes = wait_for_delivery(log_path, offset)
            print("telegram normal delivery outcomes: " + json.dumps(outcomes), flush=True)
            if not outcomes or any(outcome in ("send_failed", "missing_configuration") for outcome in outcomes.values()):
                print("telegram delivery requires follow-up", file=sys.stderr)
                return 1
        return 0
    except Exception:
        # 不打印异常正文，避免输入数据或网络URL进入部署日志。
        print("telegram configuration: failed; credentials not logged", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

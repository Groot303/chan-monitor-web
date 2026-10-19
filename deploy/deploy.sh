#!/bin/bash
# chan-monitor deploy executor v2.1
# ff-only 拉取 -> requirements 同步(快照回滚) -> unit/Caddyfile 同步 -> api.py 语法检查 -> 重启 -> 健康检查 -> 失败回滚(代码+依赖+unit+Caddy)
set -uo pipefail

REPO=/opt/chan-monitor/repo
VENV="$REPO/venv"
SELF=/opt/chan-monitor/deploy.sh
LOG=/var/log/chan-deploy.log
UNIT=/etc/systemd/system/chan-api.service
CADDY=/etc/caddy/Caddyfile
FREEZE=/opt/chan-monitor/venv-freeze.prev
export GIT_SSH_COMMAND="ssh -i /opt/chan-monitor/deploy_key -o StrictHostKeyChecking=accept-new"

exec 9>/var/run/chan-deploy.lock
flock -n 9 || { echo "another deploy in progress, skip"; exit 0; }

log() { local t; t=$(date +%H:%M:%S); echo "$t $*" >>"$LOG" 2>/dev/null; echo "[$t] $*"; }

self_update() {
  [ -f "$REPO/deploy/deploy.sh" ] || return 0
  cmp -s "$REPO/deploy/deploy.sh" "$SELF" && return 0
  if cp -f "$REPO/deploy/deploy.sh" "$SELF.new" && chmod 755 "$SELF.new" && mv -f "$SELF.new" "$SELF"; then log "deploy.sh self-updated"; else log "WARN: self-update failed"; fi
}

# 仅在既有部署通道中接受两项通知配置，不增加任意远程命令权限。
sync_telegram_config() {
  [ -f "$REPO/deploy/configure_telegram.py" ] || return 0
  "$VENV/bin/python" "$REPO/deploy/configure_telegram.py"
}

cd "$REPO" || exit 1

git checkout -- site/data/positions_ibkr.json 2>/dev/null || true
OTHER=$(git status --porcelain --untracked-files=no | awk '{print $2}' | grep -v '^site/data/positions_ibkr.json$' || true)
if [ -n "$OTHER" ]; then log "ABORT: dirty tracked files: $(echo $OTHER | tr '\n' ' ')"; exit 1; fi

git fetch --quiet origin main || { log "ABORT: git fetch failed"; exit 1; }
LOCAL=$(git rev-parse HEAD); REMOTE=$(git rev-parse origin/main)
if [ "$LOCAL" = "$REMOTE" ]; then log "up to date at $LOCAL"; self_update; sync_telegram_config; exit $?; fi

PREV=$LOCAL
log "deploying $LOCAL -> $REMOTE"
if ! git merge --ff-only origin/main >>"$LOG" 2>&1; then log "ABORT: ff-only merge failed"; exit 1; fi

CHANGED=$(git diff --name-only "$PREV" "$REMOTE")
log "changed: $(echo "$CHANGED" | tr '\n' ' ')"

NEED_RESTART=0; ENV_CHANGED=0; UNIT_CHANGED=0; CADDY_CHANGED=0

if echo "$CHANGED" | grep -qx "api.service"; then
  if install -m 644 api.service "$UNIT" && systemctl daemon-reload; then log "installed systemd unit"; UNIT_CHANGED=1; else log "WARN: unit install failed"; fi
  NEED_RESTART=1
fi

if echo "$CHANGED" | grep -qx "deploy/Caddyfile"; then
  if install -m 644 deploy/Caddyfile "$CADDY"; then
    systemctl reload caddy 2>/dev/null || systemctl restart caddy 2>/dev/null || log "WARN: caddy reload failed"
    log "installed Caddyfile"; CADDY_CHANGED=1
  else log "WARN: Caddyfile install failed"; fi
fi

if echo "$CHANGED" | grep -qx "requirements.txt"; then
  if [ -x "$VENV/bin/pip" ]; then
    "$VENV/bin/pip" freeze >"$FREEZE" 2>/dev/null || true
    log "requirements.txt changed -> pip install"
    if "$VENV/bin/pip" install -q -r requirements.txt >>"$LOG" 2>&1; then ENV_CHANGED=1; else
      log "WARN: pip install failed, restoring previous environment"
      "$VENV/bin/pip" install -q -r "$FREEZE" >>"$LOG" 2>&1 || true
    fi
  else log "WARN: venv pip not found ($VENV/bin/pip)"; fi
  NEED_RESTART=1
fi

if echo "$CHANGED" | grep -qx "api.py"; then NEED_RESTART=1; fi

rollback() {
  log "rolling back to $PREV"
  git reset --hard "$PREV" >>"$LOG" 2>&1
  if [ "$UNIT_CHANGED" = "1" ]; then install -m 644 "$REPO/api.service" "$UNIT" 2>/dev/null && systemctl daemon-reload; fi
  if [ "$CADDY_CHANGED" = "1" ]; then install -m 644 "$REPO/deploy/Caddyfile" "$CADDY" 2>/dev/null && { systemctl reload caddy 2>/dev/null || systemctl restart caddy 2>/dev/null; }; fi
  if [ "$ENV_CHANGED" = "1" ] && [ -s "$FREEZE" ]; then log "restoring python env from snapshot"; "$VENV/bin/pip" install -q -r "$FREEZE" >>"$LOG" 2>&1 || true; fi
  systemctl restart chan-api >>"$LOG" 2>&1
  sleep 6
  if curl -sf -o /dev/null http://127.0.0.1:8000/api/health; then log "rolled back, healthy"; else log "ROLLBACK UNHEALTHY - manual attention needed"; fi
  exit 1
}

if [ "$NEED_RESTART" = "1" ]; then
  if ! python3 -m py_compile api.py 2>>"$LOG"; then log "ABORT: api.py syntax error"; rollback; fi
  systemctl restart chan-api >>"$LOG" 2>&1
  sleep 6
  if curl -sf -o /dev/null http://127.0.0.1:8000/api/health; then log "OK restarted at $REMOTE"; else log "health FAILED"; rollback; fi
else
  log "OK static-only (no restart) at $REMOTE"
fi

self_update
sync_telegram_config

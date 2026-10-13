#!/bin/bash
# VPS pipeline for chan-monitor-web: pull latest code, run US+CN analysis,
# rebuild site data, commit & push. Runs every 15 min via cron.
# Server-side copy lives at /opt/chan-monitor/run_pipeline.sh (synced by git pull).
set -u
export GIT_SSH_COMMAND="ssh -i /opt/chan-monitor/deploy_key -o StrictHostKeyChecking=no -o ConnectTimeout=20"
if [ -f /opt/chan-monitor/.env ]; then
  set -a
  # shellcheck disable=SC1091
  source /opt/chan-monitor/.env
  set +a
fi
REPO=/opt/chan-monitor/repo
LOGDIR=/opt/chan-monitor/logs
mkdir -p "$LOGDIR"
LOG="$LOGDIR/pipeline-$(date +%Y%m%d).log"
{
echo "===== $(date -u '+%F %T UTC') pipeline start ====="
cd "$REPO" || exit 1
if [ "${API_MODE:-}" = "1" ]; then
  echo "API_MODE: skip git pull/commit/push, output to $API_DATA_DIR"
  export API_DATA_DIR="${API_DATA_DIR:-/opt/chan-monitor/api_data}"
  mkdir -p "$API_DATA_DIR"
else
  git pull --rebase -q 2>&1 | tail -1
  # refresh server-side copy of this script after pull
  cp -f "$REPO/scripts/vps_pipeline.sh" /opt/chan-monitor/run_pipeline.sh 2>/dev/null
  chmod +x /opt/chan-monitor/run_pipeline.sh 2>/dev/null
fi
VENV="$REPO/venv/bin/python"
mkdir -p out out_cn
if [ -n "${ALPACA_API_KEY:-}" ]; then
  $VENV run2.py 2>&1 | tail -2
  if [ -f out/signals.json ]; then $VENV scripts/build_data.py out 2>&1 | tail -1; fi
else
  echo "US skipped: ALPACA_API_KEY not set"
fi
$VENV run_cn.py 2>&1 | tail -2
if [ -f out_cn/signals.json ]; then $VENV scripts/build_data.py out_cn --market cn 2>&1 | tail -1; fi
if [ "${API_MODE:-}" = "1" ]; then
  echo "API_MODE: data written to $API_DATA_DIR, skip git"
else
  git add -A site/ 2>/dev/null
  if ! git diff --cached --quiet; then
    git -c user.name="chan-vps-bot" -c user.email="vps@local" commit -qm "chore: update signals $(date -u '+%FT%TZ')"
    if git push -q 2>&1 | tail -2; then echo "pushed OK"; else echo "push FAILED"; fi
  else
    echo "no site changes"
  fi
fi
echo "===== $(date -u '+%F %T UTC') pipeline end ====="
} >> "$LOG" 2>&1
find "$LOGDIR" -name 'pipeline-*.log' -mtime +14 -delete 2>/dev/null
exit 0

#!/usr/bin/env bash
# One-shot Caddy install for chan-monitor-web on the Alibaba Cloud VPS.
# Run as root on the VPS AFTER opening ports 80/443 in the console firewall.
set -euo pipefail
HOST="${1:-47-251-20-175.nip.io}"
if [ "$(id -u)" != "0" ]; then echo "run as root"; exit 1; fi
echo "==> installing Caddy (official repo)"
apt-get update -qq
apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list > /dev/null
apt-get update -qq && apt-get install -y -qq caddy
echo "==> writing Caddyfile for $HOST"
cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak 2>/dev/null || true
cp "$(dirname "$0")/Caddyfile" /etc/caddy/Caddyfile
sed -i "s/47-251-20-175.nip.io/$HOST/" /etc/caddy/Caddyfile
caddy fmt --overwrite /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile
systemctl enable --now caddy
systemctl reload caddy || systemctl restart caddy
echo "==> waiting for cert + backend (up to 90s)"
for i in $(seq 1 18); do
  if curl -sf "https://$HOST/api/health" | grep -q '"status":"ok"'; then
    echo "OK: https://$HOST/api/health is live"
    exit 0
  fi
  sleep 5
done
echo "WARN: backend not reachable yet. Check: firewall 80/443 open? 'systemctl status caddy' / 'journalctl -u caddy -n 50'"
exit 1

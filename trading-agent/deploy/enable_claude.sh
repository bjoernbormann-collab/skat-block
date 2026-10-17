#!/bin/bash
# Run on the server AFTER first boot:  sudo bash ~/skat-block/trading-agent/deploy/enable_claude.sh
# Asks for your Anthropic API key (input hidden, never printed, stored only in /etc/tradingagent.env, root-only),
# tests ONE real Claude call, and only then switches the paper agent from the placeholder to Claude.
# Still PAPER trading: no orders are sent anywhere.
set -e
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
read -r -s -p "Anthropic API key (hidden): " KEY; echo
[ -n "$KEY" ] || { echo "empty key"; exit 1; }
cd /home/ubuntu/skat-block/trading-agent
echo "Testing one Claude call ..."
ANTHROPIC_API_KEY="$KEY" /opt/ta-venv/bin/python - <<'PY'
import sys
sys.path.insert(0, ".")
from reflex.jev import ClaudeJev
from reflex.schema import JevDecision
state = dict(ts=0, mid=61000.0, spread_bps=1.2, imbalance=0.1, realized_vol=0.001, flow_net=0.05, inventory=0.0, drawdown=0.0)
d = JevDecision.parse(ClaudeJev().decide(state))
print("OK, valid answer:", d)
PY
umask 077
printf 'ANTHROPIC_API_KEY=%s\n' "$KEY" > /etc/tradingagent.env
sed -i 's/--jev placeholder/--jev claude/' /etc/systemd/system/tradingagent.service
systemctl daemon-reload && systemctl restart tradingagent
sleep 3; systemctl is-active tradingagent
echo "Claude is now the Jev (paper mode). Logs: journalctl -u tradingagent -f"

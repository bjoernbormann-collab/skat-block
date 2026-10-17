#!/bin/bash
# Oracle Cloud "Cloud-init script" (Create instance -> Advanced options -> Management -> Paste cloud-init script).
# Runs ONCE as root at first boot on Ubuntu. It installs and starts everything in PAPER mode with the placeholder Jev
# (no API key, no costs, never trades). Keys are NOT in this script; add them afterwards with deploy/enable_claude.sh.
# Log: /var/log/tradingagent-setup.log     Test result: /var/log/tradingagent-tests.log
exec > /var/log/tradingagent-setup.log 2>&1
set -x
export DEBIAN_FRONTEND=noninteractive
BRANCH=claude/new-session-1od9nf
REPO=https://github.com/bjoernbormann-collab/skat-block.git
U=ubuntu
H=/home/$U

apt-get update -y
apt-get install -y python3 python3-venv python3-pip git

# code
sudo -u $U git clone --branch "$BRANCH" "$REPO" $H/skat-block || { echo "CLONE FAILED (repo private or no network)"; exit 1; }
cd $H/skat-block/trading-agent
sudo -u $U mkdir -p data

# tests (must pass)
sudo -u $U python3 -m unittest discover -s tests > /var/log/tradingagent-tests.log 2>&1 \
  && echo "TESTS OK" >> /var/log/tradingagent-tests.log || echo "TESTS FAILED" >> /var/log/tradingagent-tests.log

# python env with the Anthropic SDK (used only after enable_claude.sh)
python3 -m venv /opt/ta-venv && /opt/ta-venv/bin/pip install anthropic

# secrets file (empty, root only)
touch /etc/tradingagent.env && chmod 600 /etc/tradingagent.env

cat > /etc/systemd/system/tradingagent.service <<UNIT
[Unit]
Description=Trading agent (paper)
After=network-online.target
Wants=network-online.target
[Service]
User=$U
WorkingDirectory=$H/skat-block/trading-agent
EnvironmentFile=/etc/tradingagent.env
ExecStart=/opt/ta-venv/bin/python tools/run_paper.py --jev placeholder --interval 300
Restart=always
RestartSec=20
NoNewPrivileges=true
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/tradingagent-dashboard.service <<UNIT
[Unit]
Description=Trading agent dashboard (read-only, localhost only)
After=network-online.target
[Service]
User=$U
WorkingDirectory=$H/skat-block/trading-agent
ExecStart=/opt/ta-venv/bin/python tools/dashboard.py --host 127.0.0.1 --port 8000
Restart=always
RestartSec=10
NoNewPrivileges=true
[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now tradingagent tradingagent-dashboard
echo "SETUP DONE $(date -u)"

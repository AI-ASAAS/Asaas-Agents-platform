#!/usr/bin/env bash
# ==============================================================================
# ASAAS Agents Platform: Provisioning Script for Tier-2 Service Agent Isolation
# Dedicated User: asaas-service-sitedna
# Controls: Linux cgroups v2, systemd resource limits, Playwright OS deps,
#           and nftables UID-scoped egress filtering (IPv4 + IPv6).
# ==============================================================================
set -euo pipefail

SERVICE_USER="asaas-service-sitedna"
SERVICE_GROUP="asaas-service-sitedna"
PLATFORM_DIR="/opt/asaas-platform"
AGENT_DIR="${PLATFORM_DIR}/agents/site-dna"
AGENT_STATE_DIR="/var/lib/asaas/service-agents/site-dna"
PLATFORM_LLM_PORT="8088"
SITE_DNA_PORT="8001"

echo "==> 1. Creating dedicated service user and group..."
if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
    sudo groupadd -r "${SERVICE_GROUP}"
    sudo useradd -r -g "${SERVICE_GROUP}" -s /usr/sbin/nologin -d "${AGENT_STATE_DIR}" "${SERVICE_USER}"
    echo "Created user ${SERVICE_USER}"
else
    echo "User ${SERVICE_USER} already exists."
fi

echo "==> 2. Setting up private scratch state directories (DAC 0700)..."
sudo mkdir -p "${AGENT_STATE_DIR}/runs" "${AGENT_STATE_DIR}/tmp"
sudo chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${AGENT_STATE_DIR}"
sudo chmod 700 "${AGENT_STATE_DIR}" "${AGENT_STATE_DIR}/runs" "${AGENT_STATE_DIR}/tmp"

echo "==> 3. Installing Playwright Chromium OS libraries (one-time root step) & enabling user namespaces..."
if [ -x "${AGENT_DIR}/.venv/bin/playwright" ]; then
    sudo "${AGENT_DIR}/.venv/bin/playwright" install-deps chromium
else
    echo "WARNING: ${AGENT_DIR}/.venv/bin/playwright not found yet. Run 'python scripts/sync_agents.py' first, then re-run 'playwright install-deps chromium'."
fi

if [ -f /proc/sys/kernel/unprivileged_userns_clone ]; then
    sudo sysctl -w kernel.unprivileged_userns_clone=1 || true
fi

echo "==> 4. Applying packet-level egress rules via nftables (IPv4 + IPv6)..."
sudo mkdir -p /etc/nftables.d
cat <<EOF | sudo tee /etc/nftables.d/asaas-sitedna.nft >/dev/null
table inet asaas_service_filter {
    chain output {
        type filter hook output priority 0; policy accept;
        meta skuid != "${SERVICE_USER}" accept

        # Allow replies for established connections (e.g. Site DNA HTTP responses on 127.0.0.1:${SITE_DNA_PORT})
        ct state established,related accept

        # Allow DNS lookups ONLY to local system stub resolver BEFORE loopback drop
        ip daddr 127.0.0.53 udp dport 53 accept
        ip daddr 127.0.0.53 tcp dport 53 accept

        # Allow loopback access ONLY to platform local LLM proxy (127.0.0.1:${PLATFORM_LLM_PORT})
        ip daddr 127.0.0.1 tcp dport ${PLATFORM_LLM_PORT} accept
        ip daddr 127.0.0.0/8 drop
        ip6 daddr ::1 drop

        # Drop RFC1918, CGNAT, link-local, cloud metadata, multicast, reserved, and IPv6 equivalents
        ip daddr { 10.0.0.0/8, 100.64.0.0/10, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16, 224.0.0.0/4, 240.0.0.0/4 } drop
        ip6 daddr { fc00::/7, fe80::/10, ff00::/8, ::ffff:0:0/96 } drop

        # Allow outbound HTTP/HTTPS exclusively to public Internet on ports 80/443
        tcp dport { 80, 443 } accept

        # Drop all remaining outbound traffic (non-80/443 ports, raw UDP, etc.)
        drop
    }
}
EOF
sudo nft delete table inet asaas_service_filter 2>/dev/null || true
sudo nft -f /etc/nftables.d/asaas-sitedna.nft

echo "==> 5. Provisioning systemd service unit with cgroup v2 limits..."
cat <<EOF | sudo tee /etc/systemd/system/asaas-sitedna.service >/dev/null
[Unit]
Description=Site DNA Tier-2 Service Agent Backend
After=network.target asaas-api.service
PartOf=asaas-api.service

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
WorkingDirectory=${AGENT_DIR}
Environment=PATH=${AGENT_DIR}/.venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=PLATFORM_MANAGED_SERVICE=1
Environment=SITE_DNA_SERVICE_MODE=true
Environment=SITE_DNA_DATA_DIR=${AGENT_STATE_DIR}/runs
Environment=SITE_DNA_PORT=${SITE_DNA_PORT}
Environment=PLATFORM_LLM_BASE_URL=http://127.0.0.1:${PLATFORM_LLM_PORT}/v1
Environment=PLAYWRIGHT_BROWSERS_PATH=${AGENT_DIR}/.playwright-browsers
Environment=CREWAI_TELEMETRY_OPT_OUT=true
Environment=OTEL_SDK_DISABLED=true
ExecStart=${AGENT_DIR}/.venv/bin/uvicorn site_dna.api.main:app --host 127.0.0.1 --port ${SITE_DNA_PORT} --workers 1
Restart=always
RestartSec=3

# Resource Ceilings & Isolation (cgroups v2) — Assumptions to tune
MemoryMax=2G
CPUQuota=200%
TasksMax=96
ProtectSystem=strict
ReadOnlyPaths=${AGENT_DIR}
ReadWritePaths=${AGENT_STATE_DIR}/runs ${AGENT_STATE_DIR}/tmp
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload || true
echo "==> Provisioning complete. Verify rules with 'sudo nft list table inet asaas_service_filter'."

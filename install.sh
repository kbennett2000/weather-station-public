#!/usr/bin/env bash
#
# Jones Big Ass Weather Dashboard — installer for Ubuntu Server / Debian.
#
# What this does:
#   * Installs apt packages: python3, python3-venv, sqlite3, ufw, curl.
#   * Creates a venv at server/.venv and installs the FastAPI server in
#     editable mode with --extra-index-url disabled (uses defaults).
#   * Drops a systemd unit at /etc/systemd/system/weather-server.service
#     so the server runs at boot, restarts on failure, logs to journald.
#   * Opens TCP 8005 in UFW and leaves all other inbound ports closed.
#
# What this DOES NOT do (intentionally — out of scope per CLAUDE.md):
#   * No iptables redirects. Dashboard binds directly to 8005.
#   * No MariaDB / MySQL. Storage is SQLite (single file under server/).
#   * No network configuration (netplan / static IP). DHCP works fine;
#     pin the host in your router if you want a stable address.
#   * No ESP32 sketch flashing. Use arduino-cli or the Arduino IDE.
#
# Optional flags:
#   --with-widget      Also install GTK system packages for the tray
#                      widget (python3-gi, gir1.2-appindicator3-0.1, ...).
#   --no-systemd       Skip the systemd unit (useful for dev environments
#                      where you'd rather run `make dev` by hand).
#   --no-firewall      Skip the UFW step (leaves the firewall untouched).
#   --no-start         Install everything but don't start the service
#                      yet. Handy when you still need to edit weather.toml.
#
# Usage:
#   git clone https://github.com/kbennett2000/weather-station-public.git
#   cd weather-station-public
#   sudo ./install.sh                       # server only
#   sudo ./install.sh --with-widget         # server + widget deps
#
# This script is idempotent: re-running it on an already-installed host
# is safe and will reconcile any drift (apt, venv, unit file, ufw rule).

set -euo pipefail

# ──────────────────────────────────────────────────────────────────────
# Argument parsing
# ──────────────────────────────────────────────────────────────────────

WITH_WIDGET=false
DO_SYSTEMD=true
DO_FIREWALL=true
DO_START=true

for arg in "$@"; do
    case "$arg" in
        --with-widget)  WITH_WIDGET=true ;;
        --no-systemd)   DO_SYSTEMD=false ;;
        --no-firewall)  DO_FIREWALL=false ;;
        --no-start)     DO_START=false ;;
        -h|--help)
            sed -n '2,/^set -/p' "$0" | sed 's/^# \{0,1\}//; /^set -/d'
            exit 0
            ;;
        *)
            echo "unknown flag: $arg" >&2
            echo "see: $0 --help" >&2
            exit 2
            ;;
    esac
done

# ──────────────────────────────────────────────────────────────────────
# Pre-flight: must be root, must know which user owns the install
# ──────────────────────────────────────────────────────────────────────

if [[ $EUID -ne 0 ]]; then
    echo "install.sh must be run as root (use sudo)." >&2
    exit 1
fi

if [[ -z "${SUDO_USER:-}" || "$SUDO_USER" == "root" ]]; then
    cat >&2 <<EOF
install.sh expected to be invoked via 'sudo' from a regular user
account, so it can derive ownership of the venv, repo, and systemd
unit from \$SUDO_USER. Got: SUDO_USER='${SUDO_USER:-<unset>}'.

If you're logged in as root, log out and run again as a non-root user:
    sudo ./install.sh
EOF
    exit 1
fi

INSTALL_USER="$SUDO_USER"
INSTALL_HOME="$(getent passwd "$INSTALL_USER" | cut -d: -f6)"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$REPO_DIR/server/.venv"
UNIT_PATH="/etc/systemd/system/weather-server.service"

echo "==> Install user: $INSTALL_USER (home: $INSTALL_HOME)"
echo "==> Repo dir: $REPO_DIR"
echo "==> Venv: $VENV_DIR"

# ──────────────────────────────────────────────────────────────────────
# apt packages
# ──────────────────────────────────────────────────────────────────────

echo "==> Installing system packages…"
apt-get update
apt-get install -y \
    python3 \
    python3-venv \
    python3-pip \
    sqlite3 \
    curl \
    ufw

if $WITH_WIDGET; then
    echo "==> Installing GTK widget dependencies…"
    apt-get install -y \
        python3-gi \
        gir1.2-gtk-3.0 \
        gir1.2-appindicator3-0.1 \
        python3-requests
fi

# ──────────────────────────────────────────────────────────────────────
# Python venv + server install
# ──────────────────────────────────────────────────────────────────────

if [[ ! -d "$VENV_DIR" ]]; then
    echo "==> Creating venv at $VENV_DIR…"
    sudo -u "$INSTALL_USER" python3 -m venv "$VENV_DIR"
fi

echo "==> Installing server (editable) into venv…"
sudo -u "$INSTALL_USER" "$VENV_DIR/bin/pip" install --upgrade pip
sudo -u "$INSTALL_USER" "$VENV_DIR/bin/pip" install -e "$REPO_DIR/server"

# ──────────────────────────────────────────────────────────────────────
# Config: copy weather.toml.example if no live config exists yet
# ──────────────────────────────────────────────────────────────────────

if [[ ! -f "$REPO_DIR/server/weather.toml" ]]; then
    echo "==> Seeding server/weather.toml from weather.toml.example…"
    sudo -u "$INSTALL_USER" cp \
        "$REPO_DIR/server/weather.toml.example" \
        "$REPO_DIR/server/weather.toml"
    SEEDED_SERVER_CONFIG=true
else
    echo "==> server/weather.toml already exists, leaving it alone."
    SEEDED_SERVER_CONFIG=false
fi

if $WITH_WIDGET && [[ ! -f "$REPO_DIR/widget/config.toml" ]]; then
    echo "==> Seeding widget/config.toml from config.toml.example…"
    sudo -u "$INSTALL_USER" cp \
        "$REPO_DIR/widget/config.toml.example" \
        "$REPO_DIR/widget/config.toml"
fi

# ──────────────────────────────────────────────────────────────────────
# systemd unit
# ──────────────────────────────────────────────────────────────────────

if $DO_SYSTEMD; then
    echo "==> Writing $UNIT_PATH…"
    cat > "$UNIT_PATH" <<EOF
[Unit]
Description=Jones Big Ass Weather Dashboard (FastAPI)
Documentation=https://github.com/kbennett2000/weather-station-public
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
User=$INSTALL_USER
Group=$INSTALL_USER
WorkingDirectory=$REPO_DIR/server
ExecStart=$VENV_DIR/bin/uvicorn weather_server.main:app --host 0.0.0.0 --port 8005
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

# Lock down a few things — server only needs to read repo files and
# write its SQLite db under server/. No network privilege escalation,
# no /tmp, no kernel modules.
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths=$REPO_DIR/server
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable weather-server.service >/dev/null

    if $DO_START; then
        echo "==> Starting weather-server.service…"
        systemctl restart weather-server.service
        sleep 2
        systemctl --no-pager --lines=10 status weather-server.service || true
    else
        echo "==> --no-start: leaving weather-server.service stopped."
        echo "    Edit $REPO_DIR/server/weather.toml, then:"
        echo "        sudo systemctl start weather-server.service"
    fi
fi

# ──────────────────────────────────────────────────────────────────────
# Firewall
# ──────────────────────────────────────────────────────────────────────

if $DO_FIREWALL; then
    echo "==> Configuring UFW (allow ssh + 8005, deny everything else)…"
    ufw --force enable >/dev/null
    ufw allow ssh >/dev/null
    ufw allow 8005/tcp >/dev/null
    ufw reload >/dev/null
    ufw status verbose | sed 's/^/    /'
fi

# ──────────────────────────────────────────────────────────────────────
# Done
# ──────────────────────────────────────────────────────────────────────

cat <<EOF

✔ Install complete.

Next steps:
  1. Edit $REPO_DIR/server/weather.toml — set the IPs and
     fallback_lat / fallback_lon for your sensors. The example file
     uses fixture mode for offline testing; comment out the
     [development] block to poll real ESP32s.
EOF

if $DO_SYSTEMD; then
cat <<EOF
  2. Restart the service so it picks up your edits:
        sudo systemctl restart weather-server.service
     Tail logs with:
        journalctl -u weather-server.service -f
EOF
fi

cat <<EOF
  3. Open http://<this-host>:8005 in a browser. Dashboard should load
     and (if real sensors are reachable) show live data within ~30s.

EOF

if $WITH_WIDGET; then
cat <<EOF
Widget (optional):
  * Run 'make widget' from $REPO_DIR, or add 'python3 widget/weather_tray.py'
    to your desktop autostart. Uses the SYSTEM python so it can find gi.
  * Edit $REPO_DIR/widget/config.toml to point at this host's URL.

EOF
fi

if $SEEDED_SERVER_CONFIG; then
    echo "Reminder: server/weather.toml was just created from the example."
    echo "You almost certainly want to edit it before considering this done."
fi

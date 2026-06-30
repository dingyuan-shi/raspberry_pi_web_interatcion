#!/usr/bin/env bash
#
# Installer for the Pi remote-control web service.
# Installs into /opt/pi-remote and enables web-pi-control.service.
#
# Usage:  sudo ./install.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "This installer must be run as root (sudo ./install.sh)" >&2
    exit 1
fi

SRC_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
INSTALL_DIR="/opt/pi-remote"

echo ">>> Checking system packages"
PKGS=(python3 python3-venv python3-pip rsync)
# chromium-browser is optional - only used by /api/cheap.png to render
# the dashboard for Kindle / e-ink clients.  We list it so the installer
# auto-pulls it when missing, but install will still succeed without.
OPTIONAL_PKGS=(chromium-browser)

MISSING=()
for p in "${PKGS[@]}"; do
    if ! dpkg -l "$p" 2>/dev/null | grep -q '^ii'; then
        MISSING+=("$p")
    fi
done

if [[ ${#MISSING[@]} -eq 0 ]]; then
    echo "    -> all required packages already installed; skipping apt"
else
    echo "    -> need to install: ${MISSING[*]}"
    apt-get update --allow-releaseinfo-change || \
        echo "WARNING: apt-get update reported errors; continuing anyway"
    if ! apt-get install -y "${MISSING[@]}"; then
        echo
        echo "ERROR: apt-get install failed for: ${MISSING[*]}"
        echo "       Fix your apt sources (Raspbian Buster needs legacy.raspbian.org)"
        echo "       or set NO_VENV=1 if only python3-venv is missing."
        exit 1
    fi
fi

# Look for a chromium-like binary; install one if it's missing, but don't
# fail the install if apt can't fetch it (the Kindle/Lite render path is
# optional - everything else works without it).
if ! command -v chromium-browser >/dev/null 2>&1 \
   && ! command -v chromium >/dev/null 2>&1 \
   && ! command -v google-chrome >/dev/null 2>&1 \
   && ! command -v google-chrome-stable >/dev/null 2>&1; then
    echo ">>> chromium not found; attempting to install (needed for /cheap)"
    apt-get install -y "${OPTIONAL_PKGS[@]}" \
        || echo "WARNING: could not install chromium-browser; /api/cheap.png will be disabled"
fi

echo ">>> Copying source to ${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"

# Retire the old BLE-only service from early prototypes of this project.
if systemctl is-enabled ble-pi-control.service &>/dev/null \
   || systemctl is-active ble-pi-control.service &>/dev/null; then
    echo ">>> Disabling legacy ble-pi-control.service"
    systemctl disable --now ble-pi-control.service 2>/dev/null || true
    rm -f /etc/systemd/system/ble-pi-control.service
fi
if [[ -d /opt/ble-pi-control ]]; then
    echo ">>> Removing legacy /opt/ble-pi-control"
    rm -rf /opt/ble-pi-control
fi

rsync -a --delete \
    --exclude '.git' --exclude '.venv' --exclude 'venv' --exclude '__pycache__' \
    "${SRC_DIR}/" "${INSTALL_DIR}/"

# Use a China-friendly PyPI mirror by default; override with PIP_INDEX_URL.
: "${PIP_INDEX_URL:=https://pypi.tuna.tsinghua.edu.cn/simple}"
export PIP_INDEX_URL
# Raspbian's stock /etc/pip.conf adds piwheels.org as an extra-index-url.
# That mirror is in the UK and frequently times out from China, so disable
# it unless the caller deliberately set PIP_EXTRA_INDEX_URL themselves.
: "${PIP_EXTRA_INDEX_URL:=}"
export PIP_EXTRA_INDEX_URL
: "${PIP_DEFAULT_TIMEOUT:=120}"
export PIP_DEFAULT_TIMEOUT
echo "    -> using PyPI mirror: ${PIP_INDEX_URL}"

if [[ "${NO_VENV:-0}" == "1" ]]; then
    echo ">>> NO_VENV=1; installing dependencies against system python3"
    mkdir -p "${INSTALL_DIR}/venv/bin"
    ln -sf "$(command -v python3)" "${INSTALL_DIR}/venv/bin/python"
    PIP_BIN=(python3 -m pip)
    "${PIP_BIN[@]}" install --upgrade pip || true
    "${PIP_BIN[@]}" install -r "${INSTALL_DIR}/requirements.txt"
else
    echo ">>> Creating virtual-env at ${INSTALL_DIR}/venv"
    python3 -m venv "${INSTALL_DIR}/venv"
    PIP_BIN=("${INSTALL_DIR}/venv/bin/pip")
    "${PIP_BIN[@]}" install --upgrade pip
    "${PIP_BIN[@]}" install -r "${INSTALL_DIR}/requirements.txt"
fi

echo ">>> Installing web-pi-control.service"
install -m 0644 "${SRC_DIR}/systemd/web-pi-control.service" /etc/systemd/system/web-pi-control.service
if [[ ! -f /etc/default/web-pi-control ]]; then
    install -m 0644 "${SRC_DIR}/systemd/web-pi-control.default" /etc/default/web-pi-control
    SECRET=$(openssl rand -hex 32 2>/dev/null || python3 -c 'import secrets;print(secrets.token_hex(32))')
    sed -i "s|^WEB_SESSION_SECRET=.*|WEB_SESSION_SECRET=${SECRET}|" /etc/default/web-pi-control
    echo "    -> wrote /etc/default/web-pi-control with random session secret"
    echo "    -> edit WEB_PASSWORD before exposing the box!"
fi

systemctl daemon-reload
systemctl enable --now web-pi-control.service

echo
echo "Done.  journalctl -fu web-pi-control.service  (default http://<pi-ip>:8080)"

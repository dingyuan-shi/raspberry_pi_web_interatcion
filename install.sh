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

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [[ "$PY_MAJOR" -lt 3 || ( "$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 11 ) ]]; then
    echo "ERROR: Python 3.11+ required (found ${PY_VER})." >&2
    echo "       Raspberry Pi OS Bookworm ships Python 3.11." >&2
    exit 1
fi
echo ">>> Python ${PY_VER}"

echo ">>> Checking system packages"
PKGS=(python3 python3-venv python3-pip rsync)
# chromium is optional - only used by /api/cheap.png (see below).
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
        echo "       On Raspberry Pi OS Bookworm install python3-venv with:"
        echo "         sudo apt-get install python3-venv"
        echo "       or set NO_VENV=1 if you prefer the system python3."
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
    if ! apt-get install -y chromium; then
        apt-get install -y chromium-browser \
            || echo "WARNING: could not install chromium; /api/cheap.png will be disabled"
    fi
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

# PyPI index (China-friendly default). Override: PIP_INDEX_URL=https://pypi.org/simple
: "${PIP_INDEX_URL:=https://pypi.tuna.tsinghua.edu.cn/simple}"
: "${PIP_DEFAULT_TIMEOUT:=120}"
# Raspberry Pi OS adds piwheels.org in /etc/pip.conf; from China it is often
# very slow.  Set USE_PIWHEELS=1 to opt back in (useful on UK/EU networks).
: "${USE_PIWHEELS:=0}"

PIP_CONF_FILE="${INSTALL_DIR}/.pip.conf"
{
    echo "[global]"
    echo "index-url = ${PIP_INDEX_URL}"
    echo "timeout = ${PIP_DEFAULT_TIMEOUT}"
    if [[ "${USE_PIWHEELS}" == "1" ]]; then
        echo "extra-index-url = https://www.piwheels.org/simple"
    fi
} >"${PIP_CONF_FILE}"
# When PIP_CONFIG_FILE is set, pip loads ONLY this file (not /etc/pip.conf).
# Do NOT combine with --isolated — that flag ignores env vars and leaves
# the system piwheels extra-index-url active.
export PIP_CONFIG_FILE="${PIP_CONF_FILE}"

PIP_TRUSTED_HOST=$(
    python3 -c "from urllib.parse import urlparse; print(urlparse('${PIP_INDEX_URL}').hostname or '')"
)
PIP_ARGS=(
    --index-url "${PIP_INDEX_URL}"
    --timeout "${PIP_DEFAULT_TIMEOUT}"
    --no-cache-dir
)
if [[ -n "${PIP_TRUSTED_HOST}" && "${PIP_TRUSTED_HOST}" != "pypi.org" ]]; then
    PIP_ARGS+=(--trusted-host "${PIP_TRUSTED_HOST}")
fi

if [[ "${USE_PIWHEELS}" == "1" ]]; then
    echo "    -> using PyPI mirror: ${PIP_INDEX_URL} + piwheels.org"
else
    echo "    -> using PyPI mirror: ${PIP_INDEX_URL} (piwheels disabled)"
fi

write_venv_pip_conf() {
    # Site config inside the venv — belt-and-suspenders for venv/bin/pip.
    if [[ -d "${INSTALL_DIR}/venv" ]]; then
        cp "${PIP_CONF_FILE}" "${INSTALL_DIR}/venv/pip.conf"
    fi
}

pip_install() {
    "${PIP_BIN[@]}" cache purge >/dev/null 2>&1 || true
    "${PIP_BIN[@]}" install "${PIP_ARGS[@]}" "$@"
}
if [[ "${NO_VENV:-0}" == "1" ]]; then
    echo ">>> NO_VENV=1; installing dependencies against system python3"
    mkdir -p "${INSTALL_DIR}/venv/bin"
    ln -sf "$(command -v python3)" "${INSTALL_DIR}/venv/bin/python"
    PIP_BIN=(python3 -m pip)
    write_venv_pip_conf
    pip_install -r "${INSTALL_DIR}/requirements.txt"
else
    echo ">>> Creating virtual-env at ${INSTALL_DIR}/venv"
    python3 -m venv "${INSTALL_DIR}/venv"
    write_venv_pip_conf
    PIP_BIN=("${INSTALL_DIR}/venv/bin/pip")
    # venv ships a working pip; skip --upgrade pip to avoid slow downloads.
    pip_install -r "${INSTALL_DIR}/requirements.txt"
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

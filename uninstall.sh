#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "This script must run as root." >&2
    exit 1
fi

systemctl disable --now web-pi-control.service 2>/dev/null || true
rm -f /etc/systemd/system/web-pi-control.service

# Legacy BLE installer (removed from this project).
systemctl disable --now ble-pi-control.service 2>/dev/null || true
rm -f /etc/systemd/system/ble-pi-control.service
rm -rf /opt/ble-pi-control

rm -rf /opt/pi-remote
systemctl daemon-reload

echo "Removed web-pi-control and /opt/pi-remote."
echo "Removed legacy ble-pi-control (if present)."
echo "Left /etc/default/web-pi-control and /etc/default/ble-pi-control alone;"
echo "delete those manually if you want."

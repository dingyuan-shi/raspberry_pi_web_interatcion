"""Runtime configuration for the web service.

Every value can be overridden through an environment variable
(``/etc/default/web-pi-control`` when running under systemd).
"""

from __future__ import annotations

import os


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _pin_set(raw: str) -> set[int]:
    return {int(p) for p in raw.split(",") if p.strip()}


# ---- shared command-layer settings ---------------------------------------- #

ENABLE_SHELL: bool = _bool(os.environ.get("PI_REMOTE_ENABLE_SHELL"), True)
SHELL_AUTH_TOKEN: str = os.environ.get("PI_REMOTE_SHELL_TOKEN", "changeme")
GPIO_ALLOWED_PINS: set[int] = _pin_set(
    os.environ.get("PI_REMOTE_GPIO_PINS", "17,18,22,23,24,25,27")
)
SHELL_TIMEOUT_SECONDS: float = float(os.environ.get("PI_REMOTE_SHELL_TIMEOUT", "30"))

# ---- Status / monitor pushes --------------------------------------------- #

STATUS_INTERVAL_SECONDS: float = float(os.environ.get("STATUS_INTERVAL", "5"))
MONITOR_HISTORY_POINTS: int = int(os.environ.get("MONITOR_HISTORY_POINTS", "60"))


# ---- Web transport -------------------------------------------------------- #
# Defaults below are placeholders only — change them before exposing the host.

WEB_HOST: str = os.environ.get("WEB_HOST", "0.0.0.0")
WEB_PORT: int = int(os.environ.get("WEB_PORT", "8080"))
WEB_PASSWORD: str = os.environ.get("WEB_PASSWORD", "changeme")
WEB_SESSION_SECRET: str = os.environ.get(
    "WEB_SESSION_SECRET",
    "please-change-this-to-a-random-string",
)
WEB_SESSION_HOURS: int = int(os.environ.get("WEB_SESSION_HOURS", "12"))
# When enabled the /api/shell WebSocket gives a full interactive PTY.  The
# command-protocol shell:<...> rule still respects ENABLE_SHELL above.
WEB_ENABLE_PTY: bool = _bool(os.environ.get("WEB_ENABLE_PTY"), True)

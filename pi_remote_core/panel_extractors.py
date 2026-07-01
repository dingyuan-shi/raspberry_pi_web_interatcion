"""Run panel shell commands and parse output for the monitor UI."""

from __future__ import annotations

import re
import subprocess
import time
from typing import Any

from . import config
from .monitor_panels import (
    DISPLAY_CHART,
    DISPLAY_DISKS,
    DISPLAY_TABLE,
    DISPLAY_TEXT,
    PARSE_DF,
    PARSE_FLOAT,
    PARSE_NETRATE,
    PARSE_PS,
    PARSE_REGEX,
    PARSE_TEXT,
)

_FLOAT_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
# Block command substitution; pipes/redirects are allowed for normal shell one-liners.
_SHELL_DENY_RE = re.compile(r"\$\(|`|\$\{")

_NETRATE_STATE: dict[str, tuple[float, int, int]] = {}
_SKIP_FS = {"tmpfs", "devtmpfs", "overlay", "squashfs", "aufs", ""}


def _strip_shell_prefix(cmd: str) -> str:
    text = cmd.strip()
    if text.lower().startswith("shell:"):
        return text[6:].strip()
    return text


def run_shell_command(cmd: str) -> str:
    if not config.ENABLE_SHELL:
        raise ValueError("shell disabled by config")
    command = _strip_shell_prefix(cmd)
    if not command:
        raise ValueError("empty shell command")
    if _SHELL_DENY_RE.search(command):
        raise ValueError("shell command contains disallowed substitution")
    try:
        out = subprocess.check_output(
            command,
            shell=True,
            text=True,
            stderr=subprocess.STDOUT,
            timeout=min(config.SHELL_TIMEOUT_SECONDS, 10.0),
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("shell timeout") from exc
    except subprocess.CalledProcessError as exc:
        return (exc.output or "").rstrip()
    return out.rstrip()


def _parse_float(output: str) -> float | None:
    match = _FLOAT_RE.search(output)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def _parse_regex(output: str, pattern: str) -> float | str | None:
    if not pattern:
        return None
    match = re.search(pattern, output)
    if not match:
        return None
    raw = match.group(1) if match.lastindex else match.group(0)
    try:
        return float(raw)
    except ValueError:
        return raw


def _sum_net_bytes(output: str) -> tuple[int, int]:
    rx = tx = 0
    for line in output.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        name, rest = line.split(":", 1)
        name = name.strip()
        if name == "lo" or name.endswith("lo"):
            continue
        parts = rest.split()
        if len(parts) < 9:
            continue
        try:
            rx += int(parts[0])
            tx += int(parts[8])
        except ValueError:
            continue
    return rx, tx


def _parse_netrate(panel_id: str, output: str) -> dict[str, Any]:
    rx, tx = _sum_net_bytes(output)
    now = time.monotonic()
    last = _NETRATE_STATE.get(panel_id)
    _NETRATE_STATE[panel_id] = (now, rx, tx)
    if last is None:
        return {"value": None, "meta": "等待下一次采样…"}
    dt = now - last[0]
    if dt <= 0:
        return {"value": None, "meta": "等待下一次采样…"}
    rx_bps = max(0.0, (rx - last[1]) / dt)
    tx_bps = max(0.0, (tx - last[2]) / dt)
    rx_kb = rx_bps / 1024
    tx_kb = tx_bps / 1024
    total = round(rx_kb + tx_kb, 2)
    return {
        "value": total,
        "meta": f"↓{rx_kb:.1f} KB/s  ↑{tx_kb:.1f} KB/s",
    }


def _parse_df(output: str) -> list[dict[str, Any]]:
    disks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in output.strip().splitlines():
        parts = line.split()
        if len(parts) < 6:
            continue
        filesystem = parts[0]
        if filesystem.startswith("Filesystem"):
            continue
        if filesystem in _SKIP_FS or "loop" in filesystem:
            continue
        try:
            total = int(parts[1])
            used = int(parts[2])
            avail = int(parts[3])
            pcent_raw = parts[4].rstrip("%")
            mount = parts[5]
            percent = float(pcent_raw)
        except (ValueError, IndexError):
            continue
        if mount in seen or total <= 0:
            continue
        if mount in {"/dev/shm", "/run", "/sys/fs/cgroup"}:
            continue
        fstype = filesystem.rsplit("/", 1)[-1] if filesystem.startswith("/dev") else filesystem
        if fstype in _SKIP_FS:
            continue
        seen.add(mount)
        disks.append(
            {
                "mount": mount,
                "fstype": fstype,
                "total": total,
                "used": used,
                "free": avail,
                "percent": percent,
            }
        )
    return disks


def _parse_ps(output: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in output.strip().splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        try:
            rows.append(
                {
                    "pid": int(parts[0]),
                    "user": parts[1],
                    "name": parts[2],
                    "cpu_pct": float(parts[3]),
                    "mem_pct": float(parts[4]),
                }
            )
        except ValueError:
            continue
    return rows


def extract_panel(panel: dict[str, Any]) -> dict[str, Any]:
    parse = panel.get("parse", PARSE_FLOAT)
    display = panel.get("display", DISPLAY_CHART)
    parse_arg = panel.get("parse_arg", "")
    panel_id = panel["id"]

    try:
        raw = run_shell_command(panel["command"])
    except Exception as exc:  # pylint: disable=broad-except
        return {"value": None, "meta": f"err: {exc}", "error": str(exc)}

    try:
        if parse == PARSE_NETRATE:
            return _parse_netrate(panel_id, raw)
        if parse == PARSE_DF:
            disks = _parse_df(raw)
            return {"disks": disks, "meta": ""}
        if parse == PARSE_PS:
            top = _parse_ps(raw)
            return {"top": top, "meta": ""}
        if parse == PARSE_TEXT:
            text = raw.strip() or "—"
            return {"text": text, "meta": text, "raw": raw[:500]}
        if parse == PARSE_REGEX:
            value = _parse_regex(raw, parse_arg)
        else:
            value = _parse_float(raw)

        if display == DISPLAY_TEXT:
            text = value if isinstance(value, str) else (str(value) if value is not None else raw[:200])
            return {"text": text, "meta": text, "raw": raw[:500]}
        if isinstance(value, (int, float)):
            unit = panel.get("unit", "")
            suffix = f" {unit}" if unit else ""
            return {
                "value": float(value),
                "meta": f"cur: {float(value):.2f}{suffix}".rstrip(),
                "raw": raw[:500],
            }
        return {"value": None, "meta": "cur: ?", "raw": raw[:500]}
    except Exception as exc:  # pylint: disable=broad-except
        return {"value": None, "meta": f"err: {exc}", "error": str(exc)}


def panel_snapshot(_snap: dict[str, Any], panels: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Evaluate every panel via its shell command (snap kept for API compatibility)."""
    return {panel["id"]: extract_panel(panel) for panel in panels}

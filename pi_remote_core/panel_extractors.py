"""Evaluate monitor panel definitions against live system data."""

from __future__ import annotations

import re
import subprocess
from typing import Any

from . import config, system_info
from .monitor_panels import (
    DISPLAY_CHART,
    DISPLAY_DISKS,
    DISPLAY_TABLE,
    DISPLAY_TEXT,
    EXTRACT_BUILTIN,
    EXTRACT_SHELL,
    PARSE_FLOAT,
    PARSE_REGEX,
    PARSE_TEXT,
)

_FLOAT_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
_SHELL_DENY_RE = re.compile(r"[;&|`$]|(?:\.\./)|(?:>\s*/)")


def _strip_shell_prefix(cmd: str) -> str:
    text = cmd.strip()
    if text.lower().startswith("shell:"):
        return text[6:].strip()
    return text


def _human_bytes(n: float | int | None) -> str:
    if n is None:
        return "?"
    value = float(n)
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    digits = 1 if value < 10 else 0
    return f"{value:.{digits}f} {units[idx]}"


def run_shell_command(cmd: str) -> str:
    if not config.ENABLE_SHELL:
        raise ValueError("shell disabled by config")
    command = _strip_shell_prefix(cmd)
    if not command:
        raise ValueError("empty shell command")
    if _SHELL_DENY_RE.search(command):
        raise ValueError("shell command contains disallowed characters")
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


def parse_shell_output(output: str, parse: str, parse_arg: str) -> float | str | None:
    if parse == PARSE_TEXT:
        text = output.strip()
        return text or None
    if parse == PARSE_FLOAT:
        match = _FLOAT_RE.search(output)
        if not match:
            return None
        try:
            return float(match.group())
        except ValueError:
            return None
    if parse == PARSE_REGEX:
        if not parse_arg:
            return None
        match = re.search(parse_arg, output)
        if not match:
            return None
        raw = match.group(1) if match.lastindex else match.group(0)
        try:
            return float(raw)
        except ValueError:
            return raw
    return None


def _builtin_cpu(snap: dict[str, Any]) -> dict[str, Any]:
    load = snap.get("load")
    cores = snap.get("cpu_per_core") or []
    load_s = " / ".join(f"{x:.2f}" for x in load) if load else "?"
    cores_s = " ".join(f"{v:.0f}%" for v in cores) or "?"
    return {
        "value": snap.get("cpu_pct"),
        "meta": f"load: {load_s}   cores: {cores_s}",
    }


def _builtin_memory(snap: dict[str, Any]) -> dict[str, Any]:
    mem = snap.get("memory") or {}
    if not mem:
        return {"value": None, "meta": "used: ?"}
    meta = (
        f"used {_human_bytes(mem.get('used'))} / {_human_bytes(mem.get('total'))} "
        f"({float(mem.get('percent', 0)):.1f}%)"
        f"  ·  swap {_human_bytes(mem.get('swap_used'))} / {_human_bytes(mem.get('swap_total'))} "
        f"({float(mem.get('swap_percent', 0)):.1f}%)"
    )
    return {"value": mem.get("percent"), "meta": meta}


def _builtin_temp(snap: dict[str, Any]) -> dict[str, Any]:
    temp = snap.get("temp_c")
    if isinstance(temp, (int, float)):
        return {"value": float(temp), "meta": f"cur: {float(temp):.1f} °C"}
    return {"value": None, "meta": "cur: ?"}


def _builtin_network(snap: dict[str, Any]) -> dict[str, Any]:
    net = snap.get("net") or []
    nic = next((n for n in net if n.get("rx_bps") is not None or n.get("tx_bps") is not None), None)
    if not nic:
        return {"value": 0.0, "meta": "?  ↓0  ↑0"}
    rx_kb = float(nic.get("rx_bps") or 0) / 1024
    tx_kb = float(nic.get("tx_bps") or 0) / 1024
    total = round(rx_kb + tx_kb, 2)
    return {
        "value": total,
        "meta": f"{nic.get('nic', '?')}  ↓{rx_kb:.1f} KB/s  ↑{tx_kb:.1f} KB/s",
    }


def _builtin_disks(snap: dict[str, Any]) -> dict[str, Any]:
    return {"disks": snap.get("disks") or [], "meta": ""}


def _builtin_procs(snap: dict[str, Any]) -> dict[str, Any]:
    return {"top": snap.get("top") or [], "meta": ""}


_BUILTIN_HANDLERS = {
    "cpu": _builtin_cpu,
    "memory": _builtin_memory,
    "temp": _builtin_temp,
    "network": _builtin_network,
    "disks": _builtin_disks,
    "procs": _builtin_procs,
}


def extract_builtin(command: str, snap: dict[str, Any]) -> dict[str, Any]:
    handler = _BUILTIN_HANDLERS.get(command)
    if handler is None:
        raise ValueError(f"unknown builtin: {command}")
    return handler(snap)


def extract_shell_panel(panel: dict[str, Any]) -> dict[str, Any]:
    raw = run_shell_command(panel["command"])
    value = parse_shell_output(raw, panel.get("parse", PARSE_FLOAT), panel.get("parse_arg", ""))
    display = panel.get("display", DISPLAY_CHART)
    if display == DISPLAY_TEXT:
        text = value if isinstance(value, str) else (str(value) if value is not None else raw[:200])
        return {"text": text, "meta": text, "raw": raw[:500]}
    if isinstance(value, (int, float)):
        unit = panel.get("unit", "")
        suffix = f" {unit}" if unit else ""
        return {"value": float(value), "meta": f"cur: {float(value):.2f}{suffix}".rstrip(), "raw": raw[:500]}
    return {"value": None, "meta": "cur: ?", "raw": raw[:500]}


def extract_panel(panel: dict[str, Any], snap: dict[str, Any]) -> dict[str, Any]:
    try:
        if panel.get("extract") == EXTRACT_BUILTIN:
            return extract_builtin(panel["command"], snap)
        if panel.get("extract") == EXTRACT_SHELL:
            return extract_shell_panel(panel)
        raise ValueError(f"unknown extract method: {panel.get('extract')}")
    except Exception as exc:  # pylint: disable=broad-except
        return {"value": None, "meta": f"err: {exc}", "error": str(exc)}


def panel_snapshot(snap: dict[str, Any], panels: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {panel["id"]: extract_panel(panel, snap) for panel in panels}

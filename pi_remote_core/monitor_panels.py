"""Persisted monitor panel definitions."""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from . import config

EXTRACT_BUILTIN = "builtin"
EXTRACT_SHELL = "shell"
EXTRACT_METHODS = {EXTRACT_BUILTIN, EXTRACT_SHELL}

PARSE_FLOAT = "float"
PARSE_REGEX = "regex"
PARSE_TEXT = "text"
PARSE_METHODS = {PARSE_FLOAT, PARSE_REGEX, PARSE_TEXT}

DISPLAY_CHART = "chart"
DISPLAY_TEXT = "text"
DISPLAY_DISKS = "disks"
DISPLAY_TABLE = "table"
DISPLAY_TYPES = {DISPLAY_CHART, DISPLAY_TEXT, DISPLAY_DISKS, DISPLAY_TABLE}

BUILTIN_KEYS = {"cpu", "memory", "temp", "network", "disks", "procs"}

DEFAULT_PANELS: list[dict[str, Any]] = [
    {
        "id": "default-cpu",
        "label": "CPU 占用",
        "extract": EXTRACT_BUILTIN,
        "command": "cpu",
        "parse": PARSE_FLOAT,
        "parse_arg": "",
        "display": DISPLAY_CHART,
        "unit": "%",
        "color": "#059669",
        "wide": False,
    },
    {
        "id": "default-memory",
        "label": "内存",
        "extract": EXTRACT_BUILTIN,
        "command": "memory",
        "parse": PARSE_FLOAT,
        "parse_arg": "",
        "display": DISPLAY_CHART,
        "unit": "%",
        "color": "#2563eb",
        "wide": False,
    },
    {
        "id": "default-temp",
        "label": "温度 (°C)",
        "extract": EXTRACT_BUILTIN,
        "command": "temp",
        "parse": PARSE_FLOAT,
        "parse_arg": "",
        "display": DISPLAY_CHART,
        "unit": "°C",
        "color": "#d97706",
        "wide": False,
    },
    {
        "id": "default-network",
        "label": "网络吞吐 (KB/s)",
        "extract": EXTRACT_BUILTIN,
        "command": "network",
        "parse": PARSE_FLOAT,
        "parse_arg": "",
        "display": DISPLAY_CHART,
        "unit": "",
        "color": "#7c3aed",
        "wide": False,
    },
    {
        "id": "default-disks",
        "label": "磁盘",
        "extract": EXTRACT_BUILTIN,
        "command": "disks",
        "parse": PARSE_TEXT,
        "parse_arg": "",
        "display": DISPLAY_DISKS,
        "unit": "",
        "color": "",
        "wide": True,
    },
    {
        "id": "default-procs",
        "label": "Top 进程（按 CPU%）",
        "extract": EXTRACT_BUILTIN,
        "command": "procs",
        "parse": PARSE_TEXT,
        "parse_arg": "",
        "display": DISPLAY_TABLE,
        "unit": "",
        "color": "",
        "wide": True,
    },
]

MAX_PANELS = 32
MAX_LABEL_LEN = 40
MAX_COMMAND_LEN = 500
MAX_PARSE_ARG_LEN = 200
_MAX_UNIT_LEN = 12
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _panels_path() -> Path:
    return Path(config.DATA_DIR) / "monitor_panels.json"


def _read_store() -> dict[str, Any]:
    path = _panels_path()
    if not path.is_file():
        return {"panels": [dict(p) for p in DEFAULT_PANELS]}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"panels": [dict(p) for p in DEFAULT_PANELS]}
    if not isinstance(data, dict):
        return {"panels": [dict(p) for p in DEFAULT_PANELS]}
    return data


def _write_store(panels: list[dict[str, Any]]) -> None:
    path = _panels_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    payload = {"panels": panels}
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _normalize_panel(raw: dict[str, Any]) -> dict[str, Any]:
    label = str(raw.get("label", "")).strip()
    command = str(raw.get("command", "")).strip()
    if not label or not command:
        raise ValueError("label and command are required")
    if len(label) > MAX_LABEL_LEN:
        raise ValueError(f"label must be at most {MAX_LABEL_LEN} characters")
    if len(command) > MAX_COMMAND_LEN:
        raise ValueError(f"command must be at most {MAX_COMMAND_LEN} characters")

    extract = str(raw.get("extract", EXTRACT_SHELL)).strip()
    if extract not in EXTRACT_METHODS:
        raise ValueError(f"extract must be one of: {', '.join(sorted(EXTRACT_METHODS))}")

    parse = str(raw.get("parse", PARSE_FLOAT)).strip()
    if parse not in PARSE_METHODS:
        raise ValueError(f"parse must be one of: {', '.join(sorted(PARSE_METHODS))}")

    parse_arg = str(raw.get("parse_arg", "")).strip()
    if len(parse_arg) > MAX_PARSE_ARG_LEN:
        raise ValueError(f"parse_arg must be at most {MAX_PARSE_ARG_LEN} characters")

    display = str(raw.get("display", DISPLAY_CHART)).strip()
    if display not in DISPLAY_TYPES:
        raise ValueError(f"display must be one of: {', '.join(sorted(DISPLAY_TYPES))}")

    unit = str(raw.get("unit", "")).strip()
    if len(unit) > _MAX_UNIT_LEN:
        raise ValueError(f"unit must be at most {_MAX_UNIT_LEN} characters")

    color = str(raw.get("color", "")).strip()
    if color and not _COLOR_RE.fullmatch(color):
        raise ValueError("color must be a #RRGGBB hex value or empty")

    panel_id = str(raw.get("id") or "").strip() or str(uuid.uuid4())
    wide = bool(raw.get("wide", False))

    if extract == EXTRACT_BUILTIN:
        if command not in BUILTIN_KEYS:
            raise ValueError(f"builtin command must be one of: {', '.join(sorted(BUILTIN_KEYS))}")
        if command == "disks" and display != DISPLAY_DISKS:
            raise ValueError("builtin disks requires display=disks")
        if command == "procs" and display != DISPLAY_TABLE:
            raise ValueError("builtin procs requires display=table")
        if command in {"disks", "procs"} and display in {DISPLAY_CHART, DISPLAY_TEXT}:
            raise ValueError("disks/procs builtins cannot use chart/text display")
    else:
        if display in {DISPLAY_DISKS, DISPLAY_TABLE}:
            raise ValueError("shell panels only support chart or text display")
        if parse == PARSE_REGEX and not parse_arg:
            raise ValueError("parse_arg is required when parse=regex")

    return {
        "id": panel_id,
        "label": label,
        "extract": extract,
        "command": command,
        "parse": parse,
        "parse_arg": parse_arg,
        "display": display,
        "unit": unit,
        "color": color,
        "wide": wide,
    }


def _load_panels_from_store(data: dict[str, Any]) -> list[dict[str, Any]]:
    panels = data.get("panels")
    if not isinstance(panels, list) or not panels:
        return [dict(p) for p in DEFAULT_PANELS]
    out: list[dict[str, Any]] = []
    for item in panels:
        if not isinstance(item, dict):
            continue
        try:
            out.append(_normalize_panel(item))
        except ValueError:
            continue
    return out or [dict(p) for p in DEFAULT_PANELS]


def load_panels() -> list[dict[str, Any]]:
    return _load_panels_from_store(_read_store())


def save_panels(panels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(panels) > MAX_PANELS:
        raise ValueError(f"at most {MAX_PANELS} panels allowed")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in panels:
        if not isinstance(raw, dict):
            raise ValueError("each panel must be an object")
        panel = _normalize_panel(raw)
        if panel["id"] in seen:
            raise ValueError(f"duplicate panel id: {panel['id']}")
        seen.add(panel["id"])
        normalized.append(panel)
    _write_store(normalized)
    return normalized

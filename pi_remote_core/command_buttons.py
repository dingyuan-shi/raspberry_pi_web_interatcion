"""Persisted quick-command buttons for the web commands tab."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from . import config

DEFAULT_BUTTONS: list[dict[str, Any]] = [
    {"id": "default-status", "label": "status", "command": "status", "danger": False},
    {"id": "default-help", "label": "help", "command": "help", "danger": False},
    {"id": "default-ip", "label": "ip", "command": "ip", "danger": False},
    {"id": "default-uptime", "label": "uptime", "command": "uptime", "danger": False},
    {
        "id": "default-uname",
        "label": "uname -a",
        "command": "shell:uname -a",
        "danger": False,
    },
    {"id": "default-df", "label": "df -h", "command": "shell:df -h", "danger": False},
    {"id": "default-free", "label": "free -h", "command": "shell:free -h", "danger": False},
    {
        "id": "default-temp",
        "label": "measure_temp",
        "command": "shell:vcgencmd measure_temp",
        "danger": False,
    },
    {"id": "default-reboot", "label": "reboot", "command": "reboot", "danger": True},
    {"id": "default-shutdown", "label": "shutdown", "command": "shutdown", "danger": True},
]

MAX_BUTTONS = 64
MAX_LABEL_LEN = 40
MAX_COMMAND_LEN = 500


def _buttons_path() -> Path:
    return Path(config.DATA_DIR) / "command_buttons.json"


def _normalize_button(raw: dict[str, Any]) -> dict[str, Any]:
    label = str(raw.get("label", "")).strip()
    command = str(raw.get("command", "")).strip()
    if not label or not command:
        raise ValueError("label and command are required")
    if len(label) > MAX_LABEL_LEN:
        raise ValueError(f"label must be at most {MAX_LABEL_LEN} characters")
    if len(command) > MAX_COMMAND_LEN:
        raise ValueError(f"command must be at most {MAX_COMMAND_LEN} characters")
    btn_id = str(raw.get("id") or "").strip() or str(uuid.uuid4())
    danger = bool(raw.get("danger", False))
    return {"id": btn_id, "label": label, "command": command, "danger": danger}


def load_buttons() -> list[dict[str, Any]]:
    path = _buttons_path()
    if not path.is_file():
        return [dict(b) for b in DEFAULT_BUTTONS]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [dict(b) for b in DEFAULT_BUTTONS]
    buttons = data.get("buttons")
    if not isinstance(buttons, list) or not buttons:
        return [dict(b) for b in DEFAULT_BUTTONS]
    out: list[dict[str, Any]] = []
    for item in buttons:
        if not isinstance(item, dict):
            continue
        try:
            out.append(_normalize_button(item))
        except ValueError:
            continue
    return out or [dict(b) for b in DEFAULT_BUTTONS]


def save_buttons(buttons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(buttons) > MAX_BUTTONS:
        raise ValueError(f"at most {MAX_BUTTONS} buttons allowed")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in buttons:
        if not isinstance(raw, dict):
            raise ValueError("each button must be an object")
        btn = _normalize_button(raw)
        if btn["id"] in seen:
            raise ValueError(f"duplicate button id: {btn['id']}")
        seen.add(btn["id"])
        normalized.append(btn)
    path = _buttons_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    payload = {"buttons": normalized}
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return normalized

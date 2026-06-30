"""Persisted command templates, command instances, and recent launches."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from . import config

BUTTON_TYPE_TEMPLATE = "template"
BUTTON_TYPE_INSTANCE = "instance"
BUTTON_TYPES = {BUTTON_TYPE_TEMPLATE, BUTTON_TYPE_INSTANCE}

DEFAULT_BUTTONS: list[dict[str, Any]] = [
    {"id": "default-status", "type": BUTTON_TYPE_INSTANCE, "label": "status", "command": "status", "danger": False},
    {"id": "default-help", "type": BUTTON_TYPE_INSTANCE, "label": "help", "command": "help", "danger": False},
    {"id": "default-ip", "type": BUTTON_TYPE_INSTANCE, "label": "ip", "command": "ip", "danger": False},
    {"id": "default-uptime", "type": BUTTON_TYPE_INSTANCE, "label": "uptime", "command": "uptime", "danger": False},
    {
        "id": "default-uname",
        "type": BUTTON_TYPE_INSTANCE,
        "label": "uname -a",
        "command": "shell:uname -a",
        "danger": False,
    },
    {"id": "default-df", "type": BUTTON_TYPE_INSTANCE, "label": "df -h", "command": "shell:df -h", "danger": False},
    {"id": "default-free", "type": BUTTON_TYPE_INSTANCE, "label": "free -h", "command": "shell:free -h", "danger": False},
    {
        "id": "default-temp",
        "type": BUTTON_TYPE_INSTANCE,
        "label": "measure_temp",
        "command": "shell:vcgencmd measure_temp",
        "danger": False,
    },
    {"id": "default-reboot", "type": BUTTON_TYPE_INSTANCE, "label": "reboot", "command": "reboot", "danger": True},
    {"id": "default-shutdown", "type": BUTTON_TYPE_INSTANCE, "label": "shutdown", "command": "shutdown", "danger": True},
]

MAX_BUTTONS = 64
MAX_RECENT = 10
MAX_LABEL_LEN = 40
MAX_COMMAND_LEN = 500
MAX_PARAMS = 8
MAX_PARAM_NAME_LEN = 32
MAX_PARAM_LABEL_LEN = 40
MAX_PARAM_DEFAULT_LEN = 200
_PARAM_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _buttons_path() -> Path:
    return Path(config.DATA_DIR) / "command_buttons.json"


def _read_store() -> dict[str, Any]:
    path = _buttons_path()
    if not path.is_file():
        return {"buttons": [dict(b) for b in DEFAULT_BUTTONS], "recent": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"buttons": [dict(b) for b in DEFAULT_BUTTONS], "recent": []}
    if not isinstance(data, dict):
        return {"buttons": [dict(b) for b in DEFAULT_BUTTONS], "recent": []}
    return data


def _write_store(buttons: list[dict[str, Any]], recent: list[dict[str, Any]]) -> None:
    path = _buttons_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    payload = {"buttons": buttons, "recent": recent}
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _infer_type(raw: dict[str, Any]) -> str:
    explicit = str(raw.get("type", "")).strip()
    if explicit in BUTTON_TYPES:
        return explicit
    params = raw.get("params") or []
    command = str(raw.get("command", ""))
    if params or "${" in command:
        return BUTTON_TYPE_TEMPLATE
    return BUTTON_TYPE_INSTANCE


def _normalize_param(raw: dict[str, Any]) -> dict[str, str]:
    name = str(raw.get("name", "")).strip()
    if not name or not _PARAM_NAME_RE.fullmatch(name):
        raise ValueError(
            "param name must start with a letter and contain only letters, digits, underscore"
        )
    if len(name) > MAX_PARAM_NAME_LEN:
        raise ValueError(f"param name must be at most {MAX_PARAM_NAME_LEN} characters")
    label = str(raw.get("label", "")).strip() or name
    if len(label) > MAX_PARAM_LABEL_LEN:
        raise ValueError(f"param label must be at most {MAX_PARAM_LABEL_LEN} characters")
    default = str(raw.get("default", ""))
    if len(default) > MAX_PARAM_DEFAULT_LEN:
        raise ValueError(f"param default must be at most {MAX_PARAM_DEFAULT_LEN} characters")
    return {"name": name, "label": label, "default": default}


def _normalize_params(raw: Any) -> list[dict[str, str]]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise ValueError("params must be an array")
    if len(raw) > MAX_PARAMS:
        raise ValueError(f"at most {MAX_PARAMS} params per template")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("each param must be an object")
        param = _normalize_param(item)
        if param["name"] in seen:
            raise ValueError(f"duplicate param name: {param['name']}")
        seen.add(param["name"])
        out.append(param)
    return out


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
    btn_type = _infer_type(raw)
    params = _normalize_params(raw.get("params", [])) if btn_type == BUTTON_TYPE_TEMPLATE else []
    if btn_type == BUTTON_TYPE_INSTANCE and raw.get("params"):
        raise ValueError("instance commands cannot define params")
    return {
        "id": btn_id,
        "type": btn_type,
        "label": label,
        "command": command,
        "danger": danger,
        "params": params,
    }


def _normalize_recent(raw: dict[str, Any]) -> dict[str, Any]:
    command = str(raw.get("command", "")).strip()
    if not command:
        raise ValueError("recent command is required")
    if len(command) > MAX_COMMAND_LEN:
        raise ValueError(f"command must be at most {MAX_COMMAND_LEN} characters")
    entry_id = str(raw.get("id") or "").strip() or str(uuid.uuid4())
    template_id = str(raw.get("template_id") or "").strip() or None
    template_label = str(raw.get("template_label") or "").strip() or None
    ts = raw.get("ts")
    if not isinstance(ts, (int, float)):
        ts = time.time()
    return {
        "id": entry_id,
        "command": command,
        "template_id": template_id,
        "template_label": template_label,
        "ts": float(ts),
    }


def _load_buttons_from_store(data: dict[str, Any]) -> list[dict[str, Any]]:
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


def _load_recent_from_store(data: dict[str, Any]) -> list[dict[str, Any]]:
    recent = data.get("recent")
    if not isinstance(recent, list):
        return []
    out: list[dict[str, Any]] = []
    for item in recent:
        if not isinstance(item, dict):
            continue
        try:
            out.append(_normalize_recent(item))
        except ValueError:
            continue
    return out[:MAX_RECENT]


def load_state() -> dict[str, Any]:
    data = _read_store()
    return {
        "buttons": _load_buttons_from_store(data),
        "recent": _load_recent_from_store(data),
    }


def load_buttons() -> list[dict[str, Any]]:
    return load_state()["buttons"]


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
    recent = _load_recent_from_store(_read_store())
    _write_store(normalized, recent)
    return normalized


def add_recent(entry: dict[str, Any]) -> list[dict[str, Any]]:
    normalized = _normalize_recent(entry)
    data = _read_store()
    buttons = _load_buttons_from_store(data)
    recent = _load_recent_from_store(data)
    recent = [r for r in recent if r["command"] != normalized["command"]]
    recent.insert(0, normalized)
    recent = recent[:MAX_RECENT]
    _write_store(buttons, recent)
    return recent


def promote_recent(recent_id: str, label: str | None = None) -> dict[str, Any]:
    data = _read_store()
    buttons = _load_buttons_from_store(data)
    recent = _load_recent_from_store(data)
    match = next((r for r in recent if r["id"] == recent_id), None)
    if match is None:
        raise ValueError("recent entry not found")
    btn_label = (label or match["template_label"] or match["command"][:MAX_LABEL_LEN]).strip()
    if len(btn_label) > MAX_LABEL_LEN:
        btn_label = btn_label[:MAX_LABEL_LEN]
    new_btn = _normalize_button(
        {
            "id": str(uuid.uuid4()),
            "type": BUTTON_TYPE_INSTANCE,
            "label": btn_label,
            "command": match["command"],
            "danger": False,
            "params": [],
        }
    )
    buttons.append(new_btn)
    if len(buttons) > MAX_BUTTONS:
        raise ValueError(f"at most {MAX_BUTTONS} buttons allowed")
    _write_store(buttons, recent)
    return {"buttons": buttons, "recent": recent, "created": new_btn}

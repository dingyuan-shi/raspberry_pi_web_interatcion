"""Textual command dispatcher shared by every transport.

Commands are received as UTF-8 strings.  Each :class:`CommandHandler`
instance carries its own session state (currently only whether the
``shell:`` channel has been unlocked via ``auth:<token>``), so callers
should keep one handler per *logical* connection (e.g. one WebSocket
session).

Supported syntax::

    help                            list available commands
    status                          one-shot system snapshot
    ip                              primary IPv4 address
    uptime                          uptime since boot
    reboot                          reboot the host (sudo)
    shutdown                        power off the host (sudo)
    gpio:<pin>:on|off|toggle|read   drive / read a GPIO pin
    auth:<token>                    unlock the shell channel for this session
    shell:<command>                 execute an arbitrary shell command
"""

from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass

from . import config, system_info

try:
    from gpiozero import LED
    from gpiozero.exc import BadPinFactory
except ImportError:  # pragma: no cover - optional dep
    LED = None  # type: ignore[assignment]
    BadPinFactory = Exception  # type: ignore[assignment]


HELP_TEXT = (
    "cmds: help|status|ip|uptime|reboot|shutdown|"
    "gpio:<pin>:on|off|toggle|read|auth:<token>|shell:<cmd>"
)


@dataclass
class Session:
    """Per-connection state held by the command handler."""

    shell_authenticated: bool = False


class CommandHandler:
    """Execute textual commands.

    Parameters
    ----------
    pre_authenticated:
        If ``True``, ``shell:<cmd>`` works without an explicit
        ``auth:<token>`` first.  Set this for transports that already
        carry their own authentication (e.g. an authenticated web
        session).
    """

    def __init__(self, pre_authenticated: bool = False) -> None:
        self._pre_authed = pre_authenticated
        self._session = Session(shell_authenticated=pre_authenticated)
        self._gpio_cache: dict[int, "LED"] = {}

    def reset_session(self) -> None:
        """Drop session state (called on disconnect)."""
        self._session = Session(shell_authenticated=self._pre_authed)
        for led in self._gpio_cache.values():
            try:
                led.close()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
        self._gpio_cache.clear()

    async def handle(self, payload: bytes | str) -> str:
        if isinstance(payload, bytes):
            text = payload.decode("utf-8", errors="replace").strip()
        else:
            text = payload.strip()
        if not text:
            return "ERR empty command"

        lower = text.lower()
        try:
            if lower in {"help", "?"}:
                return HELP_TEXT
            if lower == "status":
                return system_info.snapshot_text()
            if lower == "ip":
                return system_info.primary_ip()
            if lower == "uptime":
                return system_info.format_uptime(system_info.uptime_seconds())
            if lower == "reboot":
                return await _run(["sudo", "-n", "/sbin/reboot"])
            if lower == "shutdown":
                return await _run(["sudo", "-n", "/sbin/poweroff"])
            if lower.startswith("auth:"):
                return self._auth(text[5:])
            if lower.startswith("gpio:"):
                return self._gpio(text[5:])
            if lower.startswith("shell:"):
                return await self._shell(text[6:])
        except Exception as exc:  # pylint: disable=broad-except
            return f"ERR {exc.__class__.__name__}: {exc}"

        return f"ERR unknown command: {text!r}"

    def _auth(self, token: str) -> str:
        if not config.ENABLE_SHELL:
            return "ERR shell disabled by config"
        if token == config.SHELL_AUTH_TOKEN:
            self._session.shell_authenticated = True
            return "OK shell unlocked"
        return "ERR bad token"

    async def _shell(self, raw_command: str) -> str:
        if not config.ENABLE_SHELL:
            return "ERR shell disabled by config"
        if not self._session.shell_authenticated:
            return "ERR auth required: send 'auth:<token>' first"
        proc = await asyncio.create_subprocess_shell(
            raw_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=config.SHELL_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            proc.kill()
            return "ERR shell timeout"
        output = stdout.decode("utf-8", errors="replace").rstrip()
        return output or f"OK rc={proc.returncode}"

    def _gpio(self, spec: str) -> str:
        parts = spec.split(":")
        if len(parts) != 2:
            return "ERR gpio syntax: gpio:<pin>:on|off|toggle|read"
        try:
            pin = int(parts[0])
        except ValueError:
            return "ERR gpio pin must be int"
        action = parts[1].lower()
        if pin not in config.GPIO_ALLOWED_PINS:
            return f"ERR pin {pin} not allowed"
        if LED is None:
            return "ERR gpiozero not installed"

        try:
            led = self._gpio_cache.get(pin)
            if led is None:
                led = LED(pin)
                self._gpio_cache[pin] = led
            if action == "on":
                led.on()
                return f"OK gpio{pin}=1"
            if action == "off":
                led.off()
                return f"OK gpio{pin}=0"
            if action == "toggle":
                led.toggle()
                return f"OK gpio{pin}={int(led.is_lit)}"
            if action == "read":
                return f"OK gpio{pin}={int(led.is_lit)}"
            return "ERR action must be on|off|toggle|read"
        except BadPinFactory:
            return "ERR no GPIO backend available (RPi.GPIO/lgpio missing)"


async def _run(cmd: list[str]) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode("utf-8", errors="replace").rstrip()
    if proc.returncode == 0:
        return output or f"OK {shlex.join(cmd)}"
    return f"ERR rc={proc.returncode} {output}"

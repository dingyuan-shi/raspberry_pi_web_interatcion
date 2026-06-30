"""Interactive PTY bridge for the /api/shell WebSocket.

Spawns a login-ish shell inside a pseudo-terminal and shuttles bytes
between the PTY master fd and an asyncio queue/WebSocket.
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import pty
import shlex
import signal
import struct
import termios
from typing import Awaitable, Callable

log = logging.getLogger(__name__)


class PtyProcess:
    """Owns the PTY master fd plus the forked child shell."""

    def __init__(self, command: list[str] | None = None, *, cols: int = 80, rows: int = 24):
        self.command = command or [os.environ.get("SHELL", "/bin/bash"), "-il"]
        self.cols = cols
        self.rows = rows
        self.pid = -1
        self.fd = -1

    def start(self) -> None:
        pid, fd = pty.fork()
        if pid == 0:  # child
            env = os.environ.copy()
            env.setdefault("TERM", "xterm-256color")
            os.execvpe(self.command[0], self.command, env)
        self.pid = pid
        self.fd = fd
        self.resize(self.cols, self.rows)
        # Non-blocking reads from the master end.
        flags = fcntl.fcntl(self.fd, fcntl.F_GETFL)
        fcntl.fcntl(self.fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def resize(self, cols: int, rows: int) -> None:
        if self.fd < 0:
            return
        self.cols, self.rows = cols, rows
        size = struct.pack("HHHH", rows, cols, 0, 0)
        try:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, size)
        except OSError:  # pragma: no cover
            pass

    def write(self, data: bytes) -> None:
        if self.fd >= 0:
            os.write(self.fd, data)

    def close(self) -> None:
        if self.fd >= 0:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = -1
        if self.pid > 0:
            try:
                os.kill(self.pid, signal.SIGHUP)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                pass
            self.pid = -1


async def pump_pty_to_callback(
    pty_proc: PtyProcess,
    on_data: Callable[[bytes], Awaitable[None]],
    chunk_size: int = 4096,
) -> None:
    """Read from the PTY master and forward bytes to ``on_data``.

    Terminates when the PTY is closed or the child exits (OSError on read).
    """
    loop = asyncio.get_running_loop()
    while pty_proc.fd >= 0:
        try:
            data = await loop.run_in_executor(None, _read_nonblocking, pty_proc.fd, chunk_size)
        except OSError:
            break
        if not data:
            await asyncio.sleep(0.02)
            continue
        await on_data(data)
    log.debug("PTY reader exited for pid=%s", pty_proc.pid)


def _read_nonblocking(fd: int, n: int) -> bytes:
    try:
        return os.read(fd, n)
    except BlockingIOError:
        return b""

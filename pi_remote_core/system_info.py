"""Lightweight helpers to read system metrics on a Raspberry Pi."""

from __future__ import annotations

import socket
import subprocess
import time
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover - psutil is a runtime dep
    psutil = None  # type: ignore[assignment]


# --------------------------------------------------------------------------- #
# Basic snapshot (used by /api/status and the SSE stream)
# --------------------------------------------------------------------------- #


def cpu_temperature_c() -> float | None:
    """Return CPU temperature in degrees Celsius, or None when unavailable."""
    thermal = Path("/sys/class/thermal/thermal_zone0/temp")
    if thermal.exists():
        try:
            return int(thermal.read_text().strip()) / 1000.0
        except ValueError:
            return None
    try:
        out = subprocess.check_output(["vcgencmd", "measure_temp"], text=True, timeout=2)
        # Example: "temp=46.7'C"
        return float(out.strip().split("=")[1].split("'")[0])
    except (FileNotFoundError, subprocess.SubprocessError, IndexError, ValueError):
        return None


def primary_ip() -> str:
    """Best-effort IPv4 address of the default route interface."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "0.0.0.0"
    finally:
        sock.close()


def uptime_seconds() -> float:
    try:
        with open("/proc/uptime", "r", encoding="ascii") as fh:
            return float(fh.read().split()[0])
    except OSError:
        return 0.0


def format_uptime(seconds: float) -> str:
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d{hours:02d}h{minutes:02d}m"
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    return f"{minutes}m{secs:02d}s"


def snapshot() -> dict[str, object]:
    """Compact dict for the status pills + SSE stream."""
    cpu = mem = None
    if psutil is not None:
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
    return {
        "ip": primary_ip(),
        "host": socket.gethostname(),
        "cpu_pct": cpu,
        "mem_pct": mem,
        "temp_c": cpu_temperature_c(),
        "uptime": format_uptime(uptime_seconds()),
    }


def snapshot_text() -> str:
    info = snapshot()
    parts = [
        f"host={info['host']}",
        f"ip={info['ip']}",
        f"cpu={info['cpu_pct']}%" if info["cpu_pct"] is not None else "cpu=?",
        f"mem={info['mem_pct']}%" if info["mem_pct"] is not None else "mem=?",
        f"temp={info['temp_c']:.1f}C" if isinstance(info["temp_c"], float) else "temp=?",
        f"up={info['uptime']}",
    ]
    return " ".join(parts)


# --------------------------------------------------------------------------- #
# Richer monitor data (used by /api/monitor)
# --------------------------------------------------------------------------- #


# Cache the previous network IO sample so we can compute throughput per second.
_LAST_NET: dict[str, tuple[float, int, int]] = {}


def disk_usage() -> list[dict[str, object]]:
    """Return usage for each real filesystem (skips tmpfs/devtmpfs/snap loops)."""
    if psutil is None:
        return []
    out: list[dict[str, object]] = []
    seen: set[str] = set()
    for part in psutil.disk_partitions(all=False):
        if part.fstype in {"", "squashfs", "tmpfs", "devtmpfs", "overlay", "aufs"}:
            continue
        if part.mountpoint in seen:
            continue
        seen.add(part.mountpoint)
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        out.append(
            {
                "mount": part.mountpoint,
                "fstype": part.fstype,
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": usage.percent,
            }
        )
    return out


def network_io() -> list[dict[str, object]]:
    """Per-interface bytes/sec since last call. Loopback skipped."""
    if psutil is None:
        return []
    now = time.monotonic()
    out: list[dict[str, object]] = []
    counters = psutil.net_io_counters(pernic=True)
    for nic, c in counters.items():
        if nic == "lo":
            continue
        rx_bps = tx_bps = None
        last = _LAST_NET.get(nic)
        if last is not None:
            dt = now - last[0]
            if dt > 0:
                rx_bps = max(0.0, (c.bytes_recv - last[1]) / dt)
                tx_bps = max(0.0, (c.bytes_sent - last[2]) / dt)
        _LAST_NET[nic] = (now, c.bytes_recv, c.bytes_sent)
        out.append(
            {
                "nic": nic,
                "bytes_recv": c.bytes_recv,
                "bytes_sent": c.bytes_sent,
                "rx_bps": rx_bps,
                "tx_bps": tx_bps,
            }
        )
    return out


def top_processes(n: int = 8) -> list[dict[str, object]]:
    """Return the top-N processes ordered by CPU%."""
    if psutil is None:
        return []
    procs = []
    for p in psutil.process_iter(["pid", "name", "username", "cpu_percent", "memory_percent"]):
        try:
            info = p.info
            procs.append(
                {
                    "pid": info["pid"],
                    "name": info["name"] or "?",
                    "user": info["username"] or "?",
                    "cpu_pct": info["cpu_percent"] or 0.0,
                    "mem_pct": round(info["memory_percent"] or 0.0, 1),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    procs.sort(key=lambda r: (-(r["cpu_pct"] or 0.0), -(r["mem_pct"] or 0.0)))
    return procs[:n]


def load_average() -> tuple[float, float, float] | None:
    try:
        return tuple(__import__("os").getloadavg())  # type: ignore[return-value]
    except (OSError, AttributeError):
        return None


def memory_breakdown() -> dict[str, object] | None:
    if psutil is None:
        return None
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    return {
        "total": vm.total,
        "available": vm.available,
        "used": vm.used,
        "percent": vm.percent,
        "swap_total": sw.total,
        "swap_used": sw.used,
        "swap_percent": sw.percent,
    }


def cpu_per_core() -> list[float]:
    if psutil is None:
        return []
    return psutil.cpu_percent(interval=None, percpu=True)


def monitor_snapshot() -> dict[str, object]:
    """Aggregate snapshot used by /api/monitor and its SSE stream."""
    base = snapshot()
    load = load_average()
    return {
        **base,
        "ts": time.time(),
        "load": list(load) if load else None,
        "cpu_per_core": cpu_per_core(),
        "memory": memory_breakdown(),
        "disks": disk_usage(),
        "net": network_io(),
        "top": top_processes(),
    }

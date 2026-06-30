"""Server-side screenshot of the e-ink dashboard for Kindle clients.

Headless Chromium screenshots ``/_render/lite`` for ``/api/cheap.png``.
Users open ``/cheap`` on Kindle; ``/lite`` is the live SVG page.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 5.0
RENDER_TIMEOUT_SECONDS = 20.0
DEFAULT_WIDTH = 1236
DEFAULT_HEIGHT = 1648

_chrome_lock = asyncio.Lock()
_cache: dict[tuple[int, int, str], tuple[float, bytes]] = {}


def find_chromium() -> Optional[str]:
    """Return the path to a usable Chromium-like binary, or None."""
    for name in (
        "chromium-browser",
        "chromium",
        "google-chrome-stable",
        "google-chrome",
        "chrome",
    ):
        path = shutil.which(name)
        if path:
            return path
    # Some Raspberry Pi OS installs put it under /usr/lib/chromium-browser/.
    for candidate in (
        "/usr/lib/chromium-browser/chromium-browser",
        "/usr/lib/chromium/chromium",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


async def render_screenshot(
    target_url: str,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> bytes:
    """Render ``target_url`` to a PNG via headless Chromium.

    Results are cached for :data:`CACHE_TTL_SECONDS` and concurrent calls
    serialise on a single lock so we never have two Chromium processes
    competing for memory on a Raspberry Pi.

    Raises :class:`RuntimeError` if Chromium is not installed or the
    render times out.
    """
    cache_key = (width, height, target_url)
    now = time.monotonic()
    cached = _cache.get(cache_key)
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    chromium = find_chromium()
    if not chromium:
        raise RuntimeError(
            "no chromium binary found; install chromium-browser "
            "(or google-chrome) to enable /api/cheap.png"
        )

    async with _chrome_lock:
        # Re-check inside the lock: a concurrent request may have just
        # populated the cache while we were waiting.
        now = time.monotonic()
        cached = _cache.get(cache_key)
        if cached and now - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]

        png = await _run_chromium(chromium, target_url, width, height)
        _cache[cache_key] = (time.monotonic(), png)
        return png


async def _run_chromium(
    chromium: str,
    url: str,
    width: int,
    height: int,
) -> bytes:
    """Try the modern headless mode first, fall back to legacy.

    * Chrome >= 109 only honours ``--headless=new`` (plain ``--headless`` hangs).
    * Older Chromium (e.g. Raspbian Buster's v74) only knows ``--headless``
      and treats ``--headless=new`` as an unknown switch.
    """
    log.info("rendering kindle screenshot: %s (%dx%d)", url, width, height)
    last_err: Optional[str] = None
    for headless_flag in ("--headless=new", "--headless"):
        png, err = await _attempt(chromium, headless_flag, url, width, height)
        if png is not None:
            return png
        last_err = err
        log.info("chromium %s attempt failed: %s", headless_flag, err)
    raise RuntimeError(last_err or "chromium failed to produce a screenshot")


async def _attempt(
    chromium: str,
    headless_flag: str,
    url: str,
    width: int,
    height: int,
) -> tuple[Optional[bytes], Optional[str]]:
    tmpdir = tempfile.mkdtemp(prefix="pi-remote-kindle-")
    try:
        out_path = Path(tmpdir) / "shot.png"
        profile_dir = Path(tmpdir) / "profile"
        args = [
            chromium,
            headless_flag,
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            "--mute-audio",
            "--disable-features=DialMediaRouteProvider",
            "--force-device-scale-factor=1",
            "--default-background-color=FFFFFFFF",
            f"--user-data-dir={profile_dir}",
            f"--window-size={width},{height}",
            "--virtual-time-budget=2000",
            f"--screenshot={out_path}",
            url,
        ]
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=RENDER_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return None, f"timed out after {RENDER_TIMEOUT_SECONDS:.0f}s"

        if not out_path.exists():
            tail = (stderr or b"").decode("utf-8", errors="replace")
            return None, f"rc={proc.returncode}; tail={tail[-300:]!r}"
        return out_path.read_bytes(), None
    finally:
        # Chromium tends to leave a non-empty profile directory behind even
        # after exiting, which makes TemporaryDirectory.cleanup() raise.
        # rmtree(ignore_errors=True) silently drops whatever's left.
        shutil.rmtree(tmpdir, ignore_errors=True)

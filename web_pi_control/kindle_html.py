"""Server-rendered lite dashboard (HTML + SVG).

``/lite`` serves this page live in the browser (sharp SVG lines on PC).
``/cheap`` shows a PNG screenshot of the same page (``/_render/lite``) for
Kindle — edit this file only; both routes stay in sync automatically.
"""

from __future__ import annotations

import html
from typing import Any, Iterable, Optional, Sequence

DESIGN_WIDTH = 600
DESIGN_HEIGHT = 1000


def _esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def human_bytes(n: Optional[float]) -> str:
    if n is None:
        return "?"
    n = float(n)
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    return f"{n:.1f} {units[i]}" if n < 10 else f"{n:.0f} {units[i]}"


def sparkline_svg(
    values: Sequence[Optional[float]],
    *,
    width: int = 520,
    height: int = 140,
    stroke: str = "#111111",
    fill: str = "#cccccc",
    unit: str = "",
) -> str:
    """Inline SVG area/line chart."""
    nums = [float(v) for v in values if v is not None]
    if len(nums) < 2:
        label = f"{nums[0]:.1f}{unit}" if nums else "—"
        return (
            f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'xmlns="http://www.w3.org/2000/svg" role="img">'
            f'<text x="{width//2}" y="{height//2}" text-anchor="middle" '
            f'font-size="14" fill="#666">{_esc(label)}</text></svg>'
        )

    pad = 4
    inner_w = width - 2 * pad
    inner_h = height - 2 * pad
    vmin = min(nums)
    vmax = max(nums)
    if vmax == vmin:
        vmax = vmin + 1.0

    pts: list[tuple[float, float]] = []
    for i, v in enumerate(nums):
        x = pad + i * inner_w / (len(nums) - 1)
        y = pad + (1.0 - (v - vmin) / (vmax - vmin)) * inner_h
        pts.append((x, y))

    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = (
        f"M{pad:.1f},{height - pad:.1f} "
        + " ".join(f"L{x:.1f},{y:.1f}" for x, y in pts)
        + f" L{width - pad:.1f},{height - pad:.1f} Z"
    )

    y_max = f"{vmax:.0f}{unit}"
    y_min = f"{vmin:.0f}{unit}"

    return f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}"
 xmlns="http://www.w3.org/2000/svg" role="img" aria-label="chart">
  <rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>
  <line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height-pad}" stroke="#111" stroke-width="1"/>
  <line x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{height-pad}" stroke="#111" stroke-width="1"/>
  <text x="{pad+2}" y="{pad+12}" font-size="11" fill="#666">{_esc(y_max)}</text>
  <text x="{pad+2}" y="{height-pad-4}" font-size="11" fill="#666">{_esc(y_min)}</text>
  <path d="{area}" fill="{fill}" stroke="none"/>
  <polyline points="{line}" fill="none" stroke="{stroke}" stroke-width="2"
    stroke-linejoin="round" stroke-linecap="round"/>
</svg>"""


def _history_series(history: list[dict], key: str, nested: Optional[str] = None) -> list[Optional[float]]:
    out: list[Optional[float]] = []
    for row in history:
        if nested:
            block = row.get(nested) or {}
            out.append(block.get(key) if isinstance(block, dict) else None)
        else:
            out.append(row.get(key))
    return out


def _net_series(history: list[dict]) -> list[Optional[float]]:
    out: list[Optional[float]] = []
    for row in history:
        nets = row.get("net") or []
        total = 0.0
        found = False
        for nic in nets:
            if not isinstance(nic, dict):
                continue
            rx = nic.get("rx_bps")
            tx = nic.get("tx_bps")
            if rx is not None or tx is not None:
                total += (rx or 0) + (tx or 0)
                found = True
        out.append(total / 1024.0 if found else None)
    return out


def _dashboard_body(
    snap: dict[str, Any],
    hist: list[dict[str, Any]],
) -> tuple[str, ...]:
    cpu_hist = _history_series(hist, "cpu_pct")
    mem_hist = _history_series(hist, "percent", nested="memory")
    temp_hist = _history_series(hist, "temp_c")
    net_hist = _net_series(hist)

    host = _esc(snap.get("host", "?"))
    ip = _esc(snap.get("ip", "?"))
    cpu = snap.get("cpu_pct")
    mem = snap.get("mem_pct")
    temp = snap.get("temp_c")
    uptime = _esc(snap.get("uptime", "?"))

    cpu_pill = f"cpu={cpu:.1f}%" if isinstance(cpu, (int, float)) else "cpu=?"
    mem_pill = f"mem={mem:.1f}%" if isinstance(mem, (int, float)) else "mem=?"
    temp_pill = f"temp={temp:.1f}C" if isinstance(temp, (int, float)) else "temp=?"

    load = snap.get("load")
    load_txt = " / ".join(f"{x:.2f}" for x in load) if load else "?"
    cores = snap.get("cpu_per_core") or []
    cores_txt = " ".join(f"{c:.0f}%" for c in cores) if cores else "?"

    memory = snap.get("memory") or {}
    mem_meta = (
        f"used {human_bytes(memory.get('used'))} / {human_bytes(memory.get('total'))}"
        f" ({memory.get('percent', 0):.1f}%)"
        f" · swap {human_bytes(memory.get('swap_used'))}"
        f" / {human_bytes(memory.get('swap_total'))}"
        f" ({memory.get('swap_percent', 0):.1f}%)"
    )

    temp_meta = f"cur: {temp:.1f} °C" if isinstance(temp, (int, float)) else "cur: ?"

    nic = next((n for n in (snap.get("net") or []) if n.get("rx_bps") is not None), None)
    if nic:
        rx = (nic.get("rx_bps") or 0) / 1024
        tx = (nic.get("tx_bps") or 0) / 1024
        net_meta = f"{_esc(nic.get('nic', '?'))}  ↓{rx:.1f} KB/s  ↑{tx:.1f} KB/s"
    else:
        net_meta = "↓0  ↑0"

    disks_html = _render_disks(snap.get("disks") or [])
    procs_html = _render_procs(snap.get("top") or [])

    return (
        host,
        ip,
        _esc(cpu_pill),
        _esc(mem_pill),
        _esc(temp_pill),
        uptime,
        _esc(load_txt),
        _esc(cores_txt),
        _esc(mem_meta),
        _esc(temp_meta),
        net_meta,
        sparkline_svg(cpu_hist, stroke="#111", fill="#ddd", unit="%"),
        sparkline_svg(mem_hist, stroke="#111", fill="#ddd", unit="%"),
        sparkline_svg(temp_hist, stroke="#111", fill="#ddd", unit=""),
        sparkline_svg(net_hist, stroke="#111", fill="#ddd", unit=""),
        disks_html,
        procs_html,
    )


def render_dashboard_html(
    snap: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    width: int = DESIGN_WIDTH,
    height: int = DESIGN_HEIGHT,
    fit_viewport: bool = False,
) -> str:
    """Lite dashboard HTML.

    ``fit_viewport=False`` — natural layout for ``/lite`` in a desktop browser.
    ``fit_viewport=True`` — scaled to ``width``×``height`` for PNG capture.
    """
    width = max(200, min(int(width), 2000))
    height = max(200, min(int(height), 3000))
    hist = list(history)
    if not hist or hist[-1] is not snap:
        hist.append(snap)

    parts = _dashboard_body(snap, hist)
    (
        host,
        ip,
        cpu_pill,
        mem_pill,
        temp_pill,
        uptime,
        load_txt,
        cores_txt,
        mem_meta,
        temp_meta,
        net_meta,
        cpu_chart,
        mem_chart,
        temp_chart,
        net_chart,
        disks_html,
        procs_html,
    ) = parts

    grid = f"""
    <div class="card">
      <h2>CPU 占用</h2>
      {cpu_chart}
      <div class="meta">load: {load_txt} &nbsp; cores: {cores_txt}</div>
    </div>
    <div class="card">
      <h2>内存</h2>
      {mem_chart}
      <div class="meta">{mem_meta}</div>
    </div>
    <div class="card">
      <h2>温度 (°C)</h2>
      {temp_chart}
      <div class="meta">{temp_meta}</div>
    </div>
    <div class="card">
      <h2>网络吞吐 (KB/s)</h2>
      {net_chart}
      <div class="meta">{net_meta}</div>
    </div>
    <div class="card wide">
      <h2>磁盘</h2>
      {disks_html}
    </div>
    <div class="card wide">
      <h2>Top 进程（按 CPU%）</h2>
      <table>
        <thead><tr><th>PID</th><th>用户</th><th>命令</th><th>CPU%</th><th>MEM%</th></tr></thead>
        <tbody>{procs_html}</tbody>
      </table>
    </div>"""

    header = f"""
<header>
  <h1>Pi Remote Control</h1>
  <div class="pills">
    <span class="pill">host={host}</span>
    <span class="pill">ip={ip}</span>
    <span class="pill">{cpu_pill}</span>
    <span class="pill">{mem_pill}</span>
    <span class="pill">{temp_pill}</span>
    <span class="pill">up={uptime}</span>
  </div>
</header>
<main><div class="grid">{grid}</div></main>"""

    base_css = """
*{{box-sizing:border-box;margin:0;padding:0}}
#page{{width:{design_w}px;background:#fff}}
header{{padding:12px 16px;border-bottom:2px solid #111}}
h1{{font-size:20px;font-weight:700;margin-bottom:8px}}
.pills{{display:flex;flex-wrap:wrap;gap:6px}}
.pill{{border:1px solid #111;border-radius:999px;padding:3px 10px;font-size:12px;font-family:monospace;background:#fff}}
main{{padding:12px 16px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
.card{{border:1px solid #111;border-radius:4px;padding:10px 12px;background:#fff}}
.card h2{{font-size:15px;font-weight:700;border-bottom:1px solid #111;padding-bottom:4px;margin-bottom:8px}}
.card.wide{{grid-column:span 2}}
.meta{{font-size:12px;font-family:monospace;color:#333;margin-top:6px;border-top:1px solid #ddd;padding-top:6px}}
svg{{display:block;width:100%;height:auto}}
.disk{{margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid #ddd}}
.disk:last-child{{border-bottom:0;padding-bottom:0;margin-bottom:0}}
.disk .row{{display:flex;justify-content:space-between;font-size:12px;font-family:monospace}}
.bar{{height:8px;background:#eee;border:1px solid #111;margin-top:4px}}
.bar i{{display:block;height:100%;background:#111}}
table{{width:100%;border-collapse:collapse;font-size:12px;font-family:monospace;border:1px solid #111}}
th,td{{border-bottom:1px solid #111;padding:4px 6px;text-align:left}}
thead th{{border-bottom:2px solid #111;background:#f5f5f5}}
tbody tr:last-child td{{border-bottom:0}}
th{{color:#111;font-weight:700}}
td:nth-child(4),td:nth-child(5),th:nth-child(4),th:nth-child(5){{text-align:right}}
""".format(design_w=DESIGN_WIDTH)

    if fit_viewport:
        scale = min(width / DESIGN_WIDTH, height / DESIGN_HEIGHT)
        shell_css = (
            f"html,body{{width:{width}px;height:{height}px;overflow:hidden;background:#fff}}\n"
            f"body{{display:flex;justify-content:center;align-items:flex-start;"
            f"color:#111;font-family:Georgia,\"Times New Roman\",serif;font-size:15px;line-height:1.4}}\n"
            f"#page{{transform:scale({scale:.6f});transform-origin:top center}}\n"
        )
        viewport = f'width={width},height={height},user-scalable=no'
    else:
        shell_css = (
            "html,body{background:#fff;margin:0;padding:0}\n"
            "body{display:flex;justify-content:center;align-items:flex-start;"
            'color:#111;font-family:Georgia,"Times New Roman",serif;font-size:15px;line-height:1.4}\n'
            "body{padding:16px 0}\n"
        )
        viewport = "width=device-width,initial-scale=1"

    body = f"<body>\n<div id=\"page\">{header}</div>\n</body>"

    return f"""<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="{viewport}">
<title>Pi Remote</title>
<style>
{shell_css}
{base_css}
</style>
</head>{body}</html>"""


def _render_disks(disks: Iterable[dict]) -> str:
    rows = list(disks)
    if not rows:
        return '<p class="meta">无可读分区</p>'
    parts: list[str] = []
    for d in rows:
        mount = _esc(d.get("mount", "?"))
        fstype = _esc(d.get("fstype", ""))
        pct = float(d.get("percent") or 0)
        parts.append(
            f'<div class="disk"><div class="row">'
            f'<span>{mount} ({fstype})</span>'
            f'<span>{human_bytes(d.get("used"))} / {human_bytes(d.get("total"))} · {pct:.1f}%</span>'
            f'</div><div class="bar"><i style="width:{pct:.1f}%"></i></div></div>'
        )
    return "\n".join(parts)


def _render_procs(top: Iterable[dict]) -> str:
    rows = list(top)
    if not rows:
        return '<tr><td colspan="5">无数据</td></tr>'
    return "\n".join(
        f"<tr><td>{_esc(p.get('pid'))}</td><td>{_esc(p.get('user'))}</td>"
        f"<td>{_esc(p.get('name'))}</td>"
        f"<td>{float(p.get('cpu_pct') or 0):.1f}</td>"
        f"<td>{float(p.get('mem_pct') or 0):.1f}</td></tr>"
        for p in rows
    )


def wrap_with_refresh(html: str, refresh: int) -> str:
    refresh = max(10, min(int(refresh), 3600))
    tag = f'<meta http-equiv="refresh" content="{refresh}">'
    if "<head>" in html:
        return html.replace("<head>", f"<head>\n{tag}", 1)
    return tag + html

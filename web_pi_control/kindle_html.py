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


def _panel_history_series(hist: list[dict[str, Any]], panel_id: str) -> list[Optional[float]]:
    out: list[Optional[float]] = []
    for row in hist:
        pdata = (row.get("panels") or {}).get(panel_id) or {}
        value = pdata.get("value")
        if isinstance(value, (int, float)):
            out.append(float(value))
        else:
            out.append(None)
    return out


def _stroke_fill(color: str) -> tuple[str, str]:
    stroke = color if color else "#111111"
    if stroke.startswith("#") and len(stroke) == 7:
        fill = stroke + "33"
    else:
        fill = "#dddddd"
    return stroke, fill


def _render_panel_card(
    panel: dict[str, Any],
    pdata: dict[str, Any],
    hist: list[dict[str, Any]],
) -> str:
    label = _esc(panel.get("label", "?"))
    wide = " wide" if panel.get("wide") else ""
    display = panel.get("display", "chart")
    panel_id = panel["id"]

    if display == "chart":
        series = _panel_history_series(hist, panel_id)
        stroke, fill = _stroke_fill(str(panel.get("color") or ""))
        chart = sparkline_svg(
            series,
            stroke=stroke,
            fill=fill,
            unit=str(panel.get("unit") or ""),
        )
        meta = _esc(pdata.get("meta") or "—")
        return (
            f'<div class="card{wide}"><h2>{label}</h2>{chart}'
            f'<div class="meta">{meta}</div></div>'
        )

    if display == "text":
        text = pdata.get("text") or pdata.get("meta") or "—"
        return (
            f'<div class="card{wide}"><h2>{label}</h2>'
            f'<div class="textval">{_esc(text)}</div></div>'
        )

    if display == "disks":
        disks_html = _render_disks(pdata.get("disks") or [])
        return f'<div class="card{wide}"><h2>{label}</h2>{disks_html}</div>'

    if display == "table":
        procs_html = _render_procs(pdata.get("top") or [])
        return (
            f'<div class="card{wide}"><h2>{label}</h2>'
            f"<table>"
            f"<thead><tr><th>PID</th><th>用户</th><th>命令</th><th>CPU%</th><th>MEM%</th></tr></thead>"
            f"<tbody>{procs_html}</tbody></table></div>"
        )

    return f'<div class="card{wide}"><h2>{label}</h2><p class="meta">未知展示类型</p></div>'


def _render_panel_grid(
    panels: list[dict[str, Any]],
    snap: dict[str, Any],
    hist: list[dict[str, Any]],
) -> str:
    panel_data = snap.get("panels") or {}
    if not panels:
        return '<p class="meta">暂无监控面板</p>'
    cards = []
    for panel in panels:
        pdata = panel_data.get(panel["id"]) or {}
        cards.append(_render_panel_card(panel, pdata, hist))
    return "\n".join(cards)


def render_dashboard_html(
    snap: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    panels: Optional[list[dict[str, Any]]] = None,
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

    panel_list = list(panels or [])
    host = _esc(snap.get("host", "?"))
    ip = _esc(snap.get("ip", "?"))
    cpu = snap.get("cpu_pct")
    mem = snap.get("mem_pct")
    temp = snap.get("temp_c")
    uptime = _esc(snap.get("uptime", "?"))

    cpu_pill = f"cpu={cpu:.1f}%" if isinstance(cpu, (int, float)) else "cpu=?"
    mem_pill = f"mem={mem:.1f}%" if isinstance(mem, (int, float)) else "mem=?"
    temp_pill = f"temp={temp:.1f}C" if isinstance(temp, (int, float)) else "temp=?"

    grid = _render_panel_grid(panel_list, snap, hist)

    header = f"""
<header>
  <h1>Pi Remote Control</h1>
  <div class="pills">
    <span class="pill">host={host}</span>
    <span class="pill">ip={ip}</span>
    <span class="pill">{_esc(cpu_pill)}</span>
    <span class="pill">{_esc(mem_pill)}</span>
    <span class="pill">{_esc(temp_pill)}</span>
    <span class="pill">up={uptime}</span>
  </div>
</header>
<main><div class="grid">{grid}</div></main>"""

    # Taller canvas when users add many panels (cheap PNG capture).
    design_h = max(DESIGN_HEIGHT, 180 + len(panel_list) * 120)

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
.textval{{font-size:18px;font-family:monospace;font-weight:700;margin:8px 0;word-break:break-word}}
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
        scale = min(width / DESIGN_WIDTH, height / design_h)
        shell_css = (
            f"html,body{{width:{width}px;height:{height}px;overflow:hidden;background:#fff}}\n"
            f"body{{display:flex;justify-content:center;align-items:flex-start;"
            f"color:#111;font-family:Georgia,\"Times New Roman\",serif;font-size:15px;line-height:1.4}}\n"
            f"#page{{transform:scale({scale:.6f});transform-origin:top center}}\n"
        )
        viewport = f"width={width},height={height},user-scalable=no"
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
            f"<span>{mount} ({fstype})</span>"
            f"<span>{human_bytes(d.get('used'))} / {human_bytes(d.get('total'))} · {pct:.1f}%</span>"
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

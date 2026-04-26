"""Shared HTML rendering helpers for the Gradio app.

Pure HTML — no Gradio imports — so any tab can build searchable, scrollable
tables and KPI blocks with consistent styling.
"""

from __future__ import annotations

import html as _html
import itertools
from typing import Iterable

_TABLE_ID_COUNTER = itertools.count(1)


def _next_table_id() -> str:
    return f"d2a-tbl-{next(_TABLE_ID_COUNTER)}"


# A cell may be:
#   - a plain value (escaped, no extra style)
#   - a (value, extra_css) tuple for inline cell styling (still escaped)
#   - a {"html": "<...>"} dict for pre-rendered HTML (NOT escaped — caller's responsibility)
Cell = object


def _render_cell(cell: Cell) -> str:
    base = "padding:6px;border-bottom:1px solid #2a2a2a;vertical-align:top"
    if isinstance(cell, dict) and "html" in cell:
        extra = cell.get("style") or ""
        style = base + (";" + extra if extra else "")
        return f"<td style='{style}'>{cell['html']}</td>"
    if isinstance(cell, tuple) and len(cell) == 2:
        value, extra = cell
        style = base + (";" + extra if extra else "")
        text = "" if value is None else str(value)
        return f"<td style='{style}'>{_html.escape(text)}</td>"
    text = "" if cell is None else str(cell)
    return f"<td style='{base}'>{_html.escape(text)}</td>"


def render_table(
    headers: list[str],
    rows: Iterable[list[Cell]],
    *,
    empty_msg: str = "—",
    max_height: int = 360,
    searchable: bool = True,
) -> str:
    """Render a styled HTML table with sticky header, scroll, and optional client-side filter.

    Cells accept plain values, (value, css) tuples, or {"html": ...} for raw HTML.
    """
    rows = list(rows)
    if not rows:
        return f"<p><em>{_html.escape(empty_msg)}</em></p>"
    tid = _next_table_id()
    th = "".join(
        "<th style='text-align:left;padding:6px;border-bottom:1px solid #888;"
        "position:sticky;top:0;background:var(--background-fill-primary, #1a1a1a);"
        f"z-index:1'>{_html.escape(h)}</th>"
        for h in headers
    )
    body_parts: list[str] = []
    for r in rows:
        tds = "".join(_render_cell(c) for c in r)
        body_parts.append(f"<tr>{tds}</tr>")
    search_box = ""
    if searchable:
        search_box = (
            "<input type='search' placeholder='Filter rows...' "
            f"data-target='{tid}' "
            'oninput="(function(e){var id=e.target.dataset.target;var q=e.target.value.toLowerCase();'
            "var t=document.getElementById(id);if(!t)return;"
            "t.querySelectorAll('tbody tr').forEach(function(r){"
            "r.style.display=r.innerText.toLowerCase().indexOf(q)>=0?'':'none';});"
            '})(event)" '
            "style='width:100%;padding:4px 8px;margin-bottom:6px;"
            "border:1px solid #555;border-radius:4px;background:transparent;color:inherit'/>"
        )
    return (
        f"<div>{search_box}"
        f"<div style='max-height:{max_height}px;overflow:auto;"
        "border:1px solid #2a2a2a;border-radius:4px'>"
        f"<table id='{tid}' style='width:100%;border-collapse:collapse;font-size:0.9em'>"
        f"<thead><tr>{th}</tr></thead><tbody>{''.join(body_parts)}</tbody></table>"
        "</div></div>"
    )


def render_kpis(items: list[tuple[str, object]]) -> str:
    """Render a flex row of KPI cards."""
    cells = []
    for label, value in items:
        cells.append(
            "<div style='flex:1;min-width:120px;padding:12px 16px;"
            "border:1px solid #2a2a2a;border-radius:8px;margin:4px'>"
            f"<div style='font-size:0.8em;opacity:0.75'>{_html.escape(label)}</div>"
            f"<div style='font-size:1.6em;font-weight:600'>{_html.escape(str(value))}</div>"
            "</div>"
        )
    return "<div style='display:flex;flex-wrap:wrap'>" + "".join(cells) + "</div>"


def fmt_score(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def fmt_duration_ms(value: object) -> str:
    """Format a duration in milliseconds as a human-readable string."""
    if value is None:
        return "—"
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return "—"
    if ms < 1000:
        return f"{ms:.0f} ms"
    secs = ms / 1000.0
    if secs < 60:
        return f"{secs:.2f} s"
    mins, secs = divmod(secs, 60)
    return f"{int(mins)}m {secs:.1f}s"

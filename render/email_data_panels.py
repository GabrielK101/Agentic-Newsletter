"""email_data_panels.py - the ticker and per-sport scoreboard data-panel
renderers used by email_render.py.

Split out of email_render.py as a pure refactor (no behavior change).
"""
from render.email_components import _esc, _section_bar_html

_INK = "#1b1a17"
_ACCENT = "#7a1f12"
_MUTED = "#4b4840"
_RULE = "#cfc7b6"
_RULE_DOTTED = "#9d9686"
_UP = "#1d5e2f"
_DOWN = "#8e1d10"

_SANS = "-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

_MAX_SCOREBOARD_GROUPS = 3
_MAX_SCOREBOARD_ROWS_PER_GROUP = 4

_DIRECTION_SYMBOL = {"up": "&#9650;", "down": "&#9660;", "flat": "&#8211;"}
_DIRECTION_COLOR = {"up": _UP, "down": _DOWN, "flat": _MUTED}


def _ticker_html(ticker: list[dict]) -> str:
    """A real 3x2 <table> - the same on every width, no hybrid blocks,
    no media query. The session day (ticker[0]["session_day"], present
    only for code-sourced data - see market_data.py) goes in the heading
    instead of repeating on every row; falls back to a dayless "Markets"
    heading for model-sourced ticker data, which doesn't carry it."""
    if not ticker:
        return ""
    session_day = ticker[0].get("session_day")
    heading = f"Markets · {session_day} close" if session_day else "Markets"
    cells = []
    for row in ticker[:6]:
        color = _DIRECTION_COLOR.get(row.get("direction"), _MUTED)
        symbol = _DIRECTION_SYMBOL.get(row.get("direction"), "")
        cells.append(
            f'<td width="33%" valign="top" align="center" '
            f'style="padding:9px 8px;border-top:1px solid {_RULE};text-align:center;">'
            f'<div style="font-family:{_SANS};font-size:10.5px;font-weight:700;letter-spacing:1px;'
            f'text-transform:uppercase;color:{_MUTED};">{_esc(row.get("label", ""))}</div>'
            f'<div style="font-family:{_SANS};font-size:15px;font-weight:600;color:{_INK};margin-top:2px;">'
            f'{_esc(row.get("value", ""))}</div>'
            f'<div style="font-family:{_SANS};font-size:12.5px;font-weight:700;color:{color};margin-top:1px;">'
            f'{symbol} {_esc(row.get("change", ""))}</div></td>'
        )
    rows = "".join(f"<tr>{''.join(cells[i:i + 3])}</tr>" for i in range(0, len(cells), 3))
    return (
        f'<div style="margin:18px 0 0 0;font-family:{_SANS};font-size:10.5px;font-weight:700;'
        f'letter-spacing:1.5px;text-transform:uppercase;color:{_ACCENT};">{_esc(heading)}</div>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-bottom:1px solid {_INK};margin-top:4px;">{rows}</table>'
    )


def _scoreboard_panel_html(group: str, rows: list[dict]) -> str:
    trs = "".join(
        '<tr><td style="padding:6px 0;border-bottom:1px dotted '
        f'{_RULE_DOTTED};font-family:{_SANS};font-size:13px;line-height:1.35;color:{_INK};">'
        + (f'<span style="font-weight:700;">{_esc(row.get("label", ""))}</span><br>' if row.get("label") else "")
        + f'{_esc(row.get("line", ""))}</td></tr>'
        for row in rows[:_MAX_SCOREBOARD_ROWS_PER_GROUP]
    )
    return (
        f'<div style="font-family:{_SANS};font-size:11px;font-weight:700;letter-spacing:1.5px;'
        f'text-transform:uppercase;color:{_ACCENT};padding:0 0 4px 0;border-bottom:1px solid {_INK};">'
        f'{_esc(group)}</div>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{trs}</table>'
    )


def _scoreboard_html(scoreboard: list[dict]) -> str:
    """One panel per group (sport/competition), up to 3 groups. Mobile-
    first: each panel is a full-width stacked block by default; a small
    <style> media query (min-width:620px) lines them up side by side on
    anything wider - a client that drops <style> entirely (the Gmail app
    on a non-Google account) just keeps the stacked phone layout, which
    is the correct fallback, not a broken one. An <!--[if mso]> table
    gives Outlook desktop (which honours neither inline-block nor that
    media query) the same side-by-side result directly."""
    if not scoreboard:
        return ""
    groups: dict[str, list[dict]] = {}
    for row in scoreboard:
        groups.setdefault(row.get("group") or "Results", []).append(row)
    group_items = list(groups.items())[:_MAX_SCOREBOARD_GROUPS]
    n = len(group_items)
    if n == 0:
        return ""

    panels_fluid = "".join(
        f'<div class="sbp sbp{n}" style="display:block;width:100%;vertical-align:top;'
        f'font-size:15px;line-height:1.4;margin:0 0 18px 0;">{_scoreboard_panel_html(g, rows)}</div>'
        for g, rows in group_items
    )
    mso_width_pct = 100 // n
    mso = (
        '<!--[if mso]><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
        + "".join(
            f'<td width="{mso_width_pct}%" valign="top" style="padding:0 12px;">{_scoreboard_panel_html(g, rows)}</td>'
            for g, rows in group_items
        )
        + '</tr></table><![endif]-->'
    )
    fluid = (
        '<!--[if !mso]><!-->'
        f'<div class="sbwrap" style="font-size:0;line-height:0;">{panels_fluid}</div>'
        '<!--<![endif]-->'
    )
    return _section_bar_html("Scoreboard") + mso + fluid

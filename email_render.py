"""email_render.py - the mobile-first email renderer.

Replaces newsletter_render.render_html/render_teaser_html as the default
email (see delivery.py). Visual structure matches the reference mock
(design/ review round: mock.py/mock_email.html) - 720px content width,
a coloured masthead, a real 3x2 ticker table, a 2-up hybrid lead/
secondary/briefs layout, and per-sport scoreboard panels. Inline styles
only; the one small <style> block is a pure enhancement (desktop-only
scoreboard panel widths) that degrades safely to the stacked mobile
layout if a client drops it entirely (the Gmail app on non-Google
accounts does). No CSS grid/flexbox, no JavaScript, no SVG.

Reuses newsletter_render.py's shared, client-agnostic logic (safe_url,
clamp_summary, sentence_ends, format_relative_date, kicker_parts,
follows_text, the SUMMARY_CEILING_* constants) - only the HTML/CSS
structure here is new.
"""
import html

from newsletter_render import (
    SUMMARY_CEILING_BRIEF, SUMMARY_CEILING_HERO, SUMMARY_CEILING_MAJOR,
    clamp_summary, follows_text, format_relative_date, kicker_parts, safe_url, sentence_ends,
)

_PAPER = "#f6f1e4"
_INK = "#1b1a17"
_ACCENT = "#7a1f12"
_MUTED = "#4b4840"
_RULE = "#cfc7b6"
_RULE_DOTTED = "#9d9686"
_UP = "#1d5e2f"
_DOWN = "#8e1d10"

_SERIF = "Georgia,'Times New Roman',Times,serif"
_SANS = "-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

CONTENT_WIDTH = 720
_COL_WIDTH = 352  # hybrid column max-width: 2 x 352 + 16 gutter = 720
_SIDE_PAD = 16

_MAX_HTML_BYTES = 90_000  # Gmail clips around ~102KB; keep a safety margin
_MAX_SCOREBOARD_GROUPS = 3
_MAX_SCOREBOARD_ROWS_PER_GROUP = 4

_e = html.escape


def _esc(value) -> str:
    return _e(str(value if value is not None else ""))


def _href_attr(url: str | None) -> str:
    safe = safe_url(url or "")
    if safe == "#":
        return ""
    return f' href="{html.escape(safe, quote=True)}"'


def _kicker_html(story: dict, show_topic: bool = True) -> str:
    parts = kicker_parts(story, show_topic)
    if not parts:
        return ""
    text = " &middot; ".join(parts)
    return (
        f'<div style="font-family:{_SANS};font-size:11px;font-weight:700;letter-spacing:1.5px;'
        f'text-transform:uppercase;color:{_ACCENT};margin:0 0 6px 0;">{text}</div>'
    )


def _follows_html(story: dict) -> str:
    text = follows_text(story)
    if not text:
        return ""
    return f'<p style="margin:0 0 6px 0;font-family:{_SERIF};font-size:12px;font-style:italic;color:{_MUTED};">{_esc(text)}</p>'


def _headline_html(text: str, url: str | None, size: int) -> str:
    href = _href_attr(url)
    escaped = _esc(text)
    if href:
        return (
            f'<a{href} style="color:{_INK};text-decoration:none;font-family:{_SERIF};'
            f'font-weight:700;font-size:{size}px;line-height:1.18;display:block;">{escaped}</a>'
        )
    return f'<div style="color:{_INK};font-family:{_SERIF};font-weight:700;font-size:{size}px;line-height:1.18;">{escaped}</div>'


def _para(text: str, size: float = 15, color: str = "#2b2925", top: int = 8) -> str:
    return f'<p style="margin:{top}px 0 0 0;font-family:{_SERIF};font-size:{size}px;line-height:1.55;color:{color};">{_esc(text)}</p>'


def _hybrid_row(cells_html: list[str]) -> str:
    """2-up on anything wide enough, stacked on phones, no media query:
    each cell is an inline-block div capped at _COL_WIDTH inside a
    font-size:0 container (so inter-tag whitespace can't force an early
    wrap). A single cell is simply full width - never forced into a
    half-width column on its own."""
    if len(cells_html) == 1:
        return f'<div style="padding:0 0 4px 0;">{cells_html[0]}</div>'
    inner = "".join(
        f'<div style="display:inline-block;vertical-align:top;width:100%;max-width:{_COL_WIDTH}px;'
        f'font-size:15px;line-height:1.4;margin-right:{16 if i % 2 == 0 else 0}px;">{cell}</div>'
        for i, cell in enumerate(cells_html)
    )
    return f'<div style="font-size:0;line-height:0;">{inner}</div>'


def _section_bar_html(name: str) -> str:
    return (
        f'<div style="border-top:3px double {_INK};border-bottom:1px solid {_INK};padding:7px 0;'
        f'margin:26px 0 14px 0;text-align:center;font-family:{_SERIF};font-weight:700;font-size:14px;'
        f'letter-spacing:3px;text-transform:uppercase;color:{_INK};">{_esc(name)}</div>'
    )


def _preheader_html(lead: dict | None, secondary: list[dict]) -> str:
    headlines = []
    if lead:
        headlines.append(str(lead.get("headline", "")))
    headlines.extend(str(s.get("headline", "")) for s in secondary[:2])
    text = " · ".join(h for h in headlines if h)
    if len(text) > 110:
        text = text[:107].rstrip() + "..."
    padding = "&#847;&zwnj;&nbsp;" * 30
    return f'<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">{_esc(text)}{padding}</div>'


def _masthead_html(title: str, tagline: str | None, date_str: str, web_url: str | None) -> str:
    tagline_html = (
        f'<div style="text-align:center;font-family:{_SERIF};font-style:italic;font-size:14px;'
        f'color:{_MUTED};margin-top:4px;">{_esc(tagline)}</div>'
        if tagline else ""
    )
    href = _href_attr(web_url)
    link_html = (
        f'<a{href} style="color:{_ACCENT};text-decoration:none;font-weight:700;">Full front page &rarr;</a>'
        if href else ""
    )
    return (
        f'<div style="border-top:4px solid {_INK};margin:0 0 14px 0;"></div>'
        f'<div style="text-align:center;font-family:{_SERIF};font-weight:700;font-size:36px;'
        f'letter-spacing:2px;color:{_INK};line-height:1.1;">{_highlight_daily(title)}</div>'
        + tagline_html +
        f'<div style="border-top:1px solid {_INK};margin:12px 0 2px 0;"></div>'
        f'<div style="border-top:1px solid {_INK};margin:0 0 7px 0;"></div>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td style="font-family:{_SANS};font-size:11px;letter-spacing:1.5px;color:{_MUTED};'
        f'text-transform:uppercase;">{_esc(date_str)}</td>'
        f'<td align="right" style="font-family:{_SANS};font-size:11px;letter-spacing:1px;'
        f'text-transform:uppercase;">{link_html}</td></tr></table>'
    )


def _highlight_daily(title: str) -> str:
    """`title` escaped, with the first case-insensitive whole-word match
    of "Daily" picked out in the accent colour - matches the masthead
    style used elsewhere in this project. No match -> plain escaped text."""
    import re
    escaped = _esc(title.upper())
    pattern = re.compile(r"\bDAILY\b", re.IGNORECASE)
    return pattern.sub(lambda m: f'<span style="color:{_ACCENT};">{m.group(0)}</span>', escaped, count=1)


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
            f'<td width="33%" valign="top" style="padding:9px 8px;border-top:1px solid {_RULE};">'
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


def _split_long_paragraph(text: str, max_words: int = 60) -> list[str]:
    """If `text` is a single paragraph over `max_words`, split it into two
    at the sentence boundary nearest the middle (using sentence_ends from
    newsletter_render, the same abbreviation-aware boundary detector
    clamp_summary uses) - never mid-sentence. Returns [text] unchanged if
    it's already short enough or has no usable boundary to split at."""
    words = text.split()
    if len(words) <= max_words:
        return [text]
    boundaries = list(sentence_ends(text))
    if not boundaries:
        return [text]
    middle = len(text) / 2
    best = min(boundaries, key=lambda m: abs(m.end() - middle))
    first, second = text[:best.end()].strip(), text[best.end():].strip()
    return [p for p in (first, second) if p]


def _lead_html(lead: dict | None) -> str:
    if not lead:
        return ""
    body = str(lead.get("body") or lead.get("summary") or "")
    body = clamp_summary(body, SUMMARY_CEILING_HERO)
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    if len(paragraphs) == 1:
        paragraphs = _split_long_paragraph(paragraphs[0])
    dek = str(lead.get("dek") or "").strip()
    sources = [s for s in (lead.get("sources") or []) if s]
    return (
        f'<div style="padding:22px 0 0 0;">'
        + _kicker_html(lead, show_topic=True) + _follows_html(lead)
        + _headline_html(lead.get("headline", ""), lead.get("url"), 32)
        + (
            f'<p style="margin:10px 0 0 0;font-family:{_SERIF};font-style:italic;font-size:18px;'
            f'line-height:1.4;color:#3a3833;">{_esc(dek)}</p>'
            if dek else ""
        )
        + "".join(_para(p) for p in paragraphs)
        + (
            f'<div style="font-family:{_SANS};font-size:11.5px;color:{_MUTED};margin-top:10px;">'
            f'Sources: {_esc(", ".join(sources))}</div>'
            if sources else ""
        )
        + "</div>"
    )


def _secondary_item_html(item: dict) -> str:
    summary = clamp_summary(str(item.get("summary", "")), SUMMARY_CEILING_MAJOR)
    return (
        f'<div style="border-top:1px solid {_INK};padding:14px 0 6px 0;">'
        + _kicker_html(item, show_topic=True) + _follows_html(item)
        + _headline_html(item.get("headline", ""), item.get("url"), 21)
        + (_para(summary, 14.5, "#3a3833", 7) if summary else "")
        + "</div>"
    )


def _secondary_html(secondary: list[dict]) -> str:
    """2-up on desktop, stacked on mobile; with 3 items, 2-up then 1 full
    width - never 3-up (_hybrid_row always pairs by 2)."""
    if not secondary:
        return ""
    items = [_secondary_item_html(s) for s in secondary]
    rows = [_hybrid_row(items[i:i + 2]) for i in range(0, len(items), 2)]
    return f'<div style="margin-top:20px;">{"".join(rows)}</div>'


def _brief_html(brief: dict) -> str:
    summary = clamp_summary(str(brief.get("summary", "")), SUMMARY_CEILING_BRIEF)
    return (
        f'<div style="padding:0 0 14px 0;margin:0 0 14px 0;border-bottom:1px solid {_RULE};">'
        + _kicker_html(brief, show_topic=False) + _follows_html(brief)
        + _headline_html(brief.get("headline", ""), brief.get("url"), 18)
        + (_para(summary, 14, "#3a3833", 6) if summary else "")
        + "</div>"
    )


def _sections_html(sections: list[dict]) -> str:
    """Non-empty sections only. A section with one brief shows it full
    width, except two CONSECUTIVE one-brief sections, which sit side by
    side (each column carries its own bar) - this removes ragged gaps
    without breaking mobile reading order, since they still stack in the
    same top-to-bottom sequence."""
    live = [s for s in sections if s.get("briefs")]
    if not live:
        return ""
    parts = []
    i = 0
    while i < len(live):
        section = live[i]
        briefs = section["briefs"]
        nxt = live[i + 1] if i + 1 < len(live) else None
        if len(briefs) == 1 and nxt and len(nxt["briefs"]) == 1:
            cells = [
                _section_bar_html(s["name"]) + _brief_html(s["briefs"][0])
                for s in (section, nxt)
            ]
            parts.append(_hybrid_row(cells))
            i += 2
            continue
        parts.append(_section_bar_html(section["name"]))
        for j in range(0, len(briefs), 2):
            parts.append(_hybrid_row([_brief_html(b) for b in briefs[j:j + 2]]))
        i += 1
    return "".join(parts)


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


def _button_html(web_url: str | None) -> str:
    href = _href_attr(web_url)
    if not href:
        return ""
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" align="center" '
        'style="margin:28px auto 0 auto;"><tr>'
        f'<td bgcolor="{_ACCENT}" style="background:{_ACCENT};border-radius:3px;">'
        f'<a{href} style="display:inline-block;padding:13px 28px;font-family:{_SANS};font-size:13px;'
        f'font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#ffffff;text-decoration:none;">'
        'Read the full front page &rarr;</a></td></tr></table>'
    )


def _footer_html(sources: list[dict], disclosure: str | None, notes: str) -> str:
    source_names = []
    for src in sources or []:
        name = src.get("name")
        if not name:
            continue
        href = _href_attr(src.get("url"))
        source_names.append(f'<a{href} style="color:{_MUTED};">{_esc(name)}</a>' if href else _esc(name))
    parts = []
    if source_names:
        parts.append(f"Sources: {', '.join(source_names)}")
    if disclosure:
        parts.append(_esc(disclosure))
    if notes:
        parts.append(_esc(notes))
    if not parts:
        return ""
    return (
        f'<div style="border-top:3px double {_INK};margin:28px 0 0 0;padding-top:10px;text-align:center;'
        f'font-family:{_SANS};font-size:11.5px;line-height:1.6;color:{_MUTED};">{"<br>".join(parts)}</div>'
    )


_HEAD_STYLE = """
@media screen and (min-width:620px){
  .sbp{display:inline-block!important;margin-right:24px!important}
  .sbp3{width:224px!important}
  .sbp2{width:348px!important}
  .sbp:last-child{margin-right:0!important}
}
"""


def render_email_html(front_page: dict, title: str = "The Daily Digest",
                       tagline: str | None = None, web_url: str | None = None,
                       date_str: str = "") -> str:
    """One self-contained, mobile-first email HTML string, 720px wide.
    Trims briefs (last section first) if the result would exceed
    _MAX_HTML_BYTES."""
    lead = front_page.get("lead")
    secondary = list(front_page.get("secondary") or [])
    sections = [dict(s, briefs=list(s.get("briefs") or [])) for s in (front_page.get("sections") or [])]
    ticker = front_page.get("ticker") or []
    scoreboard = front_page.get("scoreboard") or []
    sources = front_page.get("sources") or []
    disclosure = front_page.get("disclosure")
    notes = str(front_page.get("notes") or "").strip()

    def build() -> str:
        body = (
            _preheader_html(lead, secondary)
            + _masthead_html(title, tagline, date_str, web_url)
            + _ticker_html(ticker)
            + _lead_html(lead)
            + _secondary_html(secondary)
            + _sections_html(sections)
            + _scoreboard_html(scoreboard)
            + _button_html(web_url)
            + _footer_html(sources, disclosure, notes)
        )
        return (
            "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta name="color-scheme" content="light">'
            '<meta name="supported-color-schemes" content="light">'
            f"<title>{_esc(title)}</title>"
            f"<style>{_HEAD_STYLE}</style>"
            f'</head><body style="margin:0;padding:0;background:{_PAPER};" bgcolor="{_PAPER}">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'bgcolor="{_PAPER}" style="background:{_PAPER};"><tr><td align="center" style="padding:28px {_SIDE_PAD}px;">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="max-width:{CONTENT_WIDTH}px;"><tr><td style="text-align:left;color:{_INK};">'
            + body +
            '</td></tr></table></td></tr></table></body></html>'
        )

    html_out = build()
    # Oversize trimming: drop briefs from the last section backwards
    # until under budget, rather than cutting mid-document.
    guard = 0
    while len(html_out.encode("utf-8")) > _MAX_HTML_BYTES and guard < 200:
        trimmed_any = False
        for section in reversed(sections):
            if section["briefs"]:
                section["briefs"].pop()
                trimmed_any = True
                break
        if not trimmed_any:
            print("[warning] email_render: output still over size budget after trimming all briefs")
            break
        html_out = build()
        guard += 1
    if len(html_out.encode("utf-8")) > _MAX_HTML_BYTES:
        print(f"[warning] email_render: final HTML is {len(html_out.encode('utf-8'))} bytes, over the {_MAX_HTML_BYTES} budget")
    return html_out


def render_email_text(front_page: dict, title: str = "The Daily Digest",
                       web_url: str | None = None, date_str: str = "") -> str:
    """Plain-text alternative, same order as render_email_html."""
    lead = front_page.get("lead")
    secondary = front_page.get("secondary") or []
    sections = front_page.get("sections") or []
    ticker = front_page.get("ticker") or []
    scoreboard = front_page.get("scoreboard") or []
    sources = front_page.get("sources") or []
    disclosure = front_page.get("disclosure")

    lines = [title, date_str, ""]

    if ticker:
        for row in ticker:
            change = f" {row['change']}" if row.get("change") else ""
            lines.append(f"{row['label']}: {row['value']}{change}")
        lines.append("")

    if lead:
        lines.append(lead.get("headline", ""))
        if lead.get("dek"):
            lines.append(lead["dek"])
        body = lead.get("body") or lead.get("summary") or ""
        if body:
            lines.append(body)
        if lead.get("sources"):
            lines.append(f"Sources: {', '.join(lead['sources'])}")
        lines.append("")

    if secondary:
        lines.append("ALSO TODAY")
        for item in secondary:
            lines.append(item.get("headline", ""))
            if item.get("summary"):
                lines.append(item["summary"])
            lines.append("")

    for section in sections:
        briefs = section.get("briefs") or []
        if not briefs:
            continue
        lines.append(section.get("name", "").upper())
        for brief in briefs:
            lines.append(brief.get("headline", ""))
            if brief.get("summary"):
                lines.append(brief["summary"])
        lines.append("")

    if scoreboard:
        lines.append("SCOREBOARD")
        groups: dict[str, list[dict]] = {}
        for row in scoreboard:
            groups.setdefault(row.get("group") or "Results", []).append(row)
        for group, rows in groups.items():
            lines.append(group)
            for row in rows:
                prefix = f"{row['label']}: " if row.get("label") else ""
                lines.append(f"{prefix}{row['line']}")
        lines.append("")

    if web_url:
        lines.append(f"Read the full front page: {web_url}")
        lines.append("")

    if sources:
        lines.append("Sources: " + ", ".join(s["name"] for s in sources if s.get("name")))
    if disclosure:
        lines.append(disclosure)

    return "\n".join(lines)

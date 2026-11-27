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

The generic HTML-building helpers (escaping, links, kickers, headlines,
paragraphs, the hybrid 2-up layout, section bars, masthead, footer) live
in email_components.py; the ticker/scoreboard data-panel renderers live
in email_data_panels.py. This module keeps the top-level content
assembly and the two public entry points, render_email_html and
render_email_text.
"""
from render.email_components import (
    _button_html, _esc, _footer_html, _follows_html, _headline_html, _hybrid_row, _kicker_html,
    _para, _preheader_html, _masthead_html, _section_bar_html, _split_long_paragraph,
)
from render.email_data_panels import _scoreboard_html, _ticker_html
from render.newsletter_render import (
    SUMMARY_CEILING_BRIEF, SUMMARY_CEILING_HERO, SUMMARY_CEILING_MAJOR, clamp_summary,
)

_PAPER = "#f6f1e4"
_INK = "#1b1a17"
_MUTED = "#4b4840"
_RULE = "#cfc7b6"

_SERIF = "Georgia,'Times New Roman',Times,serif"
_SANS = "-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

_SIDE_PAD = 16

CONTENT_WIDTH = 720

_MAX_HTML_BYTES = 90_000  # Gmail clips around ~102KB; keep a safety margin


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

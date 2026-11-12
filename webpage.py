"""webpage.py - the web edition: a single self-contained HTML page.

Replicates design/Main.dc.html's broadsheet look (colours, fonts, sizes,
spacing, rules) in plain HTML/CSS - no React, no build step - built from
the same already-filtered front-page shape the email renderer uses
(see digest.py's prepare_front_page). Every text field is escaped; every
href goes through safe_url first. Collapses to 2 columns, then 1, on
narrower screens.
"""
import html
from datetime import date as date_cls

from newsletter_render import clamp_summary, safe_url

_BODY_BG = "#e9e4d8"
_PAPER = "#f6f1e4"
_INK = "#1b1a17"
_ACCENT = "#7a1f12"
_ACCENT_HOVER = "#4a120a"
_MUTED = "#4b4840"
_RULE_SOFT = "#b9b2a3"
_RULE_DOTTED = "#9d9686"
_UP = "#1d5e2f"
_DOWN = "#8e1d10"

_LEAD_BODY_WORDS = 160
_SECONDARY_SUMMARY_WORDS = 60
_BRIEF_SUMMARY_WORDS = 60

_FONTS_HREF = (
    "https://fonts.googleapis.com/css2?family=UnifrakturMaguntia"
    "&family=Playfair+Display:ital,wght@0,700;0,900;1,700"
    "&family=Libre+Caslon+Text:ital,wght@0,400;0,700;1,400"
    "&family=Inter:wght@500;700&display=swap"
)

_STYLE = f"""
body{{margin:0;background:{_BODY_BG}}}
a{{color:{_ACCENT};text-decoration:none}}
a:hover{{color:{_ACCENT_HOVER}}}
.page{{width:100%;max-width:1240px;margin:0 auto;box-sizing:border-box;
  padding:40px 52px;background:{_PAPER};font-family:'Libre Caslon Text',Georgia,serif;
  color:{_INK}}}
.page p{{margin:0 0 10px 0;font-size:14.5px;line-height:1.5;text-align:justify;hyphens:auto}}
.kicker{{font-family:'Inter',sans-serif;font-weight:700;font-size:11px;letter-spacing:.14em;
  text-transform:uppercase;color:{_ACCENT};margin:0 0 6px 0}}
.hd{{font-family:'Playfair Display',Georgia,serif;font-weight:900;line-height:1.05;margin:0 0 8px 0}}
.hd a{{color:inherit}}
.dek{{font-family:'Playfair Display',Georgia,serif;font-style:italic;font-weight:700;
  font-size:19px;line-height:1.3;margin:0 0 12px 0;color:#3a3833}}
.rule{{border:0;border-top:1px solid {_INK};margin:14px 0}}
.sec{{font-family:'Playfair Display',Georgia,serif;font-weight:900;font-size:15px;
  letter-spacing:.2em;text-transform:uppercase;border-top:3px double {_INK};
  border-bottom:1px solid {_INK};padding:6px 0;margin:0 0 12px 0;text-align:center}}
.col{{display:flex;flex-direction:column;min-width:0}}
.brief{{margin:0 0 12px 0;padding:0 0 12px 0;border-bottom:1px solid {_RULE_SOFT}}}
.brief:last-child{{border-bottom:0}}
.brief h4{{font-family:'Playfair Display',Georgia,serif;font-weight:700;font-size:18px;
  line-height:1.15;margin:0 0 5px 0}}
.brief p{{font-size:13.5px;margin:0}}
.secondary-item{{margin:0 0 14px 0;padding:0 0 14px 0;border-bottom:1px solid {_RULE_SOFT}}}
.secondary-item:last-child{{border-bottom:0}}
.score{{display:flex;justify-content:space-between;font-family:'Inter',sans-serif;
  font-size:13px;padding:5px 0;border-bottom:1px dotted {_RULE_DOTTED}}}
.score b{{font-weight:700}}
.tick{{display:flex;flex-direction:column;gap:2px;font-family:'Inter',sans-serif;font-size:12px}}
.tick span:first-child{{font-weight:700;letter-spacing:.06em;text-transform:uppercase;
  font-size:10.5px;color:{_MUTED}}}
.up{{color:{_UP};font-weight:700}}
.dn{{color:{_DOWN};font-weight:700}}
.flat{{color:{_MUTED};font-weight:700}}
.empty-note{{font-style:italic;color:{_MUTED};font-size:13px;margin:0}}
.masthead{{font-family:'UnifrakturMaguntia',serif;font-weight:400;font-size:min(9vw,104px);
  line-height:1;text-align:center;margin:14px 0 6px 0;color:{_INK}}}
.metabar{{border-top:3px double {_INK};border-bottom:1px solid {_INK};padding:7px 0;
  display:flex;flex-wrap:wrap;gap:6px;justify-content:space-between;
  font-family:'Inter',sans-serif;font-size:12.5px;letter-spacing:.06em;text-transform:uppercase}}
.tickerrow{{display:grid;grid-template-columns:repeat(6,1fr);gap:18px;padding:10px 0;
  border-bottom:1px solid {_INK};margin-bottom:22px}}
.leadgrid{{display:grid;grid-template-columns:2fr 1fr;gap:32px}}
.leadcol{{border-right:1px solid {_INK};padding-right:32px}}
.leadbody-cols{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}
.briefsgrid{{display:grid;grid-template-columns:repeat(4,1fr);gap:28px;margin-top:26px}}
.scoreboard-block{{margin-top:26px}}
.footer{{margin-top:28px;border-top:3px double {_INK};padding-top:8px;display:flex;
  flex-wrap:wrap;justify-content:space-between;gap:10px;font-family:'Inter',sans-serif;
  font-size:11px;letter-spacing:.05em;color:{_MUTED}}}

@media (max-width:900px){{
  .leadgrid{{grid-template-columns:1fr}}
  .leadcol{{border-right:0;padding-right:0;border-bottom:1px solid {_INK};
    padding-bottom:20px;margin-bottom:20px}}
  .leadbody-cols{{grid-template-columns:1fr}}
  .briefsgrid{{grid-template-columns:repeat(2,1fr)}}
  .tickerrow{{grid-template-columns:repeat(3,1fr)}}
}}
@media (max-width:480px){{
  .page{{padding:20px 18px}}
  .briefsgrid{{grid-template-columns:1fr}}
  .tickerrow{{grid-template-columns:repeat(2,1fr)}}
  .masthead{{font-size:15vw}}
  .leadcol{{padding-right:0}}
}}
"""

_DIRECTION_SYMBOL = {"up": "&#9650;", "down": "&#9660;", "flat": "&#8211;"}
_DIRECTION_CLASS = {"up": "up", "down": "dn", "flat": "flat"}


def _esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


def _href_attr(url: str | None) -> str:
    """A safe `href="..."` attribute, or "" if there's no usable http(s) url."""
    safe = safe_url(url or "")
    if safe == "#":
        return ""
    return f' href="{html.escape(safe, quote=True)}"'


def _linked(text: str, url: str | None) -> str:
    attr = _href_attr(url)
    escaped = _esc(text)
    return f"<a{attr}>{escaped}</a>" if attr else escaped


def _read_more(url: str | None) -> str:
    attr = _href_attr(url)
    if not attr:
        return ""
    return (
        f'<p style="margin-top:6px;"><a{attr} style="font-family:\'Inter\',sans-serif;'
        f'font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;">'
        f'Read more &#8594;</a></p>'
    )


def _kicker_html(text: str) -> str:
    text = (text or "").strip()
    return f'<p class="kicker">{_esc(text.upper())}</p>' if text else ""


def _paragraphs(body: str) -> list[str]:
    return [p.strip() for p in (body or "").split("\n\n") if p.strip()]


def _lead_html(lead: dict | None) -> str:
    if not lead:
        return '<p class="empty-note">No lead story today.</p>'

    headline_html = f'<h2 class="hd" style="font-size:44px;">{_linked(lead.get("headline", ""), lead.get("url"))}</h2>'
    dek_html = f'<p class="dek">{_esc(lead.get("dek"))}</p>' if lead.get("dek") else ""

    paras = [clamp_summary(p, _LEAD_BODY_WORDS) for p in _paragraphs(lead.get("body", ""))]
    if len(paras) >= 2:
        mid = (len(paras) + 1) // 2
        left = "".join(f"<p>{_esc(p)}</p>" for p in paras[:mid])
        right = "".join(f"<p>{_esc(p)}</p>" for p in paras[mid:])
        body_html = f'<div class="leadbody-cols"><div>{left}</div><div>{right}</div></div>'
    else:
        body_html = "".join(f"<p>{_esc(p)}</p>" for p in paras)

    sources = [s for s in (lead.get("sources") or []) if s]
    sources_html = (
        f'<p style="font-family:\'Inter\',sans-serif;font-size:11px;color:{_MUTED};margin-top:10px;">'
        f'Sources: {_esc(", ".join(sources))}</p>'
        if sources else ""
    )

    return (
        _kicker_html(lead.get("topic", "")) + headline_html + dek_html
        + body_html + sources_html + _read_more(lead.get("url"))
    )


def _secondary_html(secondary: list[dict]) -> str:
    if not secondary:
        return '<p class="empty-note">Nothing else stood out today.</p>'
    items = []
    for item in secondary:
        summary = clamp_summary(item.get("summary", ""), _SECONDARY_SUMMARY_WORDS)
        items.append(
            '<div class="secondary-item">'
            + _kicker_html(item.get("topic", ""))
            + f'<h3 class="hd" style="font-size:22px;">{_linked(item.get("headline", ""), item.get("url"))}</h3>'
            + (f"<p>{_esc(summary)}</p>" if summary else "")
            + "</div>"
        )
    return "".join(items)


def _brief_html(brief: dict) -> str:
    summary = clamp_summary(brief.get("summary", ""), _BRIEF_SUMMARY_WORDS)
    return (
        '<div class="brief">'
        f'<h4>{_linked(brief.get("headline", ""), brief.get("url"))}</h4>'
        + (f"<p>{_esc(summary)}</p>" if summary else "")
        + "</div>"
    )


def _section_column_html(section: dict) -> str:
    briefs = section.get("briefs") or []
    body = (
        "".join(_brief_html(b) for b in briefs)
        if briefs else '<p class="empty-note">Nothing new today.</p>'
    )
    return f'<div class="col"><p class="sec">{_esc(section.get("name", ""))}</p>{body}</div>'


def _ticker_html(ticker: list[dict]) -> str:
    if not ticker:
        return ""
    cells = []
    for row in ticker:
        direction = row.get("direction")
        symbol = _DIRECTION_SYMBOL.get(direction, "")
        cls = _DIRECTION_CLASS.get(direction, "")
        change = _esc(row.get("change", ""))
        movement = f'<span class="{cls}">{symbol} {change}</span>'.strip() if (symbol or change) else ""
        cells.append(
            '<div class="tick">'
            f'<span>{_esc(row.get("label", ""))}</span>'
            f'<span>{_esc(row.get("value", ""))} {movement}</span>'
            "</div>"
        )
    return f'<div class="tickerrow">{"".join(cells)}</div>'


def _scoreboard_html(scoreboard: list[dict]) -> str:
    if not scoreboard:
        return ""
    rows = "".join(
        f'<div class="score"><span>{_esc(row.get("label", ""))}</span>'
        f'<span>{_esc(row.get("line", ""))}</span></div>'
        for row in scoreboard
    )
    return f'<div class="scoreboard-block"><p class="sec">Scoreboard</p>{rows}</div>'


def _footer_html(sources: list[dict], disclosure: str | None) -> str:
    source_names = []
    for src in sources or []:
        name = src.get("name")
        if not name:
            continue
        source_names.append(_linked(name, src.get("url")) if src.get("url") else _esc(name))
    sources_html = f"Sources: {', '.join(source_names)}" if source_names else ""
    disclosure_html = _esc(disclosure) if disclosure else ""
    return f'<div class="footer"><span>{sources_html}</span><span>{disclosure_html}</span></div>'


def render_web(digest: dict, title: str = "The Daily Digest",
               tagline: str | None = None, date: date_cls | None = None) -> str:
    """Render the web edition: one self-contained HTML string (inline CSS,
    Google Fonts <link> tags only) built from the already-filtered
    front-page shape {lead, secondary, sections, ticker, scoreboard,
    sources, disclosure} - the same data the email layout receives."""
    if date is None:
        date = date_cls.today()

    lead = digest.get("lead")
    secondary = digest.get("secondary") or []
    sections = digest.get("sections") or []
    ticker = digest.get("ticker") or []
    scoreboard = digest.get("scoreboard") or []
    sources = digest.get("sources") or []
    disclosure = digest.get("disclosure")

    section_names = ", ".join(s.get("name", "") for s in sections if s.get("name"))
    date_str = date.strftime("%A, %d %B %Y")

    body = (
        '<div class="page">'
        f'<h1 class="masthead">{_esc(title)}</h1>'
        '<div class="metabar">'
        f'<span>{_esc(date_str)}</span>'
        f'<span>{_esc(section_names)}</span>'
        f'<span>{_esc(tagline) if tagline else "Compiled by an AI agent from public reports"}</span>'
        "</div>"
        + _ticker_html(ticker)
        + '<div class="leadgrid">'
        f'<div class="col leadcol">{_lead_html(lead)}</div>'
        f'<div class="col">{_secondary_html(secondary)}</div>'
        "</div>"
        + f'<div class="briefsgrid">{"".join(_section_column_html(s) for s in sections)}</div>'
        + _scoreboard_html(scoreboard)
        + _footer_html(sources, disclosure)
        + "</div>"
    )

    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{_esc(title)}</title>"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        f'<link href="{_FONTS_HREF}" rel="stylesheet">'
        f"<style>{_STYLE}</style>"
        "</head><body>" + body + "</body></html>"
    )

"""email_components.py - small, generic HTML-building helpers shared by
email_render.py and email_data_panels.py.

Split out of email_render.py as a pure refactor (no behavior change):
these are the low-level building blocks (escaping, links, kickers,
headlines, paragraphs, the 2-up hybrid layout helper, section bars,
preheader/masthead, the footer/button) with no knowledge of the
top-level content assembly or the ticker/scoreboard data panels.
"""
import html

from render.newsletter_render import follows_text, kicker_parts, safe_url, sentence_ends

_INK = "#1b1a17"
_ACCENT = "#7a1f12"
_MUTED = "#4b4840"

_SERIF = "Georgia,'Times New Roman',Times,serif"
_SANS = "-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

_COL_WIDTH = 352  # hybrid column max-width: 2 x 352 + 16 gutter = 720

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


def _highlight_daily(title: str) -> str:
    """`title` escaped, with the first case-insensitive whole-word match
    of "Daily" picked out in the accent colour - matches the masthead
    style used elsewhere in this project. No match -> plain escaped text."""
    import re
    escaped = _esc(title.upper())
    pattern = re.compile(r"\bDAILY\b", re.IGNORECASE)
    return pattern.sub(lambda m: f'<span style="color:{_ACCENT};">{m.group(0)}</span>', escaped, count=1)


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

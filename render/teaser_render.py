"""teaser_render.py - the teaser email renderer: links out to the web
edition instead of rendering every story inline. Used (see delivery.py)
only when DIGEST_WEB_BASE_URL is set; same table-based/inline-style/serif-
stack conventions as web_edition_render.py's render_html - no web fonts,
everything escaped, every href through safe_url.
"""
import html

from render.summary_text import _ACCENT, _CARD_GAP, _SERIF, _kicker_html, safe_url
from render.web_edition_render import (
    CONTENT_WIDTH, _HERO_GAP, _INK, _MEDIA_QUERY_CSS, _PAPER, _SANS,
    _band, _join_sections, _masthead_html, footer_band,
)


def _teaser_secondary_html(item: dict, safe_web_url: str) -> str:
    headline = html.escape(str(item.get("headline", "")))
    href = html.escape(safe_web_url, quote=True) if safe_web_url != "#" else None
    headline_html = (
        f'<a href="{href}" style="color:{_INK};text-decoration:none;font-weight:700;">{headline}</a>'
        if href else f'<span style="font-weight:700;">{headline}</span>'
    )
    return (
        f'<div style="padding:{_CARD_GAP}px 0;">'
        + _kicker_html(item, 10)
        + f'<div style="font-family:{_SERIF};font-size:15px;line-height:1.3;">{headline_html}</div>'
        + '</div>'
    )


def _teaser_button_html(safe_web_url: str) -> str:
    href = html.escape(safe_web_url, quote=True) if safe_web_url != "#" else "#"
    return _band(
        '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 auto;"><tr>'
        f'<td style="background:{_ACCENT};border-radius:4px;">'
        f'<a href="{href}" style="display:inline-block;padding:12px 28px;font-family:{_SANS};'
        f'font-size:13px;font-weight:700;letter-spacing:.04em;color:#ffffff;text-decoration:none;'
        f'text-transform:uppercase;">Read today&#x27;s front page &#8594;</a>'
        '</td></tr></table>'
    )


def render_teaser_html(front_page: dict, title: str = "The Daily Digest",
                        tagline: str | None = None, web_url: str = "") -> str:
    """A short email that links out to the web edition instead of
    rendering every story inline: masthead, the lead's headline + dek,
    secondary headlines, and a button to `web_url`. Used when
    DIGEST_WEB_BASE_URL is set - otherwise render_html is used unchanged."""
    lead = front_page.get("lead")
    secondary = front_page.get("secondary") or []
    sections = front_page.get("sections") or []
    count = (1 if lead else 0) + len(secondary) + sum(len(s.get("briefs") or []) for s in sections)

    safe_web_url = safe_url(web_url)

    lead_html = ""
    if lead:
        headline = html.escape(str(lead.get("headline", "")))
        dek = html.escape(str(lead.get("dek", "")))
        href = html.escape(safe_web_url, quote=True) if safe_web_url != "#" else None
        headline_html = (
            f'<a href="{href}" style="color:{_INK};text-decoration:none;">{headline}</a>' if href else headline
        )
        lead_html = _band(
            _kicker_html(lead, 11)
            + f'<div style="font-family:{_SERIF};font-size:26px;line-height:1.22;font-weight:700;">'
            f'{headline_html}</div>'
            + (
                f'<div style="font-family:{_SERIF};font-size:14px;font-style:italic;'
                f'color:#3a3a3a;margin-top:{_HERO_GAP}px;">{dek}</div>'
                if dek else ""
            )
        )

    secondary_html = ""
    if secondary:
        secondary_html = _band("".join(_teaser_secondary_html(s, safe_web_url) for s in secondary))

    body = _join_sections([
        _masthead_html(count, title, tagline),
        lead_html,
        secondary_html,
        _teaser_button_html(safe_web_url),
        footer_band(),
    ])

    return (
        "<!doctype html>"
        '<html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<style>{_MEDIA_QUERY_CSS}</style>"
        '</head><body style="margin:0;padding:0;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{_PAPER}" '
        f'style="width:100%;background:{_PAPER};border-collapse:collapse;"><tr><td align="center">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="width:100%;max-width:{CONTENT_WIDTH}px;"><tr><td style="padding:24px 0;font-family:{_SANS};color:{_INK};">'
        + body +
        '</td></tr></table>'
        '</td></tr></table>'
        '</body></html>'
    )


def render_teaser_text(front_page: dict, title: str = "The Daily Digest", web_url: str = "") -> str:
    """Plain-text alternative for render_teaser_html."""
    lead = front_page.get("lead")
    secondary = front_page.get("secondary") or []

    lines = [str(title), ""]
    if lead:
        lines.append(str(lead.get("headline", "")))
        if lead.get("dek"):
            lines.append(str(lead["dek"]))
        lines.append("")
    if secondary:
        lines.append("Also today:")
        for item in secondary:
            lines.append(f"- {item.get('headline', '')}")
        lines.append("")
    lines.append(f"Read today's front page: {web_url}")
    return "\n".join(lines)

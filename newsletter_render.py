"""newsletter_render.py - the HTML/text layout engine for the digest.

ONE adaptive front-page layout, not a choice of styles: masthead -> hero ->
a grid of up to MAX_CARDS-1 cards (weight-3 stories first, then weight-2,
packed into rows of 3 that never leave a lone card) -> a 2-column brief
list for everything else -> a footer. Every band is a full-width table so
columns inside it always end together, and a thin rule separates each
major section. The model never chooses layout - it only supplies "lead"
and "weight"; everything else here is deterministic.
"""
import html
import re
from datetime import date
from urllib.parse import urlparse

_SERIF = "Georgia, 'Times New Roman', Times, serif"
_SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_INK = "#1a1a1a"
_ACCENT = "#8a1f1f"
_PAPER = "#faf6ec"
_MUTED = "#6b6456"
_RULE = "#ece6d8"

_SIDE_PAD = 20   # the one place horizontal page padding is applied
_GUTTER = 12     # padding on each side of a column rule
_BAND_GAP = 16   # vertical space after each band (compact, per the redesign)
_CARD_GAP = 4    # vertical space between a card's own headline/summary/read-more
_HERO_GAP = 8    # vertical space between the hero's headline/summary/read-more

MAX_CARDS = 9    # hero included - at most 8 more cards in the grid
CONTENT_WIDTH = 760  # overall canvas; wider than the traditional 600-640px
                     # email-safe max specifically to give the hero two
                     # flanking columns (hero_flanked) without shrinking the
                     # hero itself - still within what modern clients (Gmail,
                     # Apple Mail, Outlook.com, mobile) render without
                     # clipping; older Outlook desktop is the main risk.

# Summary word caps applied at render time (clamp_summary), matching what
# the SYSTEM prompt asks the model for - a safety net, not a re-prompt.
_SUMMARY_LIMITS = {"lead": 90, 3: 55, 2: 30, 1: 20}

_MEDIA_QUERY_CSS = (
    "@media (max-width:480px){"
    # box-sizing:border-box is load-bearing here: without it, width:100% plus
    # 16px+16px of padding renders 32px WIDER than the viewport (padding adds
    # on top of 100% in the default content-box model) - that's the exact
    # overflow this fixes, not just a tidiness nicety.
    f".col{{display:block !important;width:100% !important;box-sizing:border-box !important;"
    f"border-left:none !important;border-top:1px solid {_RULE} !important;"
    f"padding:{_BAND_GAP}px 16px 0 !important;margin-top:{_BAND_GAP}px !important;}}"
    # Stacked columns lose the vertical rule that separates them side by
    # side on desktop; the border-top above replaces it so consecutive
    # stacked cards (e.g. one card's read-more right above the next card's
    # kicker) still read as visually distinct, not run together.
    "}"
)


def safe_url(url: str) -> str:
    """Return the url if it's http(s), else a harmless placeholder."""
    if isinstance(url, str) and (url.startswith("http://") or url.startswith("https://")):
        return url
    return "#"


def _read_more_link(url: str) -> str:
    """'Read more at {domain} ->'. Link text is built in code, never taken
    from the model. Omitted entirely if the url isn't http(s)."""
    safe = safe_url(url)
    if safe == "#":
        return ""
    domain = urlparse(safe).netloc
    if domain.startswith("www."):
        domain = domain[4:]
    href = html.escape(safe, quote=True)
    label = html.escape(f"Read more at {domain} →")
    # Deliberately NOT the same colour/weight as _kicker_html: on mobile a
    # card's read-more sits directly above the next card's kicker once the
    # column rule that used to separate them is gone, and two bold accent-
    # coloured labels back to back read as one blurred line.
    return (
        f'<a href="{href}" style="color:{_MUTED};text-decoration:underline;'
        f'font-size:11px;font-weight:600;">{label}</a>'
    )


def _snippet_note(story: dict, size_px: int = 11) -> str:
    if story.get("basis") != "snippet":
        return ""
    return (
        f' <span style="color:{_MUTED};font-size:{size_px}px;font-style:italic;">'
        '(based on a search snippet only)</span>'
    )


def _kicker_text(story: dict) -> str:
    """Plain escaped kicker text: the topic, "UPDATE", or "UPDATE · TOPIC".
    "" if there's nothing to show - never a dangling "·" with no topic
    after it."""
    topic = html.escape(str(story.get("topic", "")).upper())
    is_update = story.get("update_of") is not None
    if is_update and topic:
        return f"UPDATE &middot; {topic}"
    if is_update:
        return "UPDATE"
    return topic


def _kicker_html(story: dict, size_px: int) -> str:
    text = _kicker_text(story)
    if not text:
        return ""
    return (
        f'<div style="font-size:{size_px}px;font-weight:700;letter-spacing:2px;'
        f'color:{_ACCENT};margin-bottom:{_CARD_GAP}px;">{text}</div>'
    )


def _first_sentence(text: str, limit: int = 140) -> str:
    """First sentence of text, or the first ~140 chars + an ellipsis if
    there's no sentence-ending punctuation at all."""
    match = re.search(r"[.!?](?:\s|$)", text)
    if match:
        return text[:match.end()].strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def clamp_summary(text: str, max_words: int) -> str:
    """Cut `text` to at most `max_words` words, preferring to stop at the
    last sentence boundary within that limit; falls back to a hard cut plus
    an ellipsis. Render-time only - stored text and the .md stay full."""
    words = text.split()
    if len(words) <= max_words:
        return text
    truncated = " ".join(words[:max_words])
    last_boundary = None
    for m in re.finditer(r"[.!?](?:\s|$)", truncated):
        last_boundary = m
    if last_boundary:
        return truncated[:last_boundary.end()].strip()
    return truncated.rstrip() + "…"


def _tier_of(story: dict) -> int:
    weight = story.get("weight")
    if isinstance(weight, bool) or not isinstance(weight, int) or weight not in (1, 2, 3):
        return 2
    return weight


# --- band-level table wrappers: the one place side padding/gutters live ---

def _band(inner_html: str) -> str:
    """A full-width, single-cell band. Side padding applied once, here."""
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="width:100%;border-collapse:collapse;margin-bottom:{_BAND_GAP}px;"><tr>'
        f'<td style="padding:0 {_SIDE_PAD}px;">{inner_html}</td>'
        '</tr></table>'
    )


def _band_cols(cells_html: list[str], widths: list[int] | None = None,
                outer_pad: int = _SIDE_PAD, margin_bottom: int = _BAND_GAP) -> str:
    """A full-width band split into columns, with a 1px vertical rule and a
    gutter on each side between them. `outer_pad` is the padding at the
    band's own outer edges (left of the first cell, right of the last) -
    defaults to the page-level side padding; pass 0 when this band is
    nested inside another band's cell, so padding doesn't double up.
    `margin_bottom` likewise defaults to the normal inter-band gap, but
    should be 0 when nested (the outer band already provides it)."""
    n = len(cells_html)
    if widths is None:
        widths = [100 // n] * n
    tds = []
    for i, cell in enumerate(cells_html):
        pad_l = outer_pad if i == 0 else _GUTTER
        pad_r = outer_pad if i == n - 1 else _GUTTER
        border = f"border-left:1px solid {_RULE};" if i > 0 else ""
        tds.append(
            f'<td valign="top" class="col" style="width:{widths[i]}%;{border}'
            f'padding:0 {pad_r}px 0 {pad_l}px;">{cell}</td>'
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="width:100%;border-collapse:collapse;margin-bottom:{margin_bottom}px;"><tr>'
        + "".join(tds) + '</tr></table>'
    )


def _rule_html() -> str:
    """A thin horizontal rule, used between major sections only."""
    return _band(f'<div style="border-top:1px solid {_RULE};"></div>')


def _join_sections(sections: list[str]) -> str:
    """Join the masthead/hero/grid/briefs/footer with a rule between each
    non-empty one. Skips empty sections instead of leaving a bare rule."""
    parts: list[str] = []
    for section in sections:
        if not section:
            continue
        if parts:
            parts.append(_rule_html())
        parts.append(section)
    return "".join(parts)


# --- hero ---

def _hero_content_html(hero: dict) -> str:
    """The hero's own text HTML: kicker, headline, summary, read-more."""
    headline = html.escape(str(hero.get("headline", "")))
    summary = html.escape(clamp_summary(str(hero.get("summary", "")), _SUMMARY_LIMITS["lead"]))
    read_more = _read_more_link(hero.get("url", ""))
    return (
        _kicker_html(hero, 11)
        + f'<div style="font-family:{_SERIF};font-size:26px;line-height:1.22;'
        f'font-weight:700;color:{_INK};">{headline}</div>'
        + f'<div style="font-family:{_SERIF};font-size:14px;line-height:1.5;color:#3a3a3a;margin-top:{_HERO_GAP}px;">'
        + summary + _snippet_note(hero, 12) + '</div>'
        + (f'<div style="margin-top:{_HERO_GAP}px;">{read_more}</div>' if read_more else "")
    )


def hero_band(hero: dict) -> str:
    """Full-width hero: _hero_content_html, wrapped as its own band."""
    return _band(_hero_content_html(hero))


def _flank_entry(story: dict) -> str:
    """Compact kicker + linked headline for a hero-flanking column - too
    narrow for a summary."""
    kicker_html = _kicker_html(story, 9)
    headline = html.escape(str(story.get("headline", "")))
    safe = safe_url(story.get("url", ""))
    if safe != "#":
        headline_html = (
            f'<a href="{html.escape(safe, quote=True)}" style="color:{_INK};'
            f'text-decoration:none;font-weight:700;">{headline}</a>'
        )
    else:
        headline_html = f'<span style="font-weight:700;">{headline}</span>'
    return kicker_html + f'<div style="font-family:{_SERIF};font-size:13px;line-height:1.3;">{headline_html}</div>'


def hero_flanked(hero: dict, flank_left: dict, flank_right: dict) -> str:
    """The hero with one compact story column flanking it on each side.
    Only used when the wider canvas (see render_html) has two spare brief-
    tier stories to flank with - the hero's own proportions are unchanged
    from hero_band; the flanks use the extra width the wider canvas adds,
    not space taken out of the hero."""
    return _band_cols(
        [_flank_entry(flank_left), _hero_content_html(hero), _flank_entry(flank_right)],
        widths=[15, 70, 15],
    )


# --- grid ---

def _grid_card(story: dict, headline_px: int, summary_limit: int) -> str:
    headline = html.escape(str(story.get("headline", "")))
    summary = html.escape(clamp_summary(str(story.get("summary", "")), summary_limit))
    read_more = _read_more_link(story.get("url", ""))
    return (
        _kicker_html(story, 10)
        + f'<div style="font-family:{_SERIF};font-size:{headline_px}px;line-height:1.3;'
        f'font-weight:700;color:{_INK};">{headline}</div>'
        + f'<div style="font-family:{_SERIF};font-size:13px;line-height:1.45;color:#3a3a3a;margin-top:{_CARD_GAP}px;">'
        + summary + _snippet_note(story) + '</div>'
        + (f'<div style="margin-top:{_CARD_GAP}px;">{read_more}</div>' if read_more else "")
    )


def _grid_row_html(cards: list[dict]) -> str:
    """One grid row."""
    cells = [
        _grid_card(
            c,
            headline_px=17 if _tier_of(c) == 3 else 15,
            summary_limit=_SUMMARY_LIMITS[_tier_of(c)],
        )
        for c in cards
    ]
    return _band_cols(cells)


def _pack_rows(cards: list[dict]) -> tuple[list[list[dict]], list[dict]]:
    """Pack cards into rows of 3, never leaving a lone card: a remainder of
    1 overall sends that single card to the brief list instead; a remainder
    of 1 after full rows of 3 (n % 3 == 1) turns the last 4 cards into two
    rows of 2; a remainder of 2 (n % 3 == 2) becomes one final row of 2.
    Returns (rows, cards_moved_to_the_brief_list)."""
    n = len(cards)
    if n == 0:
        return [], []
    if n == 1:
        return [], list(cards)

    rows: list[list[dict]] = []
    if n % 3 == 1:
        head, tail = cards[:n - 4], cards[n - 4:]
        rows.extend(head[i:i + 3] for i in range(0, len(head), 3))
        rows.append(tail[:2])
        rows.append(tail[2:])
    elif n % 3 == 2:
        head, tail = cards[:n - 2], cards[n - 2:]
        rows.extend(head[i:i + 3] for i in range(0, len(head), 3))
        rows.append(tail)
    else:
        rows.extend(cards[i:i + 3] for i in range(0, n, 3))

    return rows, []


# --- brief list ---

def _brief_entry(story: dict) -> str:
    """"KICKER · linked headline ->", headline only - no summary."""
    kicker_text = _kicker_text(story)
    headline = html.escape(str(story.get("headline", "")))
    safe = safe_url(story.get("url", ""))
    if safe != "#":
        headline_html = (
            f'<a href="{html.escape(safe, quote=True)}" style="color:{_INK};'
            f'text-decoration:none;font-weight:700;">{headline} &#8594;</a>'
        )
    else:
        headline_html = f'<span style="font-weight:700;">{headline} &#8594;</span>'
    kicker_html = (
        f'<span style="color:{_ACCENT};font-weight:700;">{kicker_text}</span> &middot; '
        if kicker_text else ""
    )
    return (
        f'<div style="font-family:{_SERIF};font-size:14px;line-height:1.4;padding:{_CARD_GAP}px 0;">'
        f'{kicker_html}{headline_html}</div>'
    )


def brief_list_band(stories: list[dict]) -> str:
    """Weight-1 + grid overflow, in 2 columns. Items alternate between
    columns so column heights differ by at most 1. "" if there's nothing
    left to show - the band is skipped entirely rather than rendered empty.
    A single leftover story gets one full-width column instead of a
    2-column band with an empty second cell."""
    if not stories:
        return ""
    if len(stories) == 1:
        return _band(_brief_entry(stories[0]))
    left = [s for i, s in enumerate(stories) if i % 2 == 0]
    right = [s for i, s in enumerate(stories) if i % 2 == 1]
    left_html = "".join(_brief_entry(s) for s in left)
    right_html = "".join(_brief_entry(s) for s in right)
    return _band_cols([left_html, right_html])


def footer_band() -> str:
    return _band(
        f'<div style="font-family:{_SERIF};font-size:12px;font-style:italic;'
        f'color:{_MUTED};text-align:center;">That&#x27;s everything for today.</div>'
    )


def _highlight_word(text: str, word: str) -> str:
    """Escaped `text` with the first case-insensitive whole-word match of
    `word` wrapped in an accent-coloured span. No match -> plain escaped text."""
    escaped = html.escape(text)
    pattern = re.compile(rf'\b{re.escape(word)}\b', re.IGNORECASE)
    return pattern.sub(lambda m: f'<span style="color:{_ACCENT};">{m.group(0)}</span>', escaped, count=1)


def _masthead_html(count: int, title: str, tagline: str | None) -> str:
    """4px ink rule, title ("Daily" picked out in the accent colour, if
    present), a one-line italic tagline, a double rule (two 1px rules 2px
    apart), then the date + story count."""
    today_str = html.escape(date.today().strftime("%A, %d %B %Y").upper())
    plural = "STORY" if count == 1 else "STORIES"
    tagline_html = (
        f'<div style="font-family:{_SERIF};font-size:12px;font-style:italic;'
        f'color:{_MUTED};margin-top:4px;white-space:nowrap;overflow:hidden;'
        f'text-overflow:ellipsis;">{html.escape(tagline)}</div>'
        if tagline else ""
    )
    return _band(
        f'<div style="border-top:4px solid {_INK};margin-bottom:10px;"></div>'
        '<div style="text-align:center;">'
        f'<div style="font-family:{_SERIF};font-weight:700;font-size:30px;letter-spacing:1px;color:{_INK};">'
        f'{_highlight_word(title.upper(), "DAILY")}</div>'
        + tagline_html +
        '</div>'
        f'<div style="border-top:1px solid {_INK};margin:10px 0 2px;"></div>'
        f'<div style="border-top:1px solid {_INK};margin:0 0 6px;"></div>'
        f'<div style="text-align:center;font-size:11px;letter-spacing:2px;color:{_MUTED};">'
        f'{today_str} &middot; {count} {plural}</div>'
    )


def render_html(stories: list[dict], title: str = "The Daily Digest", tagline: str | None = None) -> str:
    """Render the digest as a full HTML document: masthead, hero, a grid of
    weight-3/weight-2 stories packed into rows that never leave a lone
    card, a 2-column brief list for the rest, and a footer - each separated
    by a thin rule. Inline styles everywhere; the one <style> block holds
    the mobile column-stacking rules."""
    if not stories:
        return ""

    marked = [s for s in stories if s.get("lead") is True]
    hero = marked[0] if len(marked) == 1 else stories[0]
    pool = [s for s in stories if s is not hero]

    majors, standards, briefs = [], [], []
    for s in pool:
        tier = _tier_of(s)
        (majors if tier == 3 else standards if tier == 2 else briefs).append(s)

    grid_candidates = majors + standards
    grid_pool, overflow = grid_candidates[:MAX_CARDS - 1], grid_candidates[MAX_CARDS - 1:]
    rows, moved_to_brief = _pack_rows(grid_pool)
    briefs = briefs + overflow + moved_to_brief

    # Flank the hero with two brief-tier stories when there are enough to
    # spare - uses the wider canvas's extra width, not space taken from
    # the hero itself. Falls back to the plain hero band otherwise.
    if len(briefs) >= 2:
        flank_left, flank_right, *briefs = briefs
        hero_html = hero_flanked(hero, flank_left, flank_right)
    else:
        hero_html = hero_band(hero)

    body = _join_sections([
        _masthead_html(len(stories), title, tagline),
        hero_html,
        "".join(_grid_row_html(row) for row in rows),
        brief_list_band(briefs),
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


def render_text(stories: list[dict]) -> str:
    """Render the digest as plain text, grouped by topic in story order."""
    topic_order = list(dict.fromkeys(s.get("topic", "") for s in stories))
    grouped: dict[str, list[dict]] = {}
    for s in stories:
        grouped.setdefault(s.get("topic", ""), []).append(s)

    lines = []
    for topic in topic_order:
        lines.append(str(topic))
        lines.append("=" * len(str(topic)))
        for story in grouped[topic]:
            lines.append(str(story.get("headline", "")))
            lines.append(str(story.get("summary", "")))
            lines.append(str(story.get("url", "")))
            lines.append("")

    return "\n".join(lines)


# --- teaser email: links out to the web edition instead of rendering
# every story inline. Used (see delivery.py) only when DIGEST_WEB_BASE_URL
# is set; same table-based/inline-style/serif-stack conventions as
# render_html above - no web fonts, everything escaped, every href through
# safe_url.

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

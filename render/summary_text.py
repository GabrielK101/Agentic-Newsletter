"""summary_text.py - text/date/kicker/summary utilities shared by every
newsletter_render renderer (the web edition, the teaser email, and
callers outside this package like agent_loop.py/digest.py/email_render.py/
webpage.py). No HTML-table layout lives here - just the pure string/date
logic and the small inline-style snippets (kicker, "Follows:" line,
read-more link) that are reused verbatim by more than one renderer.
"""
import html
import re
from datetime import date, datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

# A handful of CSS tokens are needed by the helpers below (kicker/follows/
# read-more/snippet-note inline styles). The rest of the shared CSS/layout
# constants live in web_edition_render.py, which is the main consumer of
# them; teaser_render.py imports whichever subset it needs from there.
_SERIF = "Georgia, 'Times New Roman', Times, serif"
_ACCENT = "#8a1f1f"
_MUTED = "#6b6456"
_CARD_GAP = 4    # vertical space between a card's own headline/summary/read-more

# Summary word limits: a floor (below which a summary says too little to
# be worth keeping - dropped, never padded) and per-tier ceilings (render-
# time safety net matching what the SYSTEM prompt asks the model for).
# Enforced first at parse time (agent_loop.py's parse_digest, and
# digest.py's prepare_front_page so --fixture digests get the same
# treatment as real model output), then again here at render time.
SUMMARY_WORD_FLOOR = 8
# Upper bound of each field's word range in the SYSTEM/EDIT_SYSTEM prompts
# (lead body 70-100, secondary 35-60, brief 25-35) - kept aligned with the
# prompts so clamp_summary's sentence-boundary truncation never actually
# triggers on a well-behaved reply; it's a safety net, not the normal path.
SUMMARY_CEILING_HERO = 100
SUMMARY_CEILING_MAJOR = 60
SUMMARY_CEILING_BRIEF = 35

LONDON_TZ = ZoneInfo("Europe/London")


def safe_url(url: str) -> str:
    """Return the url if it's http(s), else a harmless placeholder."""
    if isinstance(url, str) and (url.startswith("http://") or url.startswith("https://")):
        return url
    return "#"


def _parse_published(value) -> date | None:
    """`value` as an ISO date or datetime string -> a date, defensively -
    None if missing or unparseable. Never infers a date from anything
    else (today, a neighbouring story, ...) - no date in means no date
    shown, not "assume today"."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(LONDON_TZ)
    return parsed.date()


def format_relative_date(published, today: date | None = None) -> str:
    """"Today" / "Yesterday" / "Thu 19 Nov" for `published` (an ISO date
    or datetime string), relative to `today` (Europe/London's current
    date if not given) - or "" if `published` is missing or unparseable.
    Anything older than yesterday gets the explicit weekday+day+month
    form, so a stale item is never silently indistinguishable from a
    fresh one."""
    parsed = _parse_published(published)
    if parsed is None:
        return ""
    if today is None:
        today = datetime.now(LONDON_TZ).date()
    delta = (today - parsed).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Yesterday"
    return f"{parsed.strftime('%a')} {parsed.day} {parsed.strftime('%b')}"


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


def kicker_parts(story: dict, show_topic: bool = True) -> list[str]:
    """Escaped, upper-cased kicker segments - the topic (unless
    `show_topic` is False: inside a section, the section heading already
    names it) and a relative date, but only when it's not "Today" (the
    common case, not worth a label for). Shared by every renderer
    (render_html, the web edition, the mobile email) so kicker rules stay
    one single source of truth."""
    parts = []
    if show_topic:
        topic = html.escape(str(story.get("topic", "")).upper())
        if topic:
            parts.append(topic)
    date_label = format_relative_date(story.get("published"))
    if date_label and date_label != "Today":
        parts.append(html.escape(date_label.upper()))
    return parts


def follows_text(story: dict) -> str | None:
    """"Follows: <prior headline>", or None. Relies on story["follows"]
    being pre-resolved (digest.py, against "Already told" history) -
    renderers never resolve ids themselves."""
    prior_headline = story.get("follows")
    if not prior_headline:
        return None
    return f"Follows: {prior_headline}"


def _kicker_text(story: dict, show_topic: bool = True) -> str:
    """Plain escaped kicker text: kicker_parts, joined by " &middot; ".
    "" if there's nothing to show."""
    return " &middot; ".join(kicker_parts(story, show_topic))


def _kicker_html(story: dict, size_px: int, show_topic: bool = True) -> str:
    text = _kicker_text(story, show_topic)
    if not text:
        return ""
    return (
        f'<div style="font-size:{size_px}px;font-weight:700;letter-spacing:2px;'
        f'color:{_ACCENT};margin-bottom:{_CARD_GAP}px;">{text}</div>'
    )


def _follows_html(story: dict, size_px: int = 11) -> str:
    text = follows_text(story)
    if not text:
        return ""
    return (
        f'<div style="font-family:{_SERIF};font-size:{size_px}px;font-style:italic;'
        f'color:{_MUTED};margin-bottom:{_CARD_GAP}px;">{html.escape(text)}</div>'
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


_SENTENCE_END = re.compile(r"""[.!?]["')\]]?(?=\s+["'(\[]?[A-Z0-9]|\s*$)""")
_ABBREVIATIONS = {
    "corp", "inc", "ltd", "plc", "co", "mr", "mrs", "ms", "dr", "st", "jr", "sr",
    "vs", "no", "u.s", "u.k", "e.g", "i.e", "approx", "est", "gov", "sen", "rep",
}


def sentence_ends(text: str):
    """Yield each regex match that really ends a sentence - skips a "."
    that's actually part of an abbreviation (e.g. "X Corp.") or an initial
    (e.g. "J. Smith"), which would otherwise look like a sentence boundary
    and cut the text off mid-thought."""
    for m in _SENTENCE_END.finditer(text):
        if text[m.start()] == ".":
            before = re.search(r"([A-Za-z][A-Za-z.]*)$", text[:m.start()])
            if before:
                word = before.group(1)
                if word.lower().rstrip(".") in _ABBREVIATIONS:
                    continue
                if len(word) == 1 and word.isupper():  # an initial, e.g. "J. Smith"
                    continue
        yield m


def clamp_summary(text: str, max_words: int) -> str:
    """Cut `text` to at most `max_words` words, stopping at the last real
    sentence boundary inside the limit (not a "." that's really part of an
    abbreviation or initial). Falls back to a hard cut plus an ellipsis if
    there's no real boundary. Render-time only - stored text and the .md
    stay full."""
    words = text.split()
    if len(words) <= max_words:
        return text
    truncated = " ".join(words[:max_words])
    last = None
    for m in sentence_ends(truncated):
        last = m
    if last:
        return truncated[:last.end()].strip()
    return truncated.rstrip(" ,;:—-") + "…"


def clean_summary(headline: str, summary: str, ceiling: int) -> str | None:
    """Clamp `summary` to `ceiling` words, then enforce SUMMARY_WORD_FLOOR:
    a summary that short says too little to be worth keeping, so the
    whole item is dropped (None, with a warning naming it by headline) -
    never padded. Shared between agent_loop.py's parse_digest (real model
    output) and digest.py's prepare_front_page, so --fixture digests get
    exactly the same floor/ceiling treatment as a real run."""
    summary = (summary or "").strip()
    if not summary:
        print(f"[dropped: no summary] {headline!r}")
        return None
    clamped = clamp_summary(summary, ceiling)
    if len(clamped.split()) < SUMMARY_WORD_FLOOR:
        print(f"[dropped: summary under {SUMMARY_WORD_FLOOR} words] {headline!r}")
        return None
    return clamped


def _tier_of(story: dict) -> int:
    weight = story.get("weight")
    if isinstance(weight, bool) or not isinstance(weight, int) or weight not in (1, 2, 3):
        return 2
    return weight

"""front_page_schema.py - JSON-extraction-and-validation pipeline for the
model's final reply against the "front page" schema (see system_prompt.py's
## Output section for the shape this parses)."""
import json

from render.newsletter_render import (
    SUMMARY_CEILING_BRIEF, SUMMARY_CEILING_HERO, SUMMARY_CEILING_MAJOR,
    clamp_summary, clean_summary, safe_url,
)

_MAX_WORDS_DEK = 25  # the one-line subhead (prompt: 12-25 words) - not one of the 4 summary tiers
_MAX_SECONDARY = 5
_MAX_SECTIONS = 6
_MAX_BRIEFS_PER_SECTION = 6
_MAX_TICKER = 8
_MAX_SCOREBOARD = 12  # up to 3 groups x 4 entries
_MAX_SOURCES = 12
_DIRECTIONS = {"up", "down", "flat"}


def _clean_str(value, max_words: int | None = None) -> str | None:
    """A non-empty stripped string, optionally clamped to `max_words` - or
    None if `value` isn't a usable string at all."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    return clamp_summary(value, max_words) if max_words is not None else value


def _clean_id(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _clean_story_item(item, ceiling: int) -> dict | None:
    """Shared cleaning for secondary items and section briefs: headline and
    a usable url are required - an item missing either is dropped as
    malformed; the summary is clamped to `ceiling` words and must clear
    SUMMARY_WORD_FLOOR (clean_summary) or the whole item is dropped."""
    if not isinstance(item, dict):
        return None
    headline = _clean_str(item.get("headline"))
    if headline is None:
        return None
    url = safe_url(item.get("url", ""))
    if url == "#":
        return None
    summary = clean_summary(headline, item.get("summary", ""), ceiling)
    if summary is None:
        return None
    return {
        "headline": headline,
        "summary": summary,
        "url": url,
        "published": item.get("published") if isinstance(item.get("published"), str) else None,
        "update_of": _clean_id(item.get("update_of")),
    }


_VALID_BASIS = {"article", "snippet"}


def _clean_basis(value) -> str | None:
    """Normalize to "article"/"snippet", or None for anything else -
    structural cleaning only. Whether a "snippet" basis is allowed is a
    business rule enforced in digest.py's prepare_front_page, not here."""
    return value if value in _VALID_BASIS else None


def _clean_lead(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    headline = _clean_str(raw.get("headline"))
    if headline is None:
        return None
    url = safe_url(raw.get("url", ""))
    if url == "#":
        return None
    body = clean_summary(headline, raw.get("body", ""), SUMMARY_CEILING_HERO)
    if body is None:
        return None
    sources_raw = raw.get("sources")
    sources = [s.strip() for s in sources_raw if isinstance(s, str) and s.strip()] if isinstance(sources_raw, list) else []
    return {
        "topic": _clean_str(raw.get("topic")) or "",
        "headline": headline,
        "dek": _clean_str(raw.get("dek"), _MAX_WORDS_DEK) or "",
        "body": body,
        "url": url,
        "sources": sources[:8],
        "basis": _clean_basis(raw.get("basis")),
        "published": raw.get("published") if isinstance(raw.get("published"), str) else None,
        "update_of": _clean_id(raw.get("update_of")),
    }


def _clean_secondary_item(raw) -> dict | None:
    cleaned = _clean_story_item(raw, SUMMARY_CEILING_MAJOR)
    if cleaned is None:
        return None
    cleaned["topic"] = _clean_str(raw.get("topic")) or ""
    cleaned["basis"] = _clean_basis(raw.get("basis")) if isinstance(raw, dict) else None
    return cleaned


def _clean_section(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    name = _clean_str(raw.get("name"))
    if name is None:
        return None
    briefs = []
    if isinstance(raw.get("briefs"), list):
        for b in raw["briefs"][:_MAX_BRIEFS_PER_SECTION]:
            cleaned = _clean_story_item(b, SUMMARY_CEILING_BRIEF)
            if cleaned is not None:
                briefs.append(cleaned)
    return {"name": name, "briefs": briefs}


def _clean_ticker_item(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    label = _clean_str(raw.get("label"))
    value = _clean_str(raw.get("value"))
    if label is None or value is None:
        return None
    direction = raw.get("direction")
    return {
        "label": label,
        "value": value,
        "change": _clean_str(raw.get("change")) or "",
        "direction": direction if direction in _DIRECTIONS else None,
    }


def _clean_scoreboard_item(raw) -> dict | None:
    """"group" (the sport/competition a panel renders under) defaults to
    "Results" when missing - "label" (an optional short sub-label within
    the group) may legitimately be "" for a plain match result; "line" is
    the only field that's actually required."""
    if not isinstance(raw, dict):
        return None
    line = _clean_str(raw.get("line"))
    if line is None:
        return None
    group = _clean_str(raw.get("group")) or "Results"
    label = raw.get("label")
    label = label.strip() if isinstance(label, str) else ""
    return {"group": group, "label": label, "line": line}


def _clean_source_item(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    name = _clean_str(raw.get("name"))
    if name is None:
        return None
    url = raw.get("url")
    url = safe_url(url) if isinstance(url, str) else "#"
    return {"name": name, "url": None if url == "#" else url}


def parse_digest(raw_text: str) -> dict | None:
    """Parse and defensively validate the model's final reply against the
    front-page schema: {lead, secondary, sections, ticker, scoreboard,
    sources, disclosure, notes}. Only "lead" is required; every other
    field is optional and malformed items are dropped individually rather
    than failing the whole parse. Returns None if the reply isn't valid
    JSON, isn't an object, or has no usable lead - text-level escaping
    happens later, at render time, not here."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()

    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        raw = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None

    lead = _clean_lead(raw.get("lead"))
    if lead is None:
        return None

    secondary = []
    if isinstance(raw.get("secondary"), list):
        for item in raw["secondary"][:_MAX_SECONDARY]:
            cleaned = _clean_secondary_item(item)
            if cleaned is not None:
                secondary.append(cleaned)

    sections = []
    if isinstance(raw.get("sections"), list):
        for item in raw["sections"][:_MAX_SECTIONS]:
            cleaned = _clean_section(item)
            if cleaned is not None:
                sections.append(cleaned)

    ticker = []
    if isinstance(raw.get("ticker"), list):
        for item in raw["ticker"][:_MAX_TICKER]:
            cleaned = _clean_ticker_item(item)
            if cleaned is not None:
                ticker.append(cleaned)

    scoreboard = []
    if isinstance(raw.get("scoreboard"), list):
        for item in raw["scoreboard"][:_MAX_SCOREBOARD]:
            cleaned = _clean_scoreboard_item(item)
            if cleaned is not None:
                scoreboard.append(cleaned)

    sources = []
    if isinstance(raw.get("sources"), list):
        for item in raw["sources"][:_MAX_SOURCES]:
            cleaned = _clean_source_item(item)
            if cleaned is not None:
                sources.append(cleaned)

    disclosure = raw.get("disclosure")
    disclosure = disclosure.strip() if isinstance(disclosure, str) and disclosure.strip() else None

    notes = raw.get("notes")
    notes = notes.strip() if isinstance(notes, str) else ""

    return {
        "lead": lead,
        "secondary": secondary,
        "sections": sections,
        "ticker": ticker,
        "scoreboard": scoreboard,
        "sources": sources,
        "disclosure": disclosure,
        "notes": notes,
    }

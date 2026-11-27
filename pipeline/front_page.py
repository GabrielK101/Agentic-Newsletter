"""front_page.py - pure front-page-assembly business logic for the digest.

Takes the model's (or fixture's) raw digest dict plus the lookback cutoff
and config, and applies every content-safety/freshness/quality filter
before anything can appear in the rendered digest. No I/O beyond the
read-only db.seen_url check; no model/email/network calls.
"""
import json
from urllib.parse import urlparse

from db import seen_url
from render.newsletter_render import SUMMARY_CEILING_BRIEF, SUMMARY_CEILING_HERO, SUMMARY_CEILING_MAJOR, clean_summary
from sources import market_data
from sources import sports_data


def _lead_summary(lead: dict) -> str:
    """The lead's dek + body joined into one block - used both as the
    HTML/text renderer's "summary" for the hero card and as what gets
    stored for future "Already told" context. Falls back to "summary"
    for a promoted secondary/brief (see prepare_front_page), which has
    that field instead of dek/body."""
    joined = " ".join(part for part in (lead.get("dek", ""), lead.get("body", "")) if part).strip()
    return joined or str(lead.get("summary", "")).strip()


def _is_fresh_and_new(item: dict, cutoff: str) -> bool:
    """A story is usable only if it isn't older than the lookback window
    (or carries no date at all) and its url hasn't already been told."""
    published = item.get("published")
    if published and published < cutoff:
        return False
    return bool(item.get("url")) and not seen_url(item["url"])


# Low-trust domains: social platforms, not primary reporting - a story
# citing one of these as its only source is dropped outright, never
# rendered. Matches the domain itself and any subdomain (e.g. m.facebook.com).
DENYLIST_DOMAINS = frozenset({
    "facebook.com", "x.com", "twitter.com", "instagram.com",
    "tiktok.com", "reddit.com", "youtube.com",
})


def _is_denylisted(url: str) -> bool:
    host = urlparse(url or "").netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host in DENYLIST_DOMAINS or any(host.endswith("." + d) for d in DENYLIST_DOMAINS)


def _passes_domain_check(item: dict) -> bool:
    """False (drop the item) if its url is on DENYLIST_DOMAINS - applies
    to every story (lead, secondary, brief)."""
    url = item.get("url", "")
    if _is_denylisted(url):
        print(f"[dropped: low-trust domain] {item.get('headline', '')!r} ({url})")
        return False
    return True


def _passes_basis_check(item: dict) -> bool:
    """False (drop the item) if "basis" is "snippet" - the lead and every
    secondary (weight-3) story must be based on the fetched article, never
    just a headline or search snippet. Never downgrades; drops outright.
    Briefs don't carry a "basis" field, so this is a no-op for them."""
    if item.get("basis") == "snippet":
        print(f"[dropped: snippet basis not allowed for lead/secondary] {item.get('headline', '')!r}")
        return False
    return True


def _code_ticker_and_scoreboard(config: dict) -> tuple[list[dict], list[dict]]:
    """Fetch ticker/scoreboard data directly from code (market_data,
    sports_data) for any topic that configures it - REPLACES the model's
    own ticker/scoreboard outright when non-empty (see __main__). ([], [])
    if no topic enables either, in which case the model's version stands
    (still governed by the SYSTEM prompt's own ticker/scoreboard rules).
    Never called in --fixture mode - these hit real external APIs."""
    ticker, scoreboard = [], []
    for topic in config["topics"]:
        data = topic.get("data") or {}
        if data.get("ticker"):
            ticker.extend(market_data.get_ticker(data["ticker"]))
        for sport in data.get("sports", []):
            if sport == "f1":
                scoreboard.extend(sports_data.get_f1())
            elif sport == "premier_league":
                scoreboard.extend(sports_data.get_football("premier_league", config["lookback_days"]))
    return ticker, scoreboard


def _try_parse_json_reply(text: str):
    """The model's raw JSON reply, parsed - or the raw text itself if it
    doesn't parse, so a malformed reply is still captured in the run
    archive for debugging why, not just silently dropped."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").removeprefix("json").strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(stripped[start:end + 1])
        except json.JSONDecodeError:
            pass
    return text


def _passes_summary_floor(item: dict, field: str, ceiling: int) -> bool:
    """Clamp item[field] to `ceiling` words and enforce the floor
    (clean_summary), mutating item[field] in place with the clamped
    text. False (drop the item) if it's empty or under the floor -
    applied here too (not just agent_loop.py's parse_digest) so a
    --fixture digest gets exactly the same treatment as real model
    output, including the dropped-item warning."""
    cleaned = clean_summary(item.get("headline", ""), item.get(field, ""), ceiling)
    if cleaned is None:
        return False
    item[field] = cleaned
    return True


def _normalize_promoted_lead(item: dict) -> dict:
    """A promoted secondary/brief item (see prepare_front_page) has
    "summary", not "dek"/"body" - give it the shape every lead consumer
    expects (_lead_summary, render_digest, webpage.py's lead block) so it
    renders exactly like a real lead, just without a dek."""
    if "body" in item or "dek" in item:
        return item
    return {**item, "dek": "", "body": item.get("summary", "")}


def _sort_and_filter_sections(sections: list[dict], config: dict) -> list[dict]:
    """Deterministic section order: the configured topic order, then
    "World", then "Worth knowing". Drops any section whose name matches
    neither - a stray/misspelled section name disappears rather than
    sorting to the end."""
    order = [t["name"] for t in config["topics"]] + ["World", "Worth knowing"]
    by_name = {s["name"]: s for s in sections}
    return [by_name[name] for name in order if name in by_name]


def _resolve_follows(items: list[dict], history_by_id: dict) -> None:
    """Mutates each item in place, adding "follows" (the prior story's
    headline, from "Already told" history) when "update_of" resolves to
    something real - None otherwise. Renderers show a "Follows: <prior
    headline>" line only when this is set; they never resolve ids
    themselves."""
    for item in items:
        prior = history_by_id.get(item.get("update_of"))
        item["follows"] = prior["headline"] if prior else None


def prepare_front_page(digest: dict, cutoff: str, config: dict) -> tuple[dict | None, list[dict], list[dict]]:
    """Apply the lookback-days cutoff, the already-seen-url check, the
    low-trust-domain denylist, the article-basis requirement (lead and
    secondary only), and the summary floor/ceiling to every item BEFORE
    it can appear in the digest. The lead must survive all of these; if
    it doesn't, the first surviving secondary item - or, failing that,
    the first surviving brief - is promoted to lead instead. The lead is
    never allowed to be a stale, already-told, low-trust, snippet-basis,
    or under-floor-summary story. Sections come back in deterministic
    (configured topic, then World, then Worth knowing) order."""
    lead = digest.get("lead")
    secondary = [s for s in digest.get("secondary", []) if _is_fresh_and_new(s, cutoff)]
    secondary = [s for s in secondary if _passes_domain_check(s)]
    secondary = [s for s in secondary if _passes_basis_check(s)]
    secondary = [s for s in secondary if _passes_summary_floor(s, "summary", SUMMARY_CEILING_MAJOR)]

    sections = []
    for section in _sort_and_filter_sections(digest.get("sections", []), config):
        briefs = [b for b in section.get("briefs", []) if _is_fresh_and_new(b, cutoff)]
        briefs = [b for b in briefs if _passes_domain_check(b)]
        briefs = [b for b in briefs if _passes_summary_floor(b, "summary", SUMMARY_CEILING_BRIEF)]
        sections.append({"name": section["name"], "briefs": briefs})

    if lead is not None and (
        not _is_fresh_and_new(lead, cutoff)
        or not _passes_domain_check(lead)
        or not _passes_basis_check(lead)
        or not _passes_summary_floor(lead, "body", SUMMARY_CEILING_HERO)
    ):
        lead = None
        if secondary:
            lead, secondary = _normalize_promoted_lead(secondary[0]), secondary[1:]
        else:
            for section in sections:
                if section["briefs"]:
                    lead, section["briefs"] = _normalize_promoted_lead(section["briefs"][0]), section["briefs"][1:]
                    break

    return lead, secondary, sections


def build_render_stories(lead: dict | None, secondary: list[dict], sections: list[dict]) -> list[dict]:
    """Flatten the front page shape into the flat list the existing HTML/
    text renderer expects: lead -> HERO (hero selection keys off
    "lead": True, not weight), secondary -> MAJOR (weight 3), section
    briefs -> BRIEF (weight 1)."""
    stories = []
    if lead is not None:
        stories.append({
            "topic": lead.get("topic", ""),
            "headline": lead["headline"],
            "dek": lead.get("dek", ""),
            "body": lead.get("body", "") or lead.get("summary", ""),
            "summary": _lead_summary(lead),
            "url": lead["url"],
            "published": lead.get("published"),
            "update_of": lead.get("update_of"),
            "follows": lead.get("follows"),
            "lead": True,
            "weight": 3,
        })
    for item in secondary:
        stories.append({
            "topic": item.get("topic", ""),
            "headline": item["headline"],
            "summary": item.get("summary", ""),
            "url": item["url"],
            "published": item.get("published"),
            "update_of": item.get("update_of"),
            "follows": item.get("follows"),
            "lead": False,
            "weight": 3,
        })
    for section in sections:
        for brief in section["briefs"]:
            stories.append({
                "topic": section["name"],
                "headline": brief["headline"],
                "summary": brief.get("summary", ""),
                "url": brief["url"],
                "published": brief.get("published"),
                "update_of": brief.get("update_of"),
                "follows": brief.get("follows"),
                "lead": False,
                "weight": 1,
            })
    return stories

"""edit.py - the model-facing editorial stage of the fixed pipeline.

Takes gather.py/filter.py's shortlisted, fetched candidates and makes ONE
model call (no tools - research is already done) to choose the front
page and write it, referencing each chosen story by candidate id rather
than writing urls/dates/basis itself. Code resolves each id against the
candidate record afterward (url, published, basis, outlet name) and runs
a numeric guard on ticker/scoreboard figures before anything is trusted.

Reuses front_page_schema.py's structural cleaners (_clean_lead etc.) so
the output is the exact same {lead, secondary, sections, ticker,
scoreboard, sources, disclosure, notes} shape agent_loop.parse_digest
produces - everything downstream (front_page.prepare_front_page onward)
is engine-agnostic.
"""
import json
import re
from datetime import datetime, timezone

import anthropic

import pipeline.front_page_schema as fps
from pipeline.agent_loop import MODEL
from pipeline.system_prompt import EDIT_SYSTEM
from render.newsletter_render import LONDON_TZ

MAX_TOKENS = 6000

_REPAIR_MESSAGE_TEMPLATE = (
    "Your last output was not valid JSON ({error}). Output only the "
    "corrected JSON object."
)


def _candidate_block(c: dict) -> str:
    header = (
        f"[{c['id']}] section={c.get('section', '')} domain={c.get('domain', '')} "
        f"published={c.get('published') or 'unknown'} has_article={str(c.get('has_article') is True).lower()}"
    )
    lines = [header, f"Title: {c.get('title', '')}"]
    if c.get("has_article") and c.get("article_text"):
        lines.append(f"Text: {c['article_text']}")
    elif c.get("snippet"):
        lines.append(f"Snippet: {c['snippet']}")
    return "\n".join(lines)


def build_edit_request(config: dict, history: list[dict], candidates: list[dict],
                        now_london: datetime | None = None, now_utc: datetime | None = None) -> str:
    now_london = now_london or datetime.now(LONDON_TZ)
    now_utc = now_utc or datetime.now(timezone.utc)
    today = now_london.strftime("%A %d %B %Y")

    topics = "\n".join(f"- {t['name']} (focus: {t['focus']})" for t in config["topics"])

    general_news = ""
    if config.get("general_news"):
        general_news = (
            f"\n\nGeneral news (always include): {config['general_focus']}. Use "
            f"topic labels 'World' for major global news and 'Worth knowing' "
            f"for interesting or unexpected stories."
        )

    if history:
        told_lines = "\n".join(
            f"- id {h['id']} | {h['told_on']} | {h['topic']} | {h['headline']} | "
            f"{h['url']} | {h['summary'][:120]}"
            for h in history
        )
    else:
        told_lines = "(none)"

    candidate_blocks = "\n\n".join(_candidate_block(c) for c in candidates) if candidates else "(none)"

    return (
        f"Today is {today} (Europe/London). Current time: "
        f"{now_utc.strftime('%H:%M')} UTC / {now_london.strftime('%H:%M %Z')}. "
        f"Use this to judge whether an event has actually finished - do not assume "
        f"something scheduled for today has already happened.\n\n"
        f"Topics:\n{topics}{general_news}\n\n"
        f"Already told (last {config['history_days']} days):\n{told_lines}\n\n"
        f"Candidates:\n{candidate_blocks}"
    )


def run_edit(config: dict, history: list[dict], candidates: list[dict]) -> tuple[str, dict]:
    """One model call, no tools - research is already done. Returns
    (final_text, usage)."""
    client = anthropic.Anthropic()
    request = build_edit_request(config, history, candidates)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=EDIT_SYSTEM,
        messages=[{"role": "user", "content": request}],
    )
    usage = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
    text = "".join(b.text for b in resp.content if b.type == "text")
    return text, usage


def run_edit_with_repair(config: dict, history: list[dict],
                          candidates: list[dict]) -> tuple[str, dict, dict | None]:
    """run_edit, plus one repair attempt (tools still off) if the reply
    doesn't parse. Returns (final_text, usage, digest) - digest is None
    if even the repair attempt failed."""
    text, usage = run_edit(config, history, candidates)
    digest = parse_edit(text, candidates)
    if digest is not None:
        return text, usage, digest

    print("[warning] edit: final reply did not parse as a valid front page; attempting one repair call")
    client = anthropic.Anthropic()
    request = build_edit_request(config, history, candidates)
    messages = [
        {"role": "user", "content": request},
        {"role": "assistant", "content": text},
        {"role": "user", "content": _REPAIR_MESSAGE_TEMPLATE.format(error=_last_parse_error(text))},
    ]
    resp = client.messages.create(model=MODEL, max_tokens=MAX_TOKENS, system=EDIT_SYSTEM, messages=messages)
    usage["input_tokens"] += resp.usage.input_tokens
    usage["output_tokens"] += resp.usage.output_tokens

    repaired_text = "".join(b.text for b in resp.content if b.type == "text")
    digest = parse_edit(repaired_text, candidates)
    return repaired_text, usage, digest


def _last_parse_error(raw_text: str) -> str:
    """Best-effort human-readable reason parse_edit rejected raw_text, for
    the repair prompt. Not load-bearing - just needs to be informative."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    if "{" not in text:
        return "no JSON object found in the reply"
    try:
        json.JSONDecoder().raw_decode(text, text.index("{"))
    except json.JSONDecodeError as e:
        return str(e)
    return "no candidate object matched the required schema (needs a \"lead\" citing a real candidate id)"


def _candidate_basis(candidate: dict) -> str:
    return "article" if candidate.get("has_article") is True else "snippet"


def _resolve_lead(raw, candidates_by_id: dict) -> tuple[dict, str] | None:
    if not isinstance(raw, dict):
        return None
    candidate = candidates_by_id.get(raw.get("id"))
    if candidate is None:
        print(f"[dropped: lead cites unknown candidate id] {raw.get('id')!r}")
        return None
    merged = {
        **raw,
        "url": candidate.get("url", ""),
        "published": candidate.get("published"),
        "basis": _candidate_basis(candidate),
    }
    cleaned = fps._clean_lead(merged)
    if cleaned is None:
        return None
    return cleaned, candidate["id"]


def _resolve_secondary(raw, candidates_by_id: dict) -> tuple[dict, str] | None:
    if not isinstance(raw, dict):
        return None
    candidate = candidates_by_id.get(raw.get("id"))
    if candidate is None:
        print(f"[dropped: secondary cites unknown candidate id] {raw.get('id')!r}")
        return None
    merged = {
        **raw,
        "url": candidate.get("url", ""),
        "published": candidate.get("published"),
        "basis": _candidate_basis(candidate),
    }
    cleaned = fps._clean_secondary_item(merged)
    if cleaned is None:
        return None
    return cleaned, candidate["id"]


def _resolve_brief(raw, candidates_by_id: dict) -> tuple[dict, str] | None:
    if not isinstance(raw, dict):
        return None
    candidate = candidates_by_id.get(raw.get("id"))
    if candidate is None:
        print(f"[dropped: brief cites unknown candidate id] {raw.get('id')!r}")
        return None
    merged = {**raw, "url": candidate.get("url", ""), "published": candidate.get("published")}
    cleaned = fps._clean_story_item(merged, fps.SUMMARY_CEILING_BRIEF)
    if cleaned is None:
        return None
    return cleaned, candidate["id"]


def _resolve_section(raw, candidates_by_id: dict) -> tuple[dict, list[str]] | None:
    if not isinstance(raw, dict):
        return None
    name = fps._clean_str(raw.get("name"))
    if name is None:
        return None
    briefs, used = [], []
    if isinstance(raw.get("briefs"), list):
        for b in raw["briefs"][:fps._MAX_BRIEFS_PER_SECTION]:
            result = _resolve_brief(b, candidates_by_id)
            if result is not None:
                cleaned, source_id = result
                briefs.append(cleaned)
                used.append(source_id)
    return {"name": name, "briefs": briefs}, used


_NUMERIC_RE = re.compile(r"\d[\d,]*\.?\d*")


def _numbers_in(text: str) -> set[str]:
    return {m.replace(",", "") for m in _NUMERIC_RE.findall(text or "")}


def _numeric_guard_ok(fields: list[str], source_text: str) -> bool:
    """True if every number mentioned in `fields` (comma-insensitive)
    appears somewhere in source_text. A field with no numbers at all
    (e.g. a bare podium order) trivially passes - there's nothing to
    fabricate there."""
    source_numbers = _numbers_in(source_text)
    return all(num in source_numbers for field in fields for num in _numbers_in(field))


def _resolve_ticker_item(raw, candidates_by_id: dict) -> tuple[dict, str] | None:
    if not isinstance(raw, dict):
        return None
    candidate = candidates_by_id.get(raw.get("source"))
    if candidate is None:
        print(f"[dropped: ticker cites unknown candidate id] {raw.get('source')!r}")
        return None
    if not candidate.get("has_article") or not candidate.get("article_text"):
        print(f"[dropped: ticker source {raw.get('source')!r} has no fetched article text] {raw.get('label', '')!r}")
        return None
    if not _numeric_guard_ok([str(raw.get("value", "")), str(raw.get("change", ""))], candidate["article_text"]):
        print(
            f"[dropped: ticker numeric guard failed] {raw.get('label', '')!r} "
            f"value={raw.get('value')!r} change={raw.get('change')!r} (not found in source text)"
        )
        return None
    cleaned = fps._clean_ticker_item(raw)
    if cleaned is None:
        return None
    return cleaned, candidate["id"]


def _resolve_scoreboard_item(raw, candidates_by_id: dict) -> tuple[dict, str] | None:
    if not isinstance(raw, dict):
        return None
    candidate = candidates_by_id.get(raw.get("source"))
    if candidate is None:
        print(f"[dropped: scoreboard cites unknown candidate id] {raw.get('source')!r}")
        return None
    if not candidate.get("has_article") or not candidate.get("article_text"):
        print(f"[dropped: scoreboard source {raw.get('source')!r} has no fetched article text] {raw.get('line', '')!r}")
        return None
    if not _numeric_guard_ok([str(raw.get("line", ""))], candidate["article_text"]):
        print(f"[dropped: scoreboard numeric guard failed] {raw.get('line', '')!r} (not found in source text)")
        return None
    cleaned = fps._clean_scoreboard_item(raw)
    if cleaned is None:
        return None
    return cleaned, candidate["id"]


def _display_name(domain: str) -> str:
    """Best-effort outlet display name from a bare domain - strips the
    TLD and title-cases (or upper-cases a short acronym-like label) the
    main label. Not perfect for multi-part domains (e.g.
    "edition.cnn.com"), but good enough for the common single-label
    domains gather.py's search results normally give."""
    label = domain.split(".")[0] if domain else ""
    if not label:
        return domain
    return label.upper() if len(label) <= 3 else label.title()


def _derive_sources(used_ids: set, candidates_by_id: dict) -> list[dict]:
    """Code-derived outlet credits (the digest-wide "Sources" list) from
    the candidates actually cited - the model never writes this list."""
    seen_domains = set()
    sources = []
    for cid in used_ids:
        candidate = candidates_by_id.get(cid)
        domain = candidate.get("domain", "") if candidate else ""
        if not domain or domain in seen_domains:
            continue
        seen_domains.add(domain)
        sources.append({"name": _display_name(domain), "url": f"https://{domain}"})
    sources.sort(key=lambda s: s["name"])
    return sources[:fps._MAX_SOURCES]


def _validate_edit(raw, candidates_by_id: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None

    lead_result = _resolve_lead(raw.get("lead"), candidates_by_id)
    if lead_result is None:
        return None
    lead, lead_id = lead_result
    used_ids = {lead_id}

    secondary = []
    if isinstance(raw.get("secondary"), list):
        for item in raw["secondary"][:fps._MAX_SECONDARY]:
            result = _resolve_secondary(item, candidates_by_id)
            if result is not None:
                cleaned, source_id = result
                secondary.append(cleaned)
                used_ids.add(source_id)

    sections = []
    if isinstance(raw.get("sections"), list):
        for item in raw["sections"][:fps._MAX_SECTIONS]:
            result = _resolve_section(item, candidates_by_id)
            if result is not None:
                section_dict, section_used_ids = result
                sections.append(section_dict)
                used_ids.update(section_used_ids)

    ticker = []
    if isinstance(raw.get("ticker"), list):
        for item in raw["ticker"][:fps._MAX_TICKER]:
            result = _resolve_ticker_item(item, candidates_by_id)
            if result is not None:
                cleaned, source_id = result
                ticker.append(cleaned)
                used_ids.add(source_id)

    scoreboard = []
    if isinstance(raw.get("scoreboard"), list):
        for item in raw["scoreboard"][:fps._MAX_SCOREBOARD]:
            result = _resolve_scoreboard_item(item, candidates_by_id)
            if result is not None:
                cleaned, source_id = result
                scoreboard.append(cleaned)
                used_ids.add(source_id)

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
        "sources": _derive_sources(used_ids, candidates_by_id),
        "disclosure": disclosure,
        "notes": notes,
    }


def parse_edit(raw_text: str, candidates: list[dict]) -> dict | None:
    """Find every JSON object in the model's reply and keep the LAST one
    that validates - same multi-candidate extraction approach as
    front_page_schema.parse_digest, adapted to resolve candidate ids
    (and run the numeric guard on ticker/scoreboard) instead of trusting
    model-written url/published/basis fields."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()

    candidates_by_id = {c["id"]: c for c in candidates}

    decoder = json.JSONDecoder()
    best = None
    pos = 0
    while True:
        brace = text.find("{", pos)
        if brace == -1:
            break
        try:
            raw, end = decoder.raw_decode(text, brace)
        except json.JSONDecodeError:
            pos = brace + 1
            continue
        validated = _validate_edit(raw, candidates_by_id)
        if validated is not None:
            best = validated
        pos = end

    return best

"""digest.py - CLI entry point and orchestration for the news digest.

Parses CLI flags, wires together the agent loop (agent_loop.py), fixtures
(fixtures.py), the database and delivery, then renders and ships the digest.
"""
import json
import os
import sys
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

from dotenv import load_dotenv

import tools  # noqa: F401  -- importing this file runs the @tool decorators that fill REGISTRY
from agent_loop import MODEL, MAX_TURNS, MAX_TOKENS, SYSTEM, build_request, run_agent_with_repair
from fixtures import fixture_stories
from config import load_config
from db import init_db, recent_stories, save_story, seen_url
from delivery import deliver
from newsletter_render import SUMMARY_CEILING_BRIEF, SUMMARY_CEILING_HERO, SUMMARY_CEILING_MAJOR, clean_summary
from storage import sync_down, sync_up, upload_run_archive

load_dotenv()

DRY_RUN = "--dry-run" in sys.argv[1:]
SEND = "--send" in sys.argv[1:]
FIXTURE = "--fixture" in sys.argv[1:]  # skip the model/tools; use a canned front page
CHECK = "--check" in sys.argv[1:]  # validate config/env only; no model, tool, or email calls

if FIXTURE:
    DRY_RUN = True  # fixture stories must never be able to reach the DB

if SEND:
    os.environ["DIGEST_DELIVERY"] = "email"  # overrides DIGEST_DELIVERY=local

# For the end-of-run cost estimate. Update if pricing changes.
PRICE_IN_PER_M = 3.0
PRICE_OUT_PER_M = 15.0
# claude-sonnet-4-6 uses the standard prompt-caching multipliers (no
# per-model exception - confirmed against the current docs, not assumed):
# https://platform.claude.com/docs/en/docs/build-with-claude/prompt-caching
_CACHE_WRITE_MULTIPLIER = 1.25  # 5-minute TTL, the only TTL this codebase uses
_CACHE_READ_MULTIPLIER = 0.1


def _print_usage_line(usage: dict) -> None:
    cost = (
        usage["input_tokens"] / 1_000_000 * PRICE_IN_PER_M
        + usage["output_tokens"] / 1_000_000 * PRICE_OUT_PER_M
        + usage.get("cache_creation_input_tokens", 0) / 1_000_000 * PRICE_IN_PER_M * _CACHE_WRITE_MULTIPLIER
        + usage.get("cache_read_input_tokens", 0) / 1_000_000 * PRICE_IN_PER_M * _CACHE_READ_MULTIPLIER
    )
    print(
        f"\n[usage] input_tokens={usage['input_tokens']} output_tokens={usage['output_tokens']} "
        f"cache_creation_input_tokens={usage.get('cache_creation_input_tokens', 0)} "
        f"cache_read_input_tokens={usage.get('cache_read_input_tokens', 0)} "
        f"estimated_cost=${cost:.4f} (estimate)"
    )


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


def prepare_front_page(digest: dict, cutoff: str) -> tuple[dict | None, list[dict], list[dict]]:
    """Apply the lookback-days cutoff, the already-seen-url check, the
    low-trust-domain denylist, the article-basis requirement (lead and
    secondary only), and the summary floor/ceiling to every item BEFORE
    it can appear in the digest. The lead must survive all of these; if
    it doesn't, the first surviving secondary item - or, failing that,
    the first surviving brief - is promoted to lead instead. The lead is
    never allowed to be a stale, already-told, low-trust, snippet-basis,
    or under-floor-summary story."""
    lead = digest.get("lead")
    secondary = [s for s in digest.get("secondary", []) if _is_fresh_and_new(s, cutoff)]
    secondary = [s for s in secondary if _passes_domain_check(s)]
    secondary = [s for s in secondary if _passes_basis_check(s)]
    secondary = [s for s in secondary if _passes_summary_floor(s, "summary", SUMMARY_CEILING_MAJOR)]

    sections = []
    for section in digest.get("sections", []):
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
    """Flatten the front-page shape into the flat list the existing HTML/
    text renderer expects: lead -> HERO (hero selection keys off
    "lead": True, not weight), secondary -> MAJOR (weight 3), section
    briefs -> BRIEF (weight 1)."""
    stories = []
    if lead is not None:
        stories.append({
            "topic": lead.get("topic", ""),
            "headline": lead["headline"],
            "summary": _lead_summary(lead),
            "url": lead["url"],
            "published": lead.get("published"),
            "update_of": lead.get("update_of"),
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
                "lead": False,
                "weight": 1,
            })
    return stories


def render_digest(lead: dict | None, secondary: list[dict], sections: list[dict],
                   ticker: list[dict], scoreboard: list[dict], sources: list[dict],
                   disclosure: str | None, history: list[dict]) -> str:
    """Build the front page as markdown: lead, then secondary stories,
    then each section's briefs, then markets/scoreboard/sources/disclosure
    if present."""
    history_by_id = {h["id"]: h for h in history}

    def _update_line(item: dict) -> str | None:
        update_of = item.get("update_of")
        if update_of is None:
            return None
        prior = history_by_id.get(update_of)
        return f"(follows: {prior['headline']})" if prior else None

    lines = []

    if lead is not None:
        lines.append(f"# {lead['headline']}")
        if lead.get("dek"):
            lines.append(f"*{lead['dek']}*")
        update_line = _update_line(lead)
        if update_line:
            lines.append(update_line)
        if lead.get("body"):
            lines.append(lead["body"])
        if lead.get("sources"):
            lines.append(f"Sources: {', '.join(lead['sources'])}")
        lines.append(lead["url"])
        lines.append("")

    if secondary:
        lines.append("## Also today\n")
        for item in secondary:
            lines.append(f"**{item['headline']}**")
            update_line = _update_line(item)
            if update_line:
                lines.append(update_line)
            if item.get("summary"):
                lines.append(item["summary"])
            lines.append(item["url"])
            lines.append("")

    for section in sections:
        if not section["briefs"]:
            continue
        lines.append(f"## {section['name']}\n")
        for brief in section["briefs"]:
            lines.append(f"**{brief['headline']}**")
            update_line = _update_line(brief)
            if update_line:
                lines.append(update_line)
            if brief.get("summary"):
                lines.append(brief["summary"])
            lines.append(brief["url"])
            lines.append("")

    if ticker:
        lines.append("## Markets\n")
        arrows = {"up": "^", "down": "v", "flat": "-"}
        for row in ticker:
            change = f" {row['change']}" if row.get("change") else ""
            arrow = arrows.get(row.get("direction"), "")
            lines.append(f"- {row['label']}: {row['value']}{change} {arrow}".rstrip())
        lines.append("")

    if scoreboard:
        lines.append("## Scoreboard\n")
        for row in scoreboard:
            lines.append(f"- {row['label']}: {row['line']}")
        lines.append("")

    if sources:
        lines.append("## Sources\n")
        for src in sources:
            lines.append(f"- {src['name']}" + (f" ({src['url']})" if src.get("url") else ""))
        lines.append("")

    if disclosure:
        lines.append(f"*{disclosure}*")

    return "\n".join(lines)


def run_check() -> int:
    """--check: validate config and environment only - no model, tool, or
    email calls, and no writes to the local DB. Returns a process exit
    code (0 ok, 1 if anything's wrong)."""
    ok = True

    print("[check] config:")
    config = None
    try:
        config = load_config()
        print(f"  OK - {len(config['topics'])} topic(s), lookback_days={config['lookback_days']}")
    except ValueError as e:
        print(f"  FAIL - {e}")
        ok = False

    print("[check] environment variables (presence only - values are never printed):")
    required = ["ANTHROPIC_API_KEY", "TAVILY_API_KEY"]

    delivery_backend = os.environ.get("DIGEST_DELIVERY", "local")
    if delivery_backend == "email":
        required += ["GMAIL_USER", "GMAIL_APP_PASSWORD"]
        has_recipient = bool(os.environ.get("DIGEST_TO")) or bool(config and config.get("recipient"))
        print(f"  {'set    ' if has_recipient else 'MISSING'} - DIGEST_TO (or config 'recipient')")
        if not has_recipient:
            ok = False

    storage_backend = os.environ.get("DIGEST_STORAGE", "local")
    if storage_backend == "gcs":
        required.append("DIGEST_GCS_BUCKET")

    for name in required:
        present = bool(os.environ.get(name))
        print(f"  {'set    ' if present else 'MISSING'} - {name}")
        if not present:
            ok = False

    if storage_backend == "gcs" and os.environ.get("DIGEST_GCS_BUCKET"):
        print("[check] GCS bucket:")
        try:
            from google.cloud import storage as gcs_storage

            bucket_name = os.environ["DIGEST_GCS_BUCKET"]
            object_name = os.environ.get("DIGEST_DB_OBJECT", "digest.db")
            # Object-level only (blob.exists(), never bucket.exists()) -
            # the runtime service account only has roles/storage.objectAdmin,
            # which doesn't cover storage.buckets.get. A missing object is
            # fine (first run); exists() itself raises on a real access
            # problem (403, network error), caught below.
            blob = gcs_storage.Client().bucket(bucket_name).blob(object_name)
            if blob.exists():
                print(f"  OK - DB object '{object_name}' exists in gs://{bucket_name}")
            else:
                print(f"  OK - DB object '{object_name}' does not exist yet in gs://{bucket_name} (first run will start fresh)")
        except Exception as e:
            print(f"  FAIL - could not verify GCS access: {type(e).__name__}: {e}")
            ok = False

    print(f"\n[check] {'all checks passed' if ok else 'one or more checks failed'}")
    return 0 if ok else 1


if __name__ == "__main__":
    if CHECK:
        sys.exit(run_check())

    config = load_config()

    for topic in config["topics"]:
        if topic["commentary"] != "none":
            print(
                f"[warning] commentary '{topic['commentary']}' for topic "
                f"'{topic['name']}' isn't implemented yet; treating it as 'none'."
            )
            topic["commentary"] = "none"

    sync_down()
    init_db()
    history = recent_stories(config["history_days"])

    usage = {
        "input_tokens": 0, "output_tokens": 0,
        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
    }
    try:
        if FIXTURE:
            print("[fixture] skipping the model and all tools; using a canned front-page digest.")
            digest = fixture_stories(config)
        else:
            raw_text, usage, tool_log, digest = run_agent_with_repair(config, history)

            # Archived regardless of outcome, so a run that fails to parse
            # (even after the repair attempt) is still captured for
            # debugging why. No-op unless gcs + DIGEST_ARCHIVE=true.
            run_timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            upload_run_archive(run_timestamp, {
                "timestamp": run_timestamp,
                "tool_results": [
                    {"tool": t["tool"], "args": t["args"], "result": str(t["result"])[:2000]}
                    for t in tool_log
                ],
                "final_json": _try_parse_json_reply(raw_text),
            })

            if digest is None:
                print(
                    "[error] agent_loop.run_agent_with_repair: the model's final reply "
                    "did not validate as a front page (needs at least a usable \"lead\"), "
                    "and the one repair retry (asking it to correct the JSON with tools "
                    "off) also failed. Raw reply follows:"
                )
                print(raw_text)
                sys.exit(1)

        cutoff = (date.today() - timedelta(days=config["lookback_days"])).isoformat()
        lead, secondary, sections = prepare_front_page(digest, cutoff)
        stories = build_render_stories(lead, secondary, sections)

        # Deliver BEFORE persisting. If delivery fails (send() exits non-zero
        # internally on a failed email), nothing below runs, so no story gets
        # marked "told" without actually reaching the reader - a retry will
        # just pick the same stories up again. The failure mode this avoids is
        # saving first: a crash or failed send between save and delivery would
        # silently lose a story forever. Worst case now is the opposite and far
        # safer - a crash between send and save can at most repeat a story in
        # tomorrow's digest, never lose one.
        rendered = render_digest(
            lead, secondary, sections,
            digest.get("ticker", []), digest.get("scoreboard", []), digest.get("sources", []),
            digest.get("disclosure"), history,
        )
        front_page = {
            "lead": lead, "secondary": secondary, "sections": sections,
            "ticker": digest.get("ticker", []), "scoreboard": digest.get("scoreboard", []),
            "sources": digest.get("sources", []), "disclosure": digest.get("disclosure"),
        }
        deliver(rendered, stories, title=config["title"], tagline=config["tagline"],
                recipient=config["recipient"], front_page=front_page)

        if not DRY_RUN:
            if lead is not None:
                save_story(
                    topic=lead.get("topic", ""), headline=lead["headline"],
                    summary=_lead_summary(lead), url=lead["url"], update_of=lead.get("update_of"),
                )
            for item in secondary:
                save_story(
                    topic=item.get("topic", ""), headline=item["headline"],
                    summary=item.get("summary", ""), url=item["url"], update_of=item.get("update_of"),
                )
            for section in sections:
                for brief in section["briefs"]:
                    save_story(
                        topic=section["name"], headline=brief["headline"],
                        summary=brief.get("summary", ""), url=brief["url"], update_of=brief.get("update_of"),
                    )
            sync_up()

        notes = digest.get("notes", "").strip()
        if notes:
            print(notes)
    finally:
        # try/finally so the usage line always prints, including when the
        # run above exits non-zero (e.g. the undeliverable-digest path).
        _print_usage_line(usage)

"""digest.py - CLI entry point and orchestration for the news digest.

Parses CLI flags, wires together the agent loop (agent_loop.py), fixtures
(fixtures.py), the database and delivery, then renders and ships the digest.
"""
import os
import sys
from datetime import date, timedelta

from dotenv import load_dotenv

import tools  # noqa: F401  -- importing this file runs the @tool decorators that fill REGISTRY
from agent_loop import MODEL, MAX_TURNS, MAX_TOKENS, SYSTEM, build_request, run_agent, parse_digest
from fixtures import fixture_stories
from config import load_config
from db import init_db, recent_stories, save_story, seen_url
from delivery import deliver
from storage import sync_down, sync_up

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


def _lead_summary(lead: dict) -> str:
    """The lead's dek + body joined into one block - used both as the
    HTML/text renderer's "summary" for the hero card and as what gets
    stored for future "Already told" context."""
    return " ".join(part for part in (lead.get("dek", ""), lead.get("body", "")) if part).strip()


def _is_fresh_and_new(item: dict, cutoff: str) -> bool:
    """A story is usable only if it isn't older than the lookback window
    (or carries no date at all) and its url hasn't already been told."""
    published = item.get("published")
    if published and published < cutoff:
        return False
    return bool(item.get("url")) and not seen_url(item["url"])


def prepare_front_page(digest: dict, cutoff: str) -> tuple[dict | None, list[dict], list[dict]]:
    """Apply the lookback-days cutoff and the already-seen-url check to
    every item BEFORE it can appear in the digest. The lead must survive
    both checks; if it doesn't, the first surviving secondary item - or,
    failing that, the first surviving brief - is promoted to lead instead.
    The lead is never allowed to be a stale or already-told story."""
    lead = digest.get("lead")
    secondary = [s for s in digest.get("secondary", []) if _is_fresh_and_new(s, cutoff)]
    sections = []
    for section in digest.get("sections", []):
        briefs = [b for b in section.get("briefs", []) if _is_fresh_and_new(b, cutoff)]
        sections.append({"name": section["name"], "briefs": briefs})

    if lead is not None and not _is_fresh_and_new(lead, cutoff):
        lead = None
        if secondary:
            lead, secondary = secondary[0], secondary[1:]
        else:
            for section in sections:
                if section["briefs"]:
                    lead, section["briefs"] = section["briefs"][0], section["briefs"][1:]
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
            from google.api_core.exceptions import NotFound
            from google.cloud import storage as gcs_storage

            bucket_name = os.environ["DIGEST_GCS_BUCKET"]
            object_name = os.environ.get("DIGEST_DB_OBJECT", "digest.db")
            bucket = gcs_storage.Client().bucket(bucket_name)
            if not bucket.exists():
                print(f"  FAIL - bucket gs://{bucket_name} is not reachable or does not exist")
                ok = False
            else:
                print(f"  OK - bucket gs://{bucket_name} is reachable")
                blob = bucket.blob(object_name)
                try:
                    blob.reload()
                    print(f"  OK - DB object '{object_name}' exists, {blob.size} bytes")
                except NotFound:
                    print(f"  OK - DB object '{object_name}' does not exist yet (first run will start fresh)")
        except Exception as e:
            print(f"  FAIL - could not verify GCS bucket: {type(e).__name__}: {e}")
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

    if FIXTURE:
        print("[fixture] skipping the model and all tools; using a canned front-page digest.")
        digest = fixture_stories(config)
        usage = {"input_tokens": 0, "output_tokens": 0}
    else:
        raw_text, hit_max_turns, usage = run_agent(config, history)
        if hit_max_turns:
            print(raw_text)
            sys.exit(1)

        digest = parse_digest(raw_text)
        if digest is None:
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

    cost = (usage["input_tokens"] / 1_000_000 * PRICE_IN_PER_M
            + usage["output_tokens"] / 1_000_000 * PRICE_OUT_PER_M)
    print(
        f"\n[usage] input_tokens={usage['input_tokens']} output_tokens={usage['output_tokens']} "
        f"estimated_cost=${cost:.4f} (estimate)"
    )

"""digest.py - CLI entry point and orchestration for the news digest.

Parses CLI flags, wires together the agent loop (agent_loop.py), fixtures
(fixtures.py), the database, image enrichment and delivery, then renders
and ships the digest.
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
from images import enrich_images
from storage import sync_down, sync_up

load_dotenv()

def _arg_value(flag: str, default: str | None = None) -> str | None:
    """Value following `flag` in argv, e.g. --fixture-count 5 -> '5'."""
    argv = sys.argv[1:]
    if flag not in argv:
        return default
    idx = argv.index(flag)
    return argv[idx + 1] if idx + 1 < len(argv) else default


DRY_RUN = "--dry-run" in sys.argv[1:]
SEND = "--send" in sys.argv[1:]
FIXTURE = "--fixture" in sys.argv[1:]  # skip the model/tools; use canned stories
NO_IMAGES = "--no-images" in sys.argv[1:]  # skip enrich_images for this run
CHECK = "--check" in sys.argv[1:]  # validate config/env only; no model, tool, or email calls

if FIXTURE:
    DRY_RUN = True  # fixture stories must never be able to reach the DB

try:
    FIXTURE_COUNT = max(1, min(15, int(_arg_value("--fixture-count", "15"))))
except ValueError:
    FIXTURE_COUNT = 15

if SEND:
    os.environ["DIGEST_DELIVERY"] = "email"  # overrides DIGEST_DELIVERY=local

# For the end-of-run cost estimate. Update if pricing changes.
PRICE_IN_PER_M = 3.0
PRICE_OUT_PER_M = 15.0


def normalise_weight(story: dict) -> int:
    """Coerce a story's "weight" to 1, 2, or 3. Anything else - missing,
    wrong type, out of range - becomes 2 (STANDARD)."""
    weight = story.get("weight")
    if isinstance(weight, bool) or not isinstance(weight, int) or weight not in (1, 2, 3):
        return 2
    return weight


def render_digest(config: dict, stories: list[dict], history: list[dict]) -> str:
    """Build the digest as markdown, grouped by topic."""
    history_by_id = {h["id"]: h for h in history}
    topic_names = [t["name"] for t in config["topics"]]
    if config.get("general_news"):
        topic_names += ["World", "Worth knowing"]

    by_topic: dict[str, list[dict]] = {}
    for story in stories:
        by_topic.setdefault(story.get("topic"), []).append(story)

    lines = []
    for topic in topic_names:
        topic_stories = by_topic.get(topic)
        if not topic_stories:
            continue
        lines.append(f"## {topic}\n")
        for story in topic_stories:
            headline = story["headline"]
            update_of = story.get("update_of")
            if update_of is not None:
                headline = f"Update: {headline}"
            lines.append(f"**{headline}**")
            if update_of is not None:
                prior = history_by_id.get(update_of)
                if prior:
                    lines.append(f"(follows: {prior['headline']})")
            summary = story["summary"]
            if story.get("basis") == "snippet":
                summary = f"{summary} (based on a search snippet only)"
            lines.append(summary)
            published = story.get("published")
            lines.append(f"Published: {published if published else '(date unverified)'}")
            lines.append(story["url"])
            lines.append("")

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
        print(f"[fixture] skipping the model and all tools; using {FIXTURE_COUNT} canned test stories.")
        digest = {
            "stories": fixture_stories(config, count=FIXTURE_COUNT),
            "notes": "Fixture test run - no real sources were read.",
        }
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
    stories = []
    for story in digest.get("stories", []):
        published = story.get("published")
        if published and published < cutoff:
            print(f"[dropped: too old] {story.get('headline', '?')} ({published})")
            continue
        stories.append(story)

    stories = [s for s in stories if not seen_url(s["url"])]

    if not FIXTURE and not NO_IMAGES and config["images"]:
        enrich_images(stories)

    for story in stories:
        story["weight"] = normalise_weight(story)  # rendering only; never stored

    # Deliver BEFORE persisting. If delivery fails (send() exits non-zero
    # internally on a failed email), nothing below runs, so no story gets
    # marked "told" without actually reaching the reader - a retry will
    # just pick the same stories up again. The failure mode this avoids is
    # saving first: a crash or failed send between save and delivery would
    # silently lose a story forever. Worst case now is the opposite and far
    # safer - a crash between send and save can at most repeat a story in
    # tomorrow's digest, never lose one.
    rendered = render_digest(config, stories, history)
    deliver(rendered, stories, title=config["title"], tagline=config["tagline"], recipient=config["recipient"])

    if not DRY_RUN:
        for story in stories:
            save_story(
                topic=story["topic"],
                headline=story["headline"],
                summary=story["summary"],
                url=story["url"],
                update_of=story.get("update_of"),
                image_url=story.get("image_url"),
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

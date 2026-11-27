"""digest.py - CLI entry point and orchestration for the news digest.

Parses CLI flags, wires together the agent loop (agent_loop.py), fixtures
(fixtures.py), the database and delivery, then renders and ships the digest.
The front-page assembly logic lives in front_page.py and the markdown
renderer in markdown_render.py; this file just wires them together.
"""
import os
import sys
from datetime import date, datetime, timedelta

from dotenv import load_dotenv

import sources.tools  # noqa: F401  -- importing this file runs the @tool decorators that fill REGISTRY
from pipeline.agent_loop import MODEL, MAX_TURNS, MAX_TOKENS, SYSTEM, build_request, run_agent, parse_digest
from fixtures import fixture_stories
from config import load_config
from db import init_db, recent_stories, save_story
from delivery import deliver
from pipeline.front_page import (
    _code_ticker_and_scoreboard, _lead_summary, _resolve_follows,
    _try_parse_json_reply, build_render_stories, prepare_front_page,
)
from pipeline.markdown_render import render_digest
from storage import sync_down, sync_up, upload_run_archive

load_dotenv()

def _flag_value(name: str) -> str | None:
    """The value after a space-separated CLI flag, e.g. "--engine pipeline"
    -> "pipeline" - or None if the flag wasn't given."""
    args = sys.argv[1:]
    if name in args:
        idx = args.index(name)
        if idx + 1 < len(args):
            return args[idx + 1]
    return None


DRY_RUN = "--dry-run" in sys.argv[1:]
SEND = "--send" in sys.argv[1:]
FIXTURE = "--fixture" in sys.argv[1:]  # skip the model/tools; use a canned front page
CHECK = "--check" in sys.argv[1:]  # validate config/env only; no model, tool, or email calls
GATHER_ONLY = "--gather-only" in sys.argv[1:]  # run gather+filter only; no model, DB write, or email
ENGINE_OVERRIDE = _flag_value("--engine")  # "pipeline" | "agent" - overrides config's "engine" key

if FIXTURE:
    DRY_RUN = True  # fixture stories must never be able to reach the DB

if SEND:
    os.environ["DIGEST_DELIVERY"] = "email"  # overrides DIGEST_DELIVERY=local

# For the end-of-run cost estimate. Update if pricing changes.
PRICE_IN_PER_M = 3.0
PRICE_OUT_PER_M = 15.0


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

    # Optional env vars: informational only, never fail the check -
    # each gates a best-effort feature that degrades gracefully if unset
    # (football scores are simply skipped; the web edition just doesn't
    # get published/linked).
    for name in ("FOOTBALL_DATA_API_KEY", "DIGEST_WEB_BUCKET"):
        present = bool(os.environ.get(name))
        print(f"  {'set    ' if present else 'unset  '} - {name} (optional)")

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


def _print_candidate_table(items: list[dict]) -> None:
    headers = ["id", "section", "domain", "published", "cluster_size", "has_article", "title"]
    rows = []
    for item in items:
        title = str(item.get("title", ""))
        if len(title) > 70:
            title = title[:69] + "…"
        rows.append([str(item.get(h, "")) for h in headers[:-1]] + [title])

    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]

    def _row(cells):
        return " | ".join(cell.ljust(w) for cell, w in zip(cells, widths))

    print(_row(headers))
    print("-+-".join("-" * w for w in widths))
    for r in rows:
        print(_row(r))


def _run_gather_and_filter(config: dict) -> tuple[list[dict], int]:
    """The gather+filter funnel shared by --gather-only and the real
    pipeline engine: build queries, search Tavily, read feeds, then
    denylist/stale/seen/dedupe/cluster/shortlist/fetch, printing a count
    at each stage. Returns (final candidates, number of Tavily searches
    run - one per query)."""
    from pipeline.gather import build_queries, search_all, gather_feeds, assign_ids
    from pipeline.filter import (
        drop_denylisted, drop_stale, drop_seen, dedupe_by_url, cluster, shortlist, fetch_top,
        require_articles_for_data,
    )

    queries = build_queries(config, datetime.now())
    data_query_count = sum(1 for q in queries if q["section"] == "data")
    print(f"[gather] {len(queries)} queries ({data_query_count} data)")

    search_results = search_all(queries, config["lookback_days"])
    feed_results = gather_feeds(config["sites"], config["lookback_days"])
    candidates = assign_ids(search_results + feed_results)
    print(f"[gather] {len(candidates)} raw results ({len(search_results)} search, {len(feed_results)} feed)")

    after_denylist = drop_denylisted(candidates)
    print(f"[filter] {len(after_denylist)} after denylist (dropped {len(candidates) - len(after_denylist)})")

    after_stale = drop_stale(after_denylist, config["lookback_days"])
    print(f"[filter] {len(after_stale)} after stale filter (dropped {len(after_denylist) - len(after_stale)})")

    after_seen = drop_seen(after_stale)
    print(f"[filter] {len(after_seen)} after seen filter (dropped {len(after_stale) - len(after_seen)})")

    after_dedupe = dedupe_by_url(after_seen)
    print(f"[filter] {len(after_dedupe)} after url dedupe (dropped {len(after_seen) - len(after_dedupe)})")

    clustered = cluster(after_dedupe)
    print(f"[filter] {len(clustered)} after clustering ({len(after_dedupe)} candidates)")

    shortlisted = shortlist(clustered)
    print(f"[filter] {len(shortlisted)} shortlisted")

    fetched = fetch_top(shortlisted)
    attempted = [f for f in fetched if f["has_article"] is not None]
    ok_count = sum(1 for f in attempted if f["has_article"])
    print(f"[filter] fetched {ok_count} OK / {len(attempted) - ok_count} failed ({len(attempted)} attempted)")

    complete = require_articles_for_data(fetched)
    print(f"[filter] {len(complete)} after requiring articles for data items (dropped {len(fetched) - len(complete)})")

    return complete, len(queries)


def run_gather_only(config: dict) -> list[dict]:
    """--gather-only: run the fixed (non-agentic) gather + filter pipeline
    and print counts at each stage plus the final shortlist as a table.
    Never calls the model, never sends email, never writes the DB (only
    drop_seen *reads* it)."""
    complete, _ = _run_gather_and_filter(config)
    print()
    _print_candidate_table(complete)

    if os.environ.get("DIGEST_ARCHIVE", "").lower() == "true":
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        upload_run_archive(f"{timestamp}-gather", {"timestamp": timestamp, "candidates": complete})

    return complete


if __name__ == "__main__":
    if CHECK:
        sys.exit(run_check())

    config = load_config()
    if ENGINE_OVERRIDE is not None:
        if ENGINE_OVERRIDE not in ("pipeline", "agent"):
            print(f"[error] --engine must be 'pipeline' or 'agent', got {ENGINE_OVERRIDE!r}")
            sys.exit(1)
        config["engine"] = ENGINE_OVERRIDE

    if GATHER_ONLY:
        init_db()  # drop_seen reads the DB; never written here
        run_gather_only(config)
        sys.exit(0)

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

    tavily_searches = 0

    if FIXTURE:
        print("[fixture] skipping the model and all tools; using a canned front-page digest.")
        digest = fixture_stories(config)
        usage = {"input_tokens": 0, "output_tokens": 0}

    elif config["engine"] == "agent":
        raw_text, hit_max_turns, usage, tool_log = run_agent(config, history)
        if hit_max_turns:
            print(raw_text)
            sys.exit(1)
        tavily_searches = sum(1 for t in tool_log if t["tool"] == "search_web")

        # Archived before parsing, so a run that fails to parse is still
        # captured for debugging why. No-op unless gcs + DIGEST_ARCHIVE=true.
        run_timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        upload_run_archive(run_timestamp, {
            "timestamp": run_timestamp,
            "tool_results": [
                {"tool": t["tool"], "args": t["args"], "result": str(t["result"])[:2000]}
                for t in tool_log
            ],
            "final_json": _try_parse_json_reply(raw_text),
        })

        digest = parse_digest(raw_text)
        if digest is None:
            print(raw_text)
            sys.exit(1)

        code_ticker, code_scoreboard = _code_ticker_and_scoreboard(config)
        if code_ticker:
            digest["ticker"] = code_ticker
        if code_scoreboard:
            digest["scoreboard"] = code_scoreboard

    else:  # engine == "pipeline"
        from pipeline.edit import run_edit_with_repair

        candidates, tavily_searches = _run_gather_and_filter(config)

        raw_text, usage, digest = run_edit_with_repair(config, history, candidates)

        # Archived before the None check, same reasoning as the agent engine:
        # a reply that fails to parse (even after repair) is still captured
        # for debugging why. No-op unless gcs + DIGEST_ARCHIVE=true.
        run_timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        upload_run_archive(run_timestamp, {
            "timestamp": run_timestamp,
            "candidates": candidates,
            "final_json": _try_parse_json_reply(raw_text),
        })

        if digest is None:
            print(
                "[error] edit: the model's final reply did not validate as a front page "
                "(needs at least a usable \"lead\" citing a real candidate id), and the "
                "one repair retry also failed. Raw reply follows:"
            )
            print(raw_text)
            sys.exit(1)

    cutoff = (date.today() - timedelta(days=config["lookback_days"])).isoformat()
    lead, secondary, sections = prepare_front_page(digest, cutoff, config)

    history_by_id = {h["id"]: h for h in history}
    if lead is not None:
        _resolve_follows([lead], history_by_id)
    _resolve_follows(secondary, history_by_id)
    for section in sections:
        _resolve_follows(section["briefs"], history_by_id)

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
        f"\n[usage] engine={config['engine']} input_tokens={usage['input_tokens']} "
        f"output_tokens={usage['output_tokens']} tavily_searches={tavily_searches} "
        f"estimated_cost=${cost:.4f} (estimate)"
    )

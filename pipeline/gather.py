"""gather.py - the gather stage of the fixed (non-agentic) news pipeline.

Builds a deterministic list of search queries from the config (no model
involved), runs them against Tavily in parallel, reads the configured RSS
feeds, and returns one flat list of candidate dicts - the raw material for
filter.py's dedupe/cluster/shortlist/fetch stages.

Each candidate dict has: id, section, title, url, domain, snippet,
published (YYYY-MM-DD or None), source_query.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
import json

from sources.tools import _tavily_client, _to_date, find_feed, read_feed

MAX_QUERIES = 14           # total query budget across topics + general news
MAX_SEARCH_WORKERS = 5
SEARCH_MAX_RESULTS = 8


def _domain_of(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _topic_queries(topic: dict) -> list[str]:
    """One or two deterministic queries for a topic, built from its name
    and focus only - no model call. The first is the broad topic name;
    the second (only added if it differs) is the topic name plus the
    first clause of its focus, for specificity."""
    name = topic["name"]
    queries = [f"{name} news"]

    first_clause = topic["focus"].split(".")[0].split(",")[0].strip()
    if first_clause and first_clause.lower() != name.lower():
        queries.append(f"{name}: {first_clause}")
    return queries


def build_queries(config: dict, now=None) -> list[dict]:
    """Deterministic query list: one or two per configured topic (name +
    focus), plus general-news queries if config['general_news'] is true.
    Capped at MAX_QUERIES total. `now` is accepted for a future
    time-sensitive query variant but isn't used yet - deterministic given
    the same config either way."""
    queries = []
    for topic in config["topics"]:
        for q in _topic_queries(topic):
            queries.append({"query": q, "section": topic["name"]})

    if config.get("general_news"):
        queries.append({"query": "world news today", "section": "general"})
        queries.append({"query": "top news today", "section": "general"})
        focus = (config.get("general_focus") or "").strip()
        if focus:
            queries.append({"query": focus, "section": "general"})

    return queries[:MAX_QUERIES]


def _search_one(query_obj: dict, lookback_days: int) -> list[dict]:
    query, section = query_obj["query"], query_obj["section"]
    try:
        response = _tavily_client.search(
            query=query,
            search_depth="basic",
            topic="news",
            days=lookback_days,
            max_results=SEARCH_MAX_RESULTS,
        )
    except Exception as e:
        print(f"[gather] search failed for {query!r}: {type(e).__name__}: {e}")
        return []

    if not response or "results" not in response:
        print(f"[gather] no results for {query!r}")
        return []

    results = []
    for r in response["results"][:SEARCH_MAX_RESULTS]:
        url = r.get("url", "")
        results.append({
            "section": section,
            "title": r.get("title", ""),
            "url": url,
            "domain": _domain_of(url),
            "snippet": r.get("content", "")[:500],
            "published": _to_date(r.get("published_date")),
            "source_query": query,
        })
    return results


def search_all(queries: list[dict], lookback_days: int, max_workers: int = MAX_SEARCH_WORKERS) -> list[dict]:
    """Run every query against Tavily in parallel. A failed query is
    printed and contributes no results rather than aborting the batch -
    _search_one already catches its own exceptions, so collecting
    future.result() here never raises."""
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_search_one, q, lookback_days) for q in queries]
        for future in as_completed(futures):
            results.extend(future.result())
    return results


def gather_feeds(sites: list[str], lookback_days: int) -> list[dict]:
    """Read each configured site's feed via find_feed/read_feed (the same
    tool functions the agent loop uses). A site with no declared feed, or
    a feed read error, is printed and skipped rather than aborting the
    others. Section is always "sites" - these aren't tied to one topic."""
    results = []
    for site in sites:
        feed_url = find_feed(site)
        if feed_url.startswith("Error:") or feed_url.startswith("No feed declared"):
            print(f"[gather] {site}: {feed_url}")
            continue

        raw = read_feed(feed_url, hours=lookback_days * 24, limit=20)
        if raw.startswith("Error:") or raw.startswith("No stories"):
            print(f"[gather] {site}: {raw}")
            continue

        try:
            stories = json.loads(raw)
        except json.JSONDecodeError:
            print(f"[gather] {site}: could not parse feed results")
            continue

        for s in stories:
            url = s.get("link", "")
            results.append({
                "section": "sites",
                "title": s.get("title", ""),
                "url": url,
                "domain": _domain_of(url),
                "snippet": s.get("summary", ""),
                "published": None,  # read_feed filters by hours but doesn't return the date
                "source_query": site,
            })
    return results


def assign_ids(candidates: list[dict]) -> list[dict]:
    """Give every candidate a stable short id (c1, c2, ...) in list order.
    Mutates and returns the same list."""
    for i, c in enumerate(candidates, start=1):
        c["id"] = f"c{i}"
    return candidates


def gather(config: dict, now=None) -> list[dict]:
    """Run the full gather stage: build queries, search Tavily, read
    feeds, assign ids. Returns one flat candidate list - no filtering."""
    queries = build_queries(config, now)
    candidates = search_all(queries, config["lookback_days"]) + gather_feeds(config["sites"], config["lookback_days"])
    return assign_ids(candidates)

from dotenv import load_dotenv
from registry import tool
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from trafilatura import fetch_url, extract
from tavily import TavilyClient
import httpx
import json
import feedparser
import html
import re

load_dotenv()

FEED_TYPES = {"application/rss+xml", "application/atom+xml"}
_tavily_client = TavilyClient()

@tool
def read_feed(url: str, hours: int = 24, limit: int = 15) -> str:
    """Read an RSS/Atom feed and return stories from the last `hours` hours,
    up to `limit` stories. Use when you have a feed URL. If you only have a
    website address, call find_feed first."""

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    feed = feedparser.parse(url)

    if not feed.entries:
        status = feed.get("status", "no response")
        reason = feed.get("bozo_exception", "no entries found")
        return f"Error: could not read a feed at {url} (status: {status}, reason: {reason}). This may be a website rather than a feed URL; try find_feed."

    stories = []
    source = feed.feed.get("title", url)
    for entry in feed.entries:
        if _is_recent(entry, cutoff):
            stories.append({
                "title": entry.get("title", ""),
                "source": source,
                "link": entry.get("link", ""),
                "summary": _clean(entry.get("summary")),
            })
            if len(stories) >= limit:
                break

    if not stories:
        return f"No stories in the last {hours} hours. The feed is valid and has {len(feed.entries)} older entries."

    return json.dumps(stories)

def _clean(text, limit=300):
    """Strip HTML tags, decode entities, and truncate."""
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()[:limit]

def _is_recent(entry, cutoff):
    t = entry.get("published_parsed")
    if not t:
        return True  # no date: keep it rather than silently drop it
    return datetime(*t[:6], tzinfo=timezone.utc) >= cutoff

@tool
def find_feed(url: str) -> str:
    """Find the RSS/Atom feed URL for a website.
    Use when given a website address (a homepage or article URL) rather than
    a feed URL. Returns the feed URL, which can be passed to read_feed.
    If no feed is declared, returns an error; fall back to search_web."""

    try:
        response = httpx.get(url, timeout=10, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as e:
        return f"Error: could not fetch {url} ({type(e).__name__}: {e})."

    soup = BeautifulSoup(response.text, "html.parser")

    for tag in soup.find_all("link"):
        rel = tag.get("rel") or []
        href = tag.get("href")
        if "alternate" in rel and tag.get("type") in FEED_TYPES and href:
            return urljoin(str(response.url), href)

    return f"No feed declared on {response.url}. Try search_web for this site instead."


@tool
def fetch_article(url: str) -> str:
    """Fetch the full text of an article, with navigation and ads stripped out.
    Use when a headline or summary alone isn't enough to judge relevance."""

    downloaded = fetch_url(url)
    if downloaded is None:
        return f"Error: could not fetch {url}."
    
    result = extract(downloaded, output_format="json", with_metadata=True)
    if result is None:
        return f"Error: could not extract article content from {url} (may be paywalled or JS-rendered)."
    
    data = json.loads(result)

    article = {
        "title": data.get("title", ""),
        "text": data.get("text", "")[:4000],   
    }

    return json.dumps(article)

@tool
def search_web(query: str, search_depth: str = "basic", max_results: int = 5, days: int = 3) -> str:
    """Search the web for a topic and return matching stories with titles,
    URLs, and short excerpts, restricted to the last `days` days. Use for
    topic-based sources with no feed, or when find_feed finds nothing for a
    given site. Put recency in `days`, not in the query text."""
    try:
        response = _tavily_client.search(
            query=query,
            search_depth=search_depth,
            topic="news",
            days=days,
        )
    except Exception as e:
        return f"Error: could not perform search for query '{query}' ({type(e).__name__}: {e})."

    if not response or "results" not in response:
        return f"Error: no results found for query '{query}'."

    results = []
    for result in response["results"][:max_results]:
        results.append({
            "title": result.get("title", ""),
            "link": result.get("url", ""),
            "summary": result.get("content", "")[:300],
            "score": result.get("score")
        })

    if not results:
        return f"No results found for query '{query}'."

    return json.dumps(results)



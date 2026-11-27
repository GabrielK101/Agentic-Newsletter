"""filter.py - the filter stage of the fixed (non-agentic) news pipeline.

Takes gather.py's flat candidate list and narrows it down: drop low-trust
domains, drop stale/already-seen items, dedupe exact-url duplicates,
cluster near-duplicate titles into one representative per story, then
shortlist and fetch full article text for the top candidates.

Every function here is pure except fetch_top, which makes network calls
(fetch_article) and drop_seen, which reads (never writes) the DB.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

from db import normalize_url, seen_url
from tools import fetch_article

# Mirrors digest.py's DENYLIST_DOMAINS (social platforms, not primary
# reporting) - kept separate rather than imported, so this pipeline has no
# import-time dependency on digest.py (which pulls in the model/delivery/
# storage stack). Keep the two lists in sync if either changes.
DENYLIST_DOMAINS = frozenset({
    "facebook.com", "x.com", "twitter.com", "instagram.com",
    "tiktok.com", "reddit.com", "youtube.com",
})

CLUSTER_THRESHOLD = 0.5
PER_SECTION_SHORTLIST = 8
TOTAL_SHORTLIST_CAP = 40
FETCH_TOP_K = 12
FETCH_MAX_WORKERS = 5
ARTICLE_TEXT_LIMIT = 3000

_STOPWORDS = frozenset({
    "a", "an", "the", "to", "of", "in", "on", "for", "and", "is", "are",
    "at", "as", "by", "with", "after", "over", "amid", "it", "its", "be",
    "will", "has", "have", "had", "from", "that", "this", "not",
})


def _is_denylisted(url: str) -> bool:
    host = urlparse(url or "").netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host in DENYLIST_DOMAINS or any(host.endswith("." + d) for d in DENYLIST_DOMAINS)


def drop_denylisted(candidates: list[dict]) -> list[dict]:
    return [c for c in candidates if not _is_denylisted(c.get("url", ""))]


def drop_stale(candidates: list[dict], lookback_days: int, today: date | None = None) -> list[dict]:
    """Drop items older than lookback_days. Undated items are always kept
    (we can't judge their age) with "published" normalized to None."""
    cutoff = ((today or date.today()) - timedelta(days=lookback_days)).isoformat()
    kept = []
    for c in candidates:
        published = c.get("published") or None
        c = {**c, "published": published}
        if published is not None and published < cutoff:
            continue
        kept.append(c)
    return kept


def drop_seen(candidates: list[dict]) -> list[dict]:
    """Drop anything whose url is already in the DB (db.seen_url)."""
    return [c for c in candidates if c.get("url") and not seen_url(c["url"])]


def dedupe_by_url(candidates: list[dict]) -> list[dict]:
    """Drop exact duplicate urls (by normalize_url), keeping the first
    occurrence - e.g. the same story returned by two different queries."""
    seen = set()
    kept = []
    for c in candidates:
        norm = normalize_url(c.get("url", ""))
        if norm in seen:
            continue
        seen.add(norm)
        kept.append(c)
    return kept


def _tokenize(title: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", (title or "").lower())
    return {t for t in tokens if t not in _STOPWORDS and len(t) > 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def _parse_date(s) -> date | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def cluster(candidates: list[dict], threshold: float = CLUSTER_THRESHOLD, today: date | None = None) -> list[dict]:
    """Group near-duplicate stories by title token overlap (Jaccard over
    non-stopword tokens >= threshold); different domains are allowed in
    the same cluster - that's the point, it's the same story reported by
    multiple outlets. Greedy single-pass clustering: a candidate joins the
    first existing cluster whose (fixed, first-member) token set clears
    the threshold, else starts a new cluster - order-dependent but
    deterministic for a given input order.

    Returns one representative dict per cluster (the most recently-dated
    member, falling back to the first member if none are dated), with
    "cluster_size" (member count) and "score" (distinct domains in the
    cluster + a recency term in [0, 1]) added."""
    today = today or date.today()
    clusters = []  # [{"tokens": set, "items": [candidate, ...]}]
    for c in candidates:
        tokens = _tokenize(c.get("title", ""))
        for cl in clusters:
            if _jaccard(tokens, cl["tokens"]) >= threshold:
                cl["items"].append(c)
                break
        else:
            clusters.append({"tokens": tokens, "items": [c]})

    representatives = []
    for cl in clusters:
        items = cl["items"]
        distinct_domains = len({i.get("domain", "") for i in items if i.get("domain")})

        dated = [(i, _parse_date(i.get("published"))) for i in items]
        dated = [(i, d) for i, d in dated if d is not None]
        if dated:
            representative, most_recent = max(dated, key=lambda pair: pair[1])
            recency_score = max(0.0, 1.0 - (today - most_recent).days / 7)
        else:
            representative = items[0]
            recency_score = 0.5  # neutral - we don't know how fresh an undated item is

        rep = {**representative, "cluster_size": len(items), "score": round(distinct_domains + recency_score, 3)}
        representatives.append(rep)
    return representatives


def shortlist(representatives: list[dict], per_section: int = PER_SECTION_SHORTLIST,
              total_cap: int = TOTAL_SHORTLIST_CAP) -> list[dict]:
    """Top `per_section` items per section by score, then the overall top
    `total_cap` across sections."""
    by_section: dict[str, list[dict]] = {}
    for r in representatives:
        by_section.setdefault(r.get("section", ""), []).append(r)

    capped = []
    for items in by_section.values():
        capped.extend(sorted(items, key=lambda x: x.get("score", 0), reverse=True)[:per_section])

    capped.sort(key=lambda x: x.get("score", 0), reverse=True)
    return capped[:total_cap]


def _fetch_targets(shortlisted: list[dict], k: int) -> list[dict]:
    """The items to actually fetch: every section's single highest-scoring
    item (always included, even if that pushes past k), topped up with
    the next-highest-scoring remaining items up to k total."""
    best_per_section: dict[str, dict] = {}
    for item in shortlisted:
        section = item.get("section", "")
        if section not in best_per_section or item.get("score", 0) > best_per_section[section].get("score", 0):
            best_per_section[section] = item

    required_ids = {item["id"] for item in best_per_section.values()}
    targets = list(best_per_section.values())
    for item in sorted(shortlisted, key=lambda x: x.get("score", 0), reverse=True):
        if len(targets) >= k:
            break
        if item["id"] not in required_ids:
            targets.append(item)
    return targets


def _fetch_one(item: dict) -> tuple[str, bool, str | None]:
    raw = fetch_article(item["url"])
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return item["id"], False, None
    text = parsed.get("text")
    if not text:
        return item["id"], False, None
    return item["id"], True, text[:ARTICLE_TEXT_LIMIT]


def fetch_top(shortlisted: list[dict], k: int = FETCH_TOP_K, max_workers: int = FETCH_MAX_WORKERS) -> list[dict]:
    """Fetch article text for the top k shortlisted items (always
    including the highest-scoring item per section), in parallel. Returns
    the full shortlisted list with "has_article"/"article_text" added:
    True/text for a successful fetch, False/None for an attempted-but-
    failed fetch, and None/None for an item that wasn't selected for
    fetching at all (so callers can tell "failed" from "not attempted")."""
    targets = _fetch_targets(shortlisted, k)
    outcomes: dict[str, tuple[bool, str | None]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_fetch_one, item) for item in targets]
        for future in as_completed(futures):
            item_id, ok, text = future.result()
            outcomes[item_id] = (ok, text)

    enriched = []
    for item in shortlisted:
        if item["id"] in outcomes:
            ok, text = outcomes[item["id"]]
        else:
            ok, text = None, None
        enriched.append({**item, "has_article": ok, "article_text": text})
    return enriched

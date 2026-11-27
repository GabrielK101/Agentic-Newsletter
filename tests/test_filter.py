"""pytest tests for filter.py: dedupe, stale filter, seen filter, clustering
on near-duplicate titles, shortlist caps, and the data-section fetch
requirements. Run with: pytest tests/test_filter.py -q
"""
import json
import sys
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline import filter as pipeline_filter


def _candidate(id_, section="tech", title="A headline", url=None, domain="example.com",
                published=None, snippet="snippet"):
    return {
        "id": id_, "section": section, "title": title,
        "url": url or f"https://{domain}/{id_}",
        "domain": domain, "snippet": snippet, "published": published,
        "source_query": "q",
    }


# --- drop_denylisted ---

def test_drop_denylisted_drops_social_domains():
    kept = pipeline_filter.drop_denylisted([
        _candidate("c1", domain="facebook.com", url="https://www.facebook.com/x/posts/1"),
        _candidate("c2", domain="reuters.com", url="https://reuters.com/a"),
    ])
    assert [c["id"] for c in kept] == ["c2"]


# --- drop_stale ---

def test_drop_stale_drops_old_but_keeps_undated():
    candidates = [
        _candidate("c1", published="2026-01-01"),   # old
        _candidate("c2", published=None),             # undated - always kept
        _candidate("c3", published=date.today().isoformat()),  # fresh
    ]
    kept = pipeline_filter.drop_stale(candidates, lookback_days=3, today=date.today())
    assert {c["id"] for c in kept} == {"c2", "c3"}


# --- drop_seen ---

def test_drop_seen_drops_urls_already_in_db():
    candidates = [
        _candidate("c1", url="https://example.com/already-told"),
        _candidate("c2", url="https://example.com/new"),
    ]
    with mock.patch.object(pipeline_filter, "seen_url", side_effect=lambda u: "already-told" in u):
        kept = pipeline_filter.drop_seen(candidates)
    assert [c["id"] for c in kept] == ["c2"]


# --- dedupe_by_url ---

def test_dedupe_by_url_keeps_first_occurrence():
    candidates = [
        _candidate("c1", url="https://example.com/a?utm_source=x"),
        _candidate("c2", url="https://example.com/a"),  # same story, normalizes equal
        _candidate("c3", url="https://example.com/b"),
    ]
    kept = pipeline_filter.dedupe_by_url(candidates)
    assert [c["id"] for c in kept] == ["c1", "c3"]


# --- cluster ---

def test_cluster_groups_near_duplicate_titles_across_domains():
    candidates = [
        _candidate("c1", title="Fed cuts interest rates by half a point", domain="reuters.com", published="2026-11-20"),
        _candidate("c2", title="Fed cuts interest rates half a point", domain="apnews.com", published="2026-11-21"),
        _candidate("c3", title="Totally unrelated sports result today", domain="espn.com", published="2026-11-21"),
    ]
    clustered = pipeline_filter.cluster(candidates, today=date(2026, 11, 21))
    assert len(clustered) == 2

    fed_cluster = next(c for c in clustered if "Fed" in c["title"])
    assert fed_cluster["cluster_size"] == 2
    # representative should be the most recently-dated member
    assert fed_cluster["id"] == "c2"

    sports_cluster = next(c for c in clustered if c["id"] == "c3")
    assert sports_cluster["cluster_size"] == 1


def test_cluster_does_not_merge_distinct_stories():
    candidates = [
        _candidate("c1", title="Haas confirms driver lineup for next season"),
        _candidate("c2", title="Mercedes announces new title sponsor deal"),
    ]
    clustered = pipeline_filter.cluster(candidates)
    assert len(clustered) == 2


# --- shortlist ---

def test_shortlist_caps_per_section_and_total():
    candidates = []
    for i in range(10):
        candidates.append({**_candidate(f"tech{i}", section="tech"), "score": 10 - i})
    for i in range(10):
        candidates.append({**_candidate(f"sport{i}", section="sport"), "score": 10 - i})

    result = pipeline_filter.shortlist(candidates, per_section=3, total_cap=40)
    by_section = {}
    for r in result:
        by_section.setdefault(r["section"], 0)
        by_section[r["section"]] += 1
    assert by_section == {"tech": 3, "sport": 3}


def test_shortlist_respects_total_cap():
    candidates = [{**_candidate(f"c{i}", section=f"s{i}"), "score": 1} for i in range(50)]
    result = pipeline_filter.shortlist(candidates, per_section=8, total_cap=5)
    assert len(result) == 5


# --- fetch_top: data-section items are always fetched ---

def _fake_fetch_article(text):
    def _fetch(url):
        return json.dumps({"title": "t", "text": text, "published": None})
    return _fetch


def test_fetch_top_always_fetches_every_data_item_even_with_low_score():
    # 15 high-scoring non-data items (more than k) plus 2 low-scoring data
    # items that would never make a plain top-k cut.
    shortlisted = [{**_candidate(f"n{i}"), "score": 100 - i} for i in range(15)]
    shortlisted += [
        {**_candidate("d1", section="data"), "score": 0},
        {**_candidate("d2", section="data"), "score": 0},
    ]
    with mock.patch.object(pipeline_filter, "fetch_article", side_effect=_fake_fetch_article("some text")):
        fetched = pipeline_filter.fetch_top(shortlisted, k=5)
    by_id = {f["id"]: f for f in fetched}
    assert by_id["d1"]["has_article"] is True
    assert by_id["d2"]["has_article"] is True


def test_fetch_top_uses_larger_text_limit_for_data_items():
    long_text = "word " * 2000  # longer than both limits
    with mock.patch.object(pipeline_filter, "fetch_article", side_effect=_fake_fetch_article(long_text)):
        fetched = pipeline_filter.fetch_top([
            {**_candidate("n1"), "score": 10},
            {**_candidate("d1", section="data"), "score": 10},
        ], k=5)
    by_id = {f["id"]: f for f in fetched}
    assert len(by_id["n1"]["article_text"]) == pipeline_filter.ARTICLE_TEXT_LIMIT
    assert len(by_id["d1"]["article_text"]) == pipeline_filter.ARTICLE_TEXT_LIMIT_DATA


# --- require_articles_for_data ---

def test_require_articles_for_data_drops_only_failed_data_items():
    items = [
        {**_candidate("n1"), "has_article": False},            # non-data, failed fetch - kept
        {**_candidate("n2"), "has_article": None},              # non-data, not attempted - kept
        {**_candidate("d1", section="data"), "has_article": True},   # data, succeeded - kept
        {**_candidate("d2", section="data"), "has_article": False},  # data, failed - dropped
        {**_candidate("d3", section="data"), "has_article": None},   # data, not attempted - dropped
    ]
    kept = pipeline_filter.require_articles_for_data(items)
    assert {i["id"] for i in kept} == {"n1", "n2", "d1"}

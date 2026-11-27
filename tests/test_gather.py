"""pytest tests for gather.py's deterministic query builder (no model, no
network). Run with: pytest tests/test_gather.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline import gather


def _config(**overrides):
    base = {
        "topics": [
            {"name": "Formula 1", "focus": "Race results and technical news.", "commentary": "none"},
            {"name": "Big tech", "focus": "Major business moves and AI. Skip reviews.", "commentary": "none"},
        ],
        "sites": ["https://example.com"],
        "general_news": True,
        "general_focus": "the biggest global stories of the day",
    }
    base.update(overrides)
    return base


def test_build_queries_deterministic():
    config = _config()
    assert gather.build_queries(config) == gather.build_queries(config)


def test_build_queries_includes_topic_and_general():
    queries = gather.build_queries(_config())
    sections = {q["section"] for q in queries}
    assert "Formula 1" in sections
    assert "Big tech" in sections
    assert "general" in sections


def test_build_queries_respects_cap():
    config = _config(topics=[
        {"name": f"Topic {i}", "focus": f"Focus for topic {i}, a long clause.", "commentary": "none"}
        for i in range(10)
    ])
    queries = gather.build_queries(config)
    assert len(queries) <= gather.MAX_QUERIES


def test_build_queries_skips_general_when_disabled():
    queries = gather.build_queries(_config(general_news=False))
    assert all(q["section"] != "general" for q in queries)


def test_assign_ids_is_stable_and_sequential():
    candidates = [{"title": "a"}, {"title": "b"}, {"title": "c"}]
    gather.assign_ids(candidates)
    assert [c["id"] for c in candidates] == ["c1", "c2", "c3"]

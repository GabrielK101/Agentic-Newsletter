"""pytest tests for pipeline/edit.py: candidate-id binding (resolving a
valid id, dropping an invented one) and the ticker/scoreboard numeric
guard. Run with: pytest tests/test_edit.py -q
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline import edit


def _candidate(id_, section="Finance", domain="reuters.com", url=None, published="2026-11-27",
                has_article=True, article_text="Some article text with a number 42 in it.", title="A headline"):
    return {
        "id": id_, "section": section, "domain": domain,
        "url": url or f"https://{domain}/{id_}",
        "published": published, "has_article": has_article,
        "article_text": article_text, "title": title,
    }


_LONG_BODY = "This happened and it matters a great deal to readers everywhere today. " * 2


def _lead_payload(candidate_id, **overrides):
    payload = {
        "id": candidate_id, "topic": "Finance", "headline": "Something Big Happened Today",
        "dek": "A short subhead adding one more fact for the reader to know about this.",
        "body": _LONG_BODY, "update_of": None,
    }
    payload.update(overrides)
    return payload


# --- id binding ---

def test_lead_with_valid_id_resolves_url_and_basis_from_candidate():
    candidates = [_candidate("c1", has_article=True)]
    reply = json.dumps({"lead": _lead_payload("c1")})
    digest = edit.parse_edit(reply, candidates)
    assert digest is not None
    assert digest["lead"]["url"] == candidates[0]["url"]
    assert digest["lead"]["basis"] == "article"


def test_lead_with_invented_id_is_dropped():
    candidates = [_candidate("c1")]
    reply = json.dumps({"lead": _lead_payload("c99")})
    assert edit.parse_edit(reply, candidates) is None


def test_lead_basis_is_snippet_when_candidate_has_no_article():
    candidates = [_candidate("c1", has_article=False, article_text=None)]
    reply = json.dumps({"lead": _lead_payload("c1")})
    digest = edit.parse_edit(reply, candidates)
    # basis="snippet" doesn't disqualify parse_edit itself - that business
    # rule lives downstream in front_page.prepare_front_page - but it must
    # be recorded correctly so that rule can act on it.
    assert digest is not None
    assert digest["lead"]["basis"] == "snippet"


def test_secondary_and_brief_drop_unknown_ids_but_keep_known_ones():
    candidates = [_candidate("c1"), _candidate("c2", domain="apnews.com")]
    reply = json.dumps({
        "lead": _lead_payload("c1"),
        "secondary": [
            {"id": "c2", "topic": "Finance", "summary": "Two full sentences describing what happened here today in enough words to clear the floor.",
             "headline": "Another Notable Thing Occurred", "update_of": None},
            {"id": "c77", "topic": "Finance", "summary": "x " * 20, "headline": "Invented Story", "update_of": None},
        ],
    })
    digest = edit.parse_edit(reply, candidates)
    assert len(digest["secondary"]) == 1
    assert digest["secondary"][0]["url"] == candidates[1]["url"]


def test_sources_are_code_derived_from_cited_candidates():
    candidates = [_candidate("c1", domain="reuters.com")]
    reply = json.dumps({"lead": _lead_payload("c1")})
    digest = edit.parse_edit(reply, candidates)
    assert digest["sources"] == [{"name": "Reuters", "url": "https://reuters.com"}]


# --- numeric guard ---

def test_ticker_entry_passes_when_numbers_appear_in_source_text():
    candidates = [_candidate("c1", article_text="The S&P 500 closed at 6,812.40, up 1.2% on the day.")]
    reply = json.dumps({
        "lead": _lead_payload("c1"),
        "ticker": [{"source": "c1", "label": "S&P 500", "value": "6,812.40", "change": "+1.2%", "direction": "up"}],
    })
    digest = edit.parse_edit(reply, candidates)
    assert len(digest["ticker"]) == 1


def test_ticker_entry_dropped_when_numbers_not_in_source_text():
    candidates = [_candidate("c1", article_text="The S&P 500 closed higher today on AI optimism.")]
    reply = json.dumps({
        "lead": _lead_payload("c1"),
        "ticker": [{"source": "c1", "label": "S&P 500", "value": "6,812.40", "change": "+1.2%", "direction": "up"}],
    })
    digest = edit.parse_edit(reply, candidates)
    assert digest["ticker"] == []


def test_ticker_entry_dropped_when_source_has_no_article_text():
    candidates = [_candidate("c1", has_article=False, article_text=None)]
    reply = json.dumps({
        "lead": _lead_payload("c1"),
        "ticker": [{"source": "c1", "label": "S&P 500", "value": "6,812.40", "change": "+1.2%", "direction": "up"}],
    })
    digest = edit.parse_edit(reply, candidates)
    assert digest["ticker"] == []


def test_ticker_entry_dropped_when_source_id_invented():
    candidates = [_candidate("c1")]
    reply = json.dumps({
        "lead": _lead_payload("c1"),
        "ticker": [{"source": "c99", "label": "S&P 500", "value": "6,812.40", "change": "+1.2%", "direction": "up"}],
    })
    digest = edit.parse_edit(reply, candidates)
    assert digest["ticker"] == []


def test_scoreboard_line_with_no_numbers_trivially_passes():
    candidates = [_candidate("c1", article_text="Verstappen won ahead of Norris and Piastri.")]
    reply = json.dumps({
        "lead": _lead_payload("c1"),
        "scoreboard": [{"source": "c1", "group": "Formula 1", "label": "", "line": "Verstappen, Norris, Piastri"}],
    })
    digest = edit.parse_edit(reply, candidates)
    assert len(digest["scoreboard"]) == 1


def test_scoreboard_line_dropped_when_score_not_in_source_text():
    candidates = [_candidate("c1", article_text="Arsenal beat Chelsea at the Emirates on Saturday.")]
    reply = json.dumps({
        "lead": _lead_payload("c1"),
        "scoreboard": [{"source": "c1", "group": "Premier League", "label": "", "line": "Arsenal 2-1 Chelsea"}],
    })
    digest = edit.parse_edit(reply, candidates)
    assert digest["scoreboard"] == []


# --- multi-candidate extraction (bad draft before good object) ---

def test_parse_edit_recovers_good_object_after_bad_draft():
    candidates = [_candidate("c1")]
    good = json.dumps({"lead": _lead_payload("c1")})
    text = f'Let me think.\n{{"draft": true}}\nHere is my answer:\n{good}\n'
    digest = edit.parse_edit(text, candidates)
    assert digest is not None
    assert digest["lead"]["url"] == candidates[0]["url"]


def test_parse_edit_returns_none_with_no_usable_object():
    candidates = [_candidate("c1")]
    assert edit.parse_edit("no json here", candidates) is None
    assert edit.parse_edit('{"draft": true}', candidates) is None

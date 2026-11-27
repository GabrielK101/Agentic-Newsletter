"""pytest tests for the IMPLEMENTATION_PROMPT.md upgrade: clamp_summary's
abbreviation handling, render_email_html's email-client constraints, and
oversize trimming. Run with: pytest tests/test_email_render.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from email_render import _MAX_HTML_BYTES, render_email_html, render_email_text
from newsletter_render import clamp_summary


# --- clamp_summary: abbreviations and initials must not look like sentence ends ---

def test_clamp_summary_keeps_corp_abbreviation():
    text = (
        "Oregon and Virginia sued SpaceX (which owns X Corp.) over Grok deepfakes. "
        "The suits seek damages and an injunction against the tool."
    )
    result = clamp_summary(text, 14)
    assert result.endswith("deepfakes.")
    assert "Corp.)" in result


def test_clamp_summary_keeps_us_abbreviation():
    text = "The U.S. economy grew 2.1%. Markets rose sharply on the news today."
    result = clamp_summary(text, 8)
    assert result == "The U.S. economy grew 2.1%."


def test_clamp_summary_keeps_initial():
    text = "J. Smith won the award. The ceremony was held in London on Friday."
    result = clamp_summary(text, 6)
    assert result.startswith("J. Smith won the award.")


def test_clamp_summary_hard_cut_with_ellipsis_when_no_boundary():
    text = "Shares jumped Then they fell back again as traders took profits on the day"
    result = clamp_summary(text, 6)
    assert result.endswith("…")


def test_clamp_summary_under_limit_is_unchanged():
    text = "Short and simple."
    assert clamp_summary(text, 20) == text


# --- render_email_html: structural/email-client constraints ---

def _sample_front_page():
    return {
        "lead": {
            "topic": "Finance", "headline": "Markets Rally on Rate Cut Hopes",
            "dek": "Investors bet on a December cut after cooler inflation data.",
            "body": "Stocks rose sharply on Friday.\n\nThe move extended a weekly rally.",
            "url": "https://example.com/lead", "sources": ["Reuters", "AP"],
            "published": "2026-11-20", "update_of": None, "follows": None,
        },
        "secondary": [
            {"topic": "Big tech", "headline": "A headline with <b>&\"</b> escaping", "summary": "A" * 50,
             "url": "https://example.com/s1", "published": "2026-11-20", "follows": None},
        ],
        "sections": [
            {"name": "Formula 1", "briefs": [
                {"headline": "Verstappen wins", "summary": "He won the race on Sunday.",
                 "url": "https://example.com/b1", "published": "2026-11-20", "follows": None},
            ]},
            {"name": "Big tech", "briefs": []},  # empty - must be skipped
        ],
        "ticker": [
            {"label": "S&P 500", "value": "6,812.40", "change": "+1.2%", "direction": "up", "session_day": "Fri"},
        ],
        "scoreboard": [
            {"group": "Formula 1", "label": "Las Vegas GP", "line": "Verstappen · Norris · Piastri"},
            {"group": "Formula 1", "label": "Drivers", "line": "Antonelli leads by 98 pts"},
        ],
        "sources": [{"name": "Reuters", "url": "https://reuters.com"}],
        "disclosure": "Built by an automated agent.",
        "notes": "",
    }


def test_render_email_html_under_size_budget():
    html_out = render_email_html(_sample_front_page(), title="Test Digest", date_str="Mon 23 Nov")
    assert len(html_out.encode("utf-8")) < _MAX_HTML_BYTES


def test_render_email_html_forbidden_features_absent():
    html_out = render_email_html(_sample_front_page(), title="Test Digest", date_str="Mon 23 Nov")
    for forbidden in ("display:grid", "display:flex", "<svg", "<script", "@import", "position:"):
        assert forbidden not in html_out, forbidden
    # <link> other than Google Fonts isn't used at all in the email (no web fonts)
    assert "<link" not in html_out


def test_render_email_html_every_href_is_http_or_absent():
    import re
    html_out = render_email_html(_sample_front_page(), title="Test Digest", date_str="Mon 23 Nov")
    hrefs = re.findall(r'href="([^"]*)"', html_out)
    assert hrefs  # the fixture has real urls, so there should be some
    for href in hrefs:
        assert href.startswith("http://") or href.startswith("https://") or href == "#"


def test_render_email_html_preheader_present_and_short():
    html_out = render_email_html(_sample_front_page(), title="Test Digest", date_str="Mon 23 Nov")
    assert "mso-hide:all" in html_out
    start = html_out.find("mso-hide:all;\">") + len("mso-hide:all;\">")
    end = html_out.find("</div>", start)
    preheader_text = html_out[start:end]
    # strip the invisible padding entities before measuring length
    visible = preheader_text.split("&#847;")[0]
    assert len(visible) <= 110


def test_render_email_html_ticker_present_when_given():
    html_out = render_email_html(_sample_front_page(), title="Test Digest", date_str="Mon 23 Nov")
    assert "S&amp;P 500" in html_out or "S&P 500" in html_out


def test_render_email_html_ticker_absent_when_empty():
    fp = _sample_front_page()
    fp["ticker"] = []
    html_out = render_email_html(fp, title="Test Digest", date_str="Mon 23 Nov")
    assert "S&P 500" not in html_out and "S&amp;P 500" not in html_out


def test_render_email_html_scoreboard_absent_when_empty():
    fp = _sample_front_page()
    fp["scoreboard"] = []
    html_out = render_email_html(fp, title="Test Digest", date_str="Mon 23 Nov")
    assert "Scoreboard" not in html_out


def test_render_email_html_empty_section_skipped_no_placeholder():
    html_out = render_email_html(_sample_front_page(), title="Test Digest", date_str="Mon 23 Nov")
    assert "Nothing new today" not in html_out


def test_render_email_html_escapes_hostile_headline():
    html_out = render_email_html(_sample_front_page(), title="Test Digest", date_str="Mon 23 Nov")
    assert "<b>&\"</b>" not in html_out
    assert "&lt;b&gt;" in html_out


def test_render_email_html_sections_in_configured_order():
    html_out = render_email_html(_sample_front_page(), title="Test Digest", date_str="Mon 23 Nov")
    # only Formula 1 has briefs - Big tech (empty) must not appear as a section heading.
    assert "letter-spacing:3px;text-transform:uppercase;color:#1b1a17;\">Formula 1</div>" in html_out


def test_render_email_text_contains_lead_and_web_link():
    text_out = render_email_text(_sample_front_page(), title="Test Digest",
                                  web_url="https://example.com/edition", date_str="Mon 23 Nov")
    assert "Markets Rally on Rate Cut Hopes" in text_out
    assert "https://example.com/edition" in text_out


def test_render_email_html_oversize_trims_last_section_first():
    fp = _sample_front_page()
    long_summary = "This is a long brief summary sentence that repeats. " * 4
    fp["sections"] = [
        {"name": "Formula 1", "briefs": [
            {"headline": f"F1 brief {i}", "summary": long_summary, "url": f"https://example.com/f1-{i}",
             "published": "2026-11-20", "follows": None}
            for i in range(30)
        ]},
        {"name": "Big tech", "briefs": [
            {"headline": f"Tech brief {i}", "summary": long_summary, "url": f"https://example.com/tech-{i}",
             "published": "2026-11-20", "follows": None}
            for i in range(30)
        ]},
    ]
    html_out = render_email_html(fp, title="Test Digest", date_str="Mon 23 Nov")
    assert len(html_out.encode("utf-8")) <= _MAX_HTML_BYTES
    # the earlier section (Formula 1) should have survived better than the later one
    assert "F1 brief 0" in html_out


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))

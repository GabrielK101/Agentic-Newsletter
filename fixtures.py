"""fixtures.py - a canned front-page digest for exercising rendering/
delivery without calling the model or any tools."""
from datetime import date, timedelta


def fixture_stories(config: dict) -> dict:
    """A front-page digest shaped exactly like parse_digest's output:
    {lead, secondary, sections, ticker, scoreboard, sources, disclosure,
    notes}. Covers a long and a short example, one empty section (the
    quiet-day case), no ticker, a scoreboard, one deliberately hostile
    item (<script> headline, javascript: url) for escaping/safe_url, a
    headline-only item (empty summary - should be dropped by the summary
    floor), a missing-date item (no "published" at all - shows no date,
    never inferred), an over-long summary (should be clamped), a mix of
    today/yesterday/older dates to exercise every relative-date case, a
    snippet-basis lead (should be dropped and a secondary promoted in its
    place), and a story citing a denylisted domain (should be dropped)."""
    topics = [t["name"] for t in config["topics"]] or ["General"]
    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()
    # 2 days old: within the default 3-day lookback window (so it survives
    # prepare_front_page's freshness filter and actually renders), but old
    # enough that format_relative_date must show the explicit weekday/day/
    # month form, not "Today"/"Yesterday".
    older = (today - timedelta(days=2)).isoformat()
    today = today.isoformat()

    long_body = (
        "This is a longer fixture body meant to sit near the word limit used "
        "for a real lead story, so a hero card's wrapping and line height can "
        "be checked visually.\n\n"
        "It continues into a second short paragraph, the way a real "
        "front-page lead would, to make sure a multi-paragraph body renders "
        "sensibly end to end."
    )
    short_summary = "Short summary, one sentence only, nothing more to add."  # 9 words - clears the 8-word floor
    over_long_summary = (
        "This brief's summary runs deliberately far past its own word ceiling "
        "so clamp_summary's truncation is actually visible in the rendered "
        "output rather than just asserted in a test - it keeps going with "
        "more clauses about the same minor story, repeating that nothing "
        "else of substance happened today beyond this one small development, "
        "well past the point any brief-tier item should ever need to reach "
        "in a real digest, to make the cut-off unmistakable."
    )

    lead = {
        "topic": topics[0],
        "headline": "Fixture hero story leads the whole front page",
        "dek": "A one-line subhead that expands on the headline.",
        "body": long_body,
        "url": "https://example.com/fixture-lead",
        "sources": ["Example Wire", "Example Daily"],
        "basis": "snippet",  # deliberately not "article" - should be dropped, promoting a secondary instead
        "published": today,
        "update_of": None,
    }

    secondary = [
        {
            "topic": topics[1 % len(topics)],
            "headline": "Fixture secondary story, long",
            "summary": (
                "A longer fixture summary for a secondary story, long enough "
                "to wrap across a couple of lines in a major-tier card."
            ),
            "url": "https://example.com/fixture-secondary-1",
            "basis": "article",
            "published": today,
            "update_of": None,
        },
        {
            "topic": topics[2 % len(topics)],
            "headline": "Fixture secondary story, short",
            "summary": short_summary,
            "url": "https://example.com/fixture-secondary-2",
            "basis": "article",
            "published": today,
            "update_of": None,
        },
        {
            "topic": topics[0],
            "headline": "Fixture secondary story with no published date",
            "summary": "This item has no \"published\" key at all - the kicker should show no date.",
            "url": "https://example.com/fixture-secondary-3",
            "basis": "article",
            "update_of": None,
            # no "published" key - defensive parsing must show nothing, never infer today.
        },
        {
            "topic": topics[0],
            "headline": "Fixture secondary story citing a denylisted domain",
            "summary": "Sourced only from a social platform, not a primary outlet, so it should be dropped outright.",
            "url": "https://www.facebook.com/example/posts/12345",
            "basis": "article",
            "published": today,
            "update_of": None,
        },
    ]

    sections = [
        {
            "name": topics[0],
            "briefs": [
                {
                    "headline": "Fixture brief with a follow-up reference",
                    "summary": short_summary,
                    "url": "https://example.com/fixture-brief-1",
                    "published": today,
                    "update_of": 1,
                },
                {
                    "headline": "<script>alert(1)</script> AT&T",
                    "summary": "AT&T said <b>nothing</b> official yet about the breach.",
                    "url": "javascript:alert(1)",
                    "published": today,
                    "update_of": None,
                },
                {
                    "headline": "Fixture headline-only brief with no summary",
                    "summary": "",
                    "url": "https://example.com/fixture-brief-headline-only",
                    "published": today,
                    "update_of": None,
                },
                {
                    "headline": "Fixture brief from yesterday",
                    "summary": "Dated yesterday, so the kicker should read \"Yesterday\".",
                    "url": "https://example.com/fixture-brief-yesterday",
                    "published": yesterday,
                    "update_of": None,
                },
            ],
        },
        {
            "name": topics[1 % len(topics)] if len(topics) > 1 else "Big tech",
            "briefs": [],  # a quiet day - nothing new for this section
        },
        {
            "name": "World",
            "briefs": [
                {
                    "headline": "Fixture World brief",
                    "summary": short_summary,
                    "url": "https://example.com/fixture-world-1",
                    "published": today,
                    "update_of": None,
                },
                {
                    "headline": "Fixture World brief with an over-long summary",
                    "summary": over_long_summary,
                    "url": "https://example.com/fixture-world-2",
                    "published": today,
                    "update_of": None,
                },
            ],
        },
        {
            "name": "Worth knowing",
            "briefs": [
                {
                    "headline": "Fixture Worth-knowing brief",
                    "summary": short_summary,
                    "url": "https://example.com/fixture-worth-knowing-1",
                    "published": today,
                    "update_of": None,
                },
                {
                    "headline": "Fixture Worth-knowing brief, a couple of days old",
                    "summary": "Dated two days ago, so the kicker should show the explicit weekday/day/month, not \"Today\".",
                    "url": "https://example.com/fixture-worth-knowing-2",
                    "published": older,
                    "update_of": None,
                },
            ],
        },
    ]

    scoreboard = [
        {"label": "Formula 1", "line": "Fixture GP: Driver A won, Driver B second."},
    ]

    sources = [
        {"name": "Example Wire", "url": "https://example.com"},
        {"name": "Example Daily", "url": None},
    ]

    return {
        "lead": lead,
        "secondary": secondary,
        "sections": sections,
        "ticker": [],  # deliberately omitted - no real tool-sourced market data here
        "scoreboard": scoreboard,
        "sources": sources,
        "disclosure": "This digest is produced by an automated agent and may contain errors.",
        "notes": "Fixture test run - no real sources were read.",
    }

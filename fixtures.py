"""fixtures.py - a canned front-page digest for exercising rendering/
delivery without calling the model or any tools."""
from datetime import date


def fixture_stories(config: dict) -> dict:
    """A front-page digest shaped exactly like parse_digest's output:
    {lead, secondary, sections, ticker, scoreboard, sources, disclosure,
    notes}. Covers a long and a short example, one empty section (the
    quiet-day case), no ticker, a scoreboard, and one deliberately hostile
    item (<script> headline, javascript: url) for escaping/safe_url."""
    topics = [t["name"] for t in config["topics"]] or ["General"]
    today = date.today().isoformat()

    long_body = (
        "This is a longer fixture body meant to sit near the word limit used "
        "for a real lead story, so a hero card's wrapping and line height can "
        "be checked visually.\n\n"
        "It continues into a second short paragraph, the way a real "
        "front-page lead would, to make sure a multi-paragraph body renders "
        "sensibly end to end."
    )
    short_summary = "Short summary, one sentence only."

    lead = {
        "topic": topics[0],
        "headline": "Fixture hero story leads the whole front page",
        "dek": "A one-line subhead that expands on the headline.",
        "body": long_body,
        "url": "https://example.com/fixture-lead",
        "sources": ["Example Wire", "Example Daily"],
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
            "published": today,
            "update_of": None,
        },
        {
            "topic": topics[2 % len(topics)],
            "headline": "Fixture secondary story, short",
            "summary": short_summary,
            "url": "https://example.com/fixture-secondary-2",
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

"""fixtures.py - canned test stories for exercising rendering/delivery
without calling the model or any tools."""
from datetime import date


def fixture_stories(config: dict, count: int = 15) -> list[dict]:
    """Canned stories for testing rendering/delivery without calling the
    model or any tools. Covers every tier (1 hero, 2 major, standard, brief),
    mixed topics and basis types, an update_of reference, summaries of very
    different lengths, and one deliberately hostile story for escaping."""
    count = max(1, min(count, 15))
    topics = [t["name"] for t in config["topics"]]
    today = date.today().isoformat()

    long_summary = (
        "This is a longer fixture summary meant to sit near the ninety word "
        "limit used for real digest stories, so a card's wrapping and line "
        "height can be checked visually. It keeps going for a few more "
        "clauses to make sure there is enough text to actually wrap across "
        "several lines inside a narrow email column, rather than fitting on "
        "one short line that would not reveal any layout problems at all."
    )
    short_summary = "Short summary, one sentence only."
    two_sentence_summary = "First sentence of this brief. Second sentence should be dropped."
    no_period_summary = (
        "A run of text with no sentence ending punctuation at all so the "
        "first sentence helper has to fall back to a plain character limit "
        "instead of finding a period question mark or exclamation mark"
    )
    hostile_summary = "AT&T said <b>nothing</b> official yet about the breach."

    # (basis, update_of, tier_or_"lead", summary, headline, url_override, has_image)
    # Roughly half carry an image, and every tier has both with and without,
    # so layouts that depend on image presence get exercised either way.
    template = [
        ("article", None, "lead", long_summary, "Fixture hero story leads the whole digest", None, True),
        ("article", None, 3, long_summary, "Fixture major story number one", None, True),
        ("snippet", None, 3, short_summary, "Fixture major story number two (snippet basis)", None, False),
        ("article", 1, 2, short_summary, "Fixture standard story with an update_of reference", None, True),
        ("article", None, 2, short_summary, "Fixture standard story two", None, False),
        ("article", None, 2, short_summary, "Fixture standard story three", None, True),
        ("article", None, 2, long_summary, "Fixture standard story four, long summary", None, False),
        ("article", None, 1, two_sentence_summary, "Fixture brief with two sentences", None, True),
        ("article", None, 1, no_period_summary, "Fixture brief with no sentence break", None, False),
        ("article", None, 1, short_summary, "Fixture brief story three", None, True),
        ("article", None, 1, hostile_summary, "<script>alert(1)</script> AT&T", "javascript:alert(1)", False),
        ("article", None, 2, short_summary, "Fixture standard story five", None, False),
        ("snippet", None, 1, short_summary, "Fixture brief story four", None, True),
        ("article", None, 3, short_summary, "Fixture extra major-weight story", None, False),
        ("article", None, 2, short_summary, "Fixture standard story six", None, True),
    ]

    stories = []
    for i, (basis, update_of, tier, summary, headline, url_override, has_image) in enumerate(template[:count]):
        is_lead = tier == "lead"
        stories.append({
            "topic": topics[i % len(topics)],
            "headline": headline,
            "summary": summary,
            "url": url_override or f"https://example.com/fixture-story-{i + 1}",
            "image_url": f"https://picsum.photos/seed/{i + 1}/800/450" if has_image else None,
            "published": today,
            "basis": basis,
            "update_of": update_of,
            "lead": is_lead,
            "weight": 2 if is_lead else tier,
        })
    return stories

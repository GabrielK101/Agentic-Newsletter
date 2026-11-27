"""tests/test_parse_digest.py - unit tests for agent_loop.parse_digest's
multi-candidate JSON extraction (it must skip a bad draft object and find
the good one that follows it, scanning every "{" rather than just the
first-to-last-brace span).

Run with: python tests/test_parse_digest.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # project root, for `import agent_loop`

from agent_loop import parse_digest

GOOD_LEAD = """{
  "lead": {
    "headline": "A real headline that is long enough to clear the floor",
    "body": "This is the real body text with plenty of words in it so it clears the summary word floor easily.",
    "url": "https://example.com/real-story"
  }
}"""

# A draft object that LOOKS like JSON but is missing a usable lead (no
# headline), followed by prose, followed by the real object.
BAD_DRAFT_THEN_GOOD = f"""
Let me think about candidates first.
{{"draft": true, "candidates": ["story a", "story b"]}}
Actually here's my real answer:
{GOOD_LEAD}
"""

# A draft that is truncated / syntactically broken JSON, followed by the
# real object - raw_decode must recover after the broken brace instead of
# giving up on the whole text.
TRUNCATED_DRAFT_THEN_GOOD = f"""
{{"lead": {{"headline": "truncated, no closing
{GOOD_LEAD}
"""

try:
    # Baseline: the good object alone parses.
    result = parse_digest(GOOD_LEAD)
    assert result is not None, "the good object alone should parse"
    assert result["lead"]["headline"].startswith("A real headline")

    # A bad (schema-invalid) draft before the good object must not prevent
    # the good object from being found - it should be the LAST valid match.
    result = parse_digest(BAD_DRAFT_THEN_GOOD)
    assert result is not None, "parse_digest must recover the good object after a bad draft"
    assert result["lead"]["headline"].startswith("A real headline")

    # A syntactically broken draft before the good object: raw_decode must
    # fail on the broken brace and keep scanning forward, not abort.
    result = parse_digest(TRUNCATED_DRAFT_THEN_GOOD)
    assert result is not None, "parse_digest must recover after a syntactically broken draft"
    assert result["lead"]["headline"].startswith("A real headline")

    # No usable object anywhere -> None, not an exception.
    assert parse_digest("no json here at all") is None
    assert parse_digest('{"draft": true}') is None  # no lead at all

    print("all tests passed")
except AssertionError as e:
    print(f"FAILED: {e}")
    sys.exit(1)

"""config.py - load and validate config.yaml."""
import os
from pathlib import Path

import yaml

_VALID_COMMENTARY = {"none", "context", "analysis"}
_TOP_LEVEL_KEYS = {
    "lookback_days", "history_days", "topics", "sites", "title", "tagline",
    "recipient", "general_news", "general_focus",
}
_DEFAULT_GENERAL_FOCUS = (
    "the biggest global stories of the day, plus one or two genuinely "
    "interesting or unexpected stories"
)
_TOPIC_KEYS = {"name", "focus", "commentary", "data"}
_VALID_TICKER_KEYS = {"sp500", "nasdaq", "dow", "ftse", "brent", "gbpusd"}
_VALID_SPORTS_KEYS = {"f1", "premier_league"}


def load_config(path: str | None = None) -> dict:
    """Load and validate the run config.

    Path order: the `path` argument, then env DIGEST_CONFIG, then
    config.yaml next to this file.
    """
    if path is None:
        path = os.environ.get("DIGEST_CONFIG")
    if path is None:
        path = Path(__file__).parent / "config.yaml"
    path = Path(path)

    if not path.exists():
        raise ValueError(
            f"config file not found at {path}. Copy config.example.yaml to "
            f"{path.name} and edit it."
        )

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"config at {path} must be a mapping, got {type(raw).__name__}")

    unknown = set(raw) - _TOP_LEVEL_KEYS
    if unknown:
        raise ValueError(f"config has unknown key(s): {sorted(unknown)}")

    _require_int_at_least_1(raw, "lookback_days")
    _require_int_at_least_1(raw, "history_days")

    if "topics" not in raw:
        raise ValueError("config is missing required key 'topics'")
    if not isinstance(raw["topics"], list) or not raw["topics"]:
        raise ValueError("config key 'topics' must be a non-empty list")

    for i, topic in enumerate(raw["topics"]):
        if not isinstance(topic, dict):
            raise ValueError(f"config key 'topics[{i}]' must be a mapping")

        unknown_topic_keys = set(topic) - _TOPIC_KEYS
        if unknown_topic_keys:
            raise ValueError(f"config key 'topics[{i}]' has unknown key(s): {sorted(unknown_topic_keys)}")

        if not isinstance(topic.get("name"), str) or not topic["name"].strip():
            raise ValueError(f"config key 'topics[{i}].name' is required and must be a non-empty string")

        if not isinstance(topic.get("focus"), str) or not topic["focus"].strip():
            raise ValueError(f"config key 'topics[{i}].focus' is required and must be a non-empty string")
        topic["focus"] = topic["focus"].strip()  # folded `>` strings carry trailing whitespace

        topic.setdefault("commentary", "none")
        if topic["commentary"] not in _VALID_COMMENTARY:
            raise ValueError(
                f"config key 'topics[{i}].commentary' must be one of "
                f"{sorted(_VALID_COMMENTARY)}, got {topic['commentary']!r}"
            )

        data = topic.setdefault("data", {})
        if not isinstance(data, dict):
            raise ValueError(f"config key 'topics[{i}].data' must be a mapping, got {type(data).__name__}")
        unknown_data_keys = set(data) - {"ticker", "sports"}
        if unknown_data_keys:
            raise ValueError(f"config key 'topics[{i}].data' has unknown key(s): {sorted(unknown_data_keys)}")
        if "ticker" in data:
            if not isinstance(data["ticker"], list) or not all(isinstance(k, str) for k in data["ticker"]):
                raise ValueError(f"config key 'topics[{i}].data.ticker' must be a list of strings")
            unknown_ticker = set(data["ticker"]) - _VALID_TICKER_KEYS
            if unknown_ticker:
                raise ValueError(
                    f"config key 'topics[{i}].data.ticker' has unknown instrument(s) "
                    f"{sorted(unknown_ticker)}; valid: {sorted(_VALID_TICKER_KEYS)}"
                )
        if "sports" in data:
            if not isinstance(data["sports"], list) or not all(isinstance(k, str) for k in data["sports"]):
                raise ValueError(f"config key 'topics[{i}].data.sports' must be a list of strings")
            unknown_sports = set(data["sports"]) - _VALID_SPORTS_KEYS
            if unknown_sports:
                raise ValueError(
                    f"config key 'topics[{i}].data.sports' has unknown value(s) "
                    f"{sorted(unknown_sports)}; valid: {sorted(_VALID_SPORTS_KEYS)}"
                )

    if "sites" not in raw:
        raise ValueError("config is missing required key 'sites'")
    if not isinstance(raw["sites"], list):
        raise ValueError("config key 'sites' must be a list")

    for i, site in enumerate(raw["sites"]):
        if not isinstance(site, str) or not site.startswith(("http://", "https://")):
            raise ValueError(f"config key 'sites[{i}]' must be a string starting with http:// or https://")

    raw.setdefault("title", "The Daily Digest")
    if not isinstance(raw["title"], str) or not raw["title"].strip():
        raise ValueError(f"config key 'title' must be a non-empty string, got {raw['title']!r}")

    tagline = raw.get("tagline")
    if tagline is not None and (not isinstance(tagline, str) or not tagline.strip()):
        raise ValueError(f"config key 'tagline' must be a non-empty string if present, got {tagline!r}")
    raw["tagline"] = tagline

    recipient = raw.get("recipient")
    if recipient is not None and (not isinstance(recipient, str) or not recipient.strip()):
        raise ValueError(f"config key 'recipient' must be a non-empty string if present, got {recipient!r}")
    raw["recipient"] = recipient  # None means "fall back to DIGEST_TO"

    raw.setdefault("general_news", True)
    if not isinstance(raw["general_news"], bool):
        raise ValueError(f"config key 'general_news' must be true or false, got {raw['general_news']!r}")

    raw.setdefault("general_focus", _DEFAULT_GENERAL_FOCUS)
    if not isinstance(raw["general_focus"], str) or not raw["general_focus"].strip():
        raise ValueError(f"config key 'general_focus' must be a non-empty string, got {raw['general_focus']!r}")

    return raw


def _require_int_at_least_1(raw: dict, key: str) -> None:
    if key not in raw:
        raise ValueError(f"config is missing required key '{key}'")
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"config key '{key}' must be an integer >= 1, got {value!r}")

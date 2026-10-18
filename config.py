"""config.py - load and validate config.yaml."""
import os
from pathlib import Path

import yaml

_VALID_COMMENTARY = {"none", "context", "analysis"}


def load_config() -> dict:
    """Load and validate the run config. Path from env DIGEST_CONFIG, else ./config.yaml."""
    path = Path(os.environ.get("DIGEST_CONFIG", "config.yaml"))
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"config at {path} must be a mapping, got {type(raw).__name__}")

    _require(raw, "lookback_days", int)
    _require(raw, "history_days", int)
    _require(raw, "topics", list)
    _require(raw, "sites", list)

    if not raw["topics"]:
        raise ValueError("config key 'topics' must not be empty")

    for i, topic in enumerate(raw["topics"]):
        if not isinstance(topic, dict):
            raise ValueError(f"config key 'topics[{i}]' must be a mapping")
        if not isinstance(topic.get("name"), str) or not topic["name"]:
            raise ValueError(f"config key 'topics[{i}].name' is required and must be a non-empty string")
        if not isinstance(topic.get("focus"), str) or not topic["focus"]:
            raise ValueError(f"config key 'topics[{i}].focus' is required and must be a non-empty string")
        topic.setdefault("commentary", "none")
        if topic["commentary"] not in _VALID_COMMENTARY:
            raise ValueError(
                f"config key 'topics[{i}].commentary' must be one of "
                f"{sorted(_VALID_COMMENTARY)}, got {topic['commentary']!r}"
            )

    for i, site in enumerate(raw["sites"]):
        if not isinstance(site, str) or not site:
            raise ValueError(f"config key 'sites[{i}]' must be a non-empty string")

    return raw


def _require(raw: dict, key: str, expected_type: type) -> None:
    if key not in raw:
        raise ValueError(f"config is missing required key '{key}'")
    if not isinstance(raw[key], expected_type):
        raise ValueError(
            f"config key '{key}' must be of type {expected_type.__name__}, "
            f"got {type(raw[key]).__name__}"
        )

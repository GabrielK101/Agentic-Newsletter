"""delivery.py - deliver the finished digest.

Backend chosen by env DIGEST_DELIVERY (local|email|webhook). "local" is
today's behaviour: print to stdout and write dated files under digests/.
"""
import json
import os
from datetime import datetime
from pathlib import Path

_BACKEND = os.environ.get("DIGEST_DELIVERY", "local")


def deliver(markdown: str, stories: list[dict]) -> None:
    """Deliver the rendered digest and its stories."""
    if _BACKEND == "local":
        _deliver_local(markdown, stories)
        return
    if _BACKEND == "email":
        raise NotImplementedError("Email delivery is not implemented yet. Set DIGEST_DELIVERY=local.")
    if _BACKEND == "webhook":
        raise NotImplementedError("Webhook delivery is not implemented yet. Set DIGEST_DELIVERY=local.")
    raise NotImplementedError(f"Unknown DIGEST_DELIVERY backend '{_BACKEND}'.")


def _deliver_local(markdown: str, stories: list[dict]) -> None:
    print(markdown)

    out_dir = Path("digests")
    out_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    md_path = out_dir / f"{timestamp}.md"
    json_path = out_dir / f"{timestamp}.json"

    md_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json.dumps(stories, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n[saved] {md_path}")
    print(f"[saved] {json_path}")

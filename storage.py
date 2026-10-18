"""storage.py - sync the SQLite DB file to/from a remote backend.

Backend chosen by env DIGEST_STORAGE (local|s3|gcs). "local" is a no-op:
digest.db already lives where it needs to be, so there's nothing to sync.
"""
import os

_BACKEND = os.environ.get("DIGEST_STORAGE", "local")
_KNOWN_BACKENDS = {"local", "s3", "gcs"}


def _check_backend() -> None:
    if _BACKEND not in _KNOWN_BACKENDS:
        raise NotImplementedError(f"Unknown DIGEST_STORAGE backend '{_BACKEND}'.")


def sync_down() -> None:
    """Pull the latest DB file down. Call before init_db()."""
    _check_backend()
    if _BACKEND != "local":
        raise NotImplementedError(
            f"DIGEST_STORAGE={_BACKEND} sync_down is not implemented yet. Set DIGEST_STORAGE=local."
        )


def sync_up() -> None:
    """Push the DB file up. Call after a successful non-dry-run save."""
    _check_backend()
    if _BACKEND != "local":
        raise NotImplementedError(
            f"DIGEST_STORAGE={_BACKEND} sync_up is not implemented yet. Set DIGEST_STORAGE=local."
        )

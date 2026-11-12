"""storage.py - sync the SQLite DB file to/from a remote backend.

Backend chosen by env DIGEST_STORAGE (local|s3|gcs). "local" is a no-op:
digest.db already lives where it needs to be, so there's nothing to sync.

"gcs" downloads/uploads DIGEST_DB to a GCS object (DIGEST_GCS_BUCKET /
DIGEST_DB_OBJECT), using the object's generation as an optimistic-
concurrency precondition on upload - so two overlapping runs can't
silently clobber each other's save. Auth is Application Default
Credentials only; no key files.
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_KNOWN_BACKENDS = {"local", "s3", "gcs"}

# The generation of the GCS object as it was when sync_down() last read it
# (0 if it didn't exist yet). Remembered here so sync_up() can upload with
# if_generation_match - module-level state is fine since one process runs
# one digest at a time.
_state = {"generation": 0}


def _backend() -> str:
    """Read DIGEST_STORAGE fresh on every call, not once at import - so a
    value set after this module is imported (e.g. by a test, or a caller
    that sets it right before running) is still picked up."""
    return os.environ.get("DIGEST_STORAGE", "local")


def _check_backend(backend: str) -> None:
    if backend not in _KNOWN_BACKENDS:
        raise NotImplementedError(f"Unknown DIGEST_STORAGE backend '{backend}'.")


def _gcs_bucket_and_object() -> tuple[str, str]:
    bucket_name = os.environ.get("DIGEST_GCS_BUCKET")
    if not bucket_name:
        raise RuntimeError("DIGEST_STORAGE=gcs requires DIGEST_GCS_BUCKET to be set.")
    object_name = os.environ.get("DIGEST_DB_OBJECT", "digest.db")
    return bucket_name, object_name


def _gcs_blob():
    from google.cloud import storage  # imported lazily: local/s3 users don't need this installed

    bucket_name, object_name = _gcs_bucket_and_object()
    client = storage.Client()  # Application Default Credentials only
    return client.bucket(bucket_name).blob(object_name)


def sync_down() -> None:
    """Pull the latest DB file down. Call before init_db()."""
    backend = _backend()
    _check_backend(backend)
    if backend == "local":
        return
    if backend == "s3":
        raise NotImplementedError("DIGEST_STORAGE=s3 sync_down is not implemented yet. Set DIGEST_STORAGE=local.")

    from google.api_core.exceptions import NotFound

    import db  # local import: `db.DB_PATH` read live, not a stale copy taken at import time

    blob = _gcs_blob()
    try:
        blob.reload()
    except NotFound:
        _state["generation"] = 0
        print(f"[storage] no existing DB object at gs://{blob.bucket.name}/{blob.name} - starting fresh.")
        return

    _state["generation"] = blob.generation
    Path(db.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    blob.download_to_filename(str(db.DB_PATH))
    print(f"[storage] downloaded DB from gs://{blob.bucket.name}/{blob.name} (generation {blob.generation})")


def sync_up() -> None:
    """Push the DB file up. Call after a successful non-dry-run save."""
    backend = _backend()
    _check_backend(backend)
    if backend == "local":
        return
    if backend == "s3":
        raise NotImplementedError("DIGEST_STORAGE=s3 sync_up is not implemented yet. Set DIGEST_STORAGE=local.")

    from google.api_core.exceptions import FailedPrecondition

    import db

    blob = _gcs_blob()
    try:
        blob.upload_from_filename(str(db.DB_PATH), if_generation_match=_state["generation"])
    except FailedPrecondition:
        print(
            f"[error] gs://{blob.bucket.name}/{blob.name} changed since it was downloaded "
            f"(expected generation {_state['generation']}) - another run uploaded in the "
            f"meantime. Not overwriting; exiting without a second upload."
        )
        sys.exit(1)
    print(f"[storage] uploaded DB to gs://{blob.bucket.name}/{blob.name}")

    if os.environ.get("DIGEST_ARCHIVE", "").lower() == "true":
        _archive_digest_files(blob.bucket)


def _latest_digest_files(out_dir: Path) -> list[Path]:
    """The .md/.json/.html files from the most recently written run (they
    all share one timestamp stem - see delivery.py's _unique_stem)."""
    html_files = sorted(out_dir.glob("*.html"), key=lambda p: p.stat().st_mtime)
    if not html_files:
        return []
    stem = html_files[-1].stem
    return [out_dir / f"{stem}{ext}" for ext in (".md", ".json", ".html") if (out_dir / f"{stem}{ext}").exists()]


def _archive_digest_files(bucket) -> None:
    """DIGEST_ARCHIVE=true only: also upload this run's saved digest files
    to gs://<bucket>/digests/. Off by default."""
    out_dir = Path("digests")
    files = _latest_digest_files(out_dir)
    if not files:
        print("[storage] DIGEST_ARCHIVE=true but no digest files found under digests/ to archive.")
        return
    for path in files:
        blob = bucket.blob(f"digests/{path.name}")
        blob.upload_from_filename(str(path))
        print(f"[storage] archived {path.name} to gs://{bucket.name}/digests/{path.name}")

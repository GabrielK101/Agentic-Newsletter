import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

DB_PATH = Path(__file__).parent / "digest.db"

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

SCHEMA = """
CREATE TABLE IF NOT EXISTS stories (
    id        INTEGER PRIMARY KEY,
    told_on   TEXT NOT NULL,
    topic     TEXT NOT NULL,
    headline  TEXT NOT NULL,
    summary   TEXT NOT NULL,
    url       TEXT NOT NULL,
    url_norm  TEXT NOT NULL UNIQUE,
    update_of INTEGER REFERENCES stories(id)
);
CREATE INDEX IF NOT EXISTS idx_stories_told_on ON stories(told_on);
"""


def init_db() -> None:
    with closing(get_conn()) as conn:
        with conn:
            conn.executescript(SCHEMA)

_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid"}

def normalize_url(url: str) -> str:
    """Normalize a URL for deduplication. This is not perfect, but it should
    catch the most common cases of duplicate stories on different sites."""
    parts = urlsplit(url.strip())

    scheme = parts.scheme.lower()
    if scheme == "http":
        scheme = "https"
    host = parts.netloc.lower()

    # Drop tracking params, keep and sort the rest.
    kept = sorted(
        (k, v) for k, v in parse_qsl(parts.query)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
    )
    query = urlencode(kept)

    # Strip the trailing slash from the path, now that query/fragment are settled.
    path = parts.path
    if path.endswith("/") and path != "/":
        path = path[:-1]

    return urlunsplit((scheme, host, path, query, ""))  # fragment dropped

def save_story(topic: str, headline: str, summary: str, url: str, update_of: int | None = None, told_on: date | None = None) -> int | None:
    if told_on is None:
        told_on = date.today()

    with closing(get_conn()) as conn:
        if update_of is not None:
            row = conn.execute("SELECT 1 FROM stories WHERE id = ?", (update_of,)).fetchone()
            if row is None:
                update_of = None  # INSERT OR IGNORE doesn't cover foreign key errors

        with conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO stories (told_on, topic, headline, summary, url, url_norm, update_of) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (told_on.isoformat(), topic, headline, summary, url, normalize_url(url), update_of),
            )
        if cur.rowcount == 0:
            return None  # duplicate url_norm
        return cur.lastrowid

def recent_stories(days: int = 7) -> list[dict]:
    """Return stories from the last `days` days as plain dicts (json.dumps-ready)."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM stories WHERE told_on >= ? ORDER BY told_on DESC, id DESC",
            (cutoff,),
        ).fetchall()
    return [dict(row) for row in rows]

def seen_url(url: str) -> bool:
    """Check if a URL has already been seen in the database."""
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT 1 FROM stories WHERE url_norm = ?",
            (normalize_url(url),),
        ).fetchone()
    return row is not None


if __name__ == "__main__":
    import shutil
    import tempfile
    import json

    tmp_dir = tempfile.mkdtemp()
    DB_PATH = Path(tmp_dir) / "test_digest.db"

    try:
        init_db()
        init_db()  # must be able to run twice without error

        assert normalize_url("https://x.com/a/?utm_source=tw") == normalize_url("https://x.com/a")
        assert normalize_url("https://x.com/read?id=5") != normalize_url("https://x.com/read?id=6")
        assert normalize_url("http://X.com/a#top") == normalize_url("https://x.com/a")

        first_id = save_story("tech", "Headline", "Summary", "https://x.com/a")
        assert first_id is not None

        dup_id = save_story("tech", "Headline again", "Summary", "https://x.com/a/?utm_source=tw")
        assert dup_id is None

        bad_update_id = save_story("tech", "Follow-up", "Summary", "https://x.com/b", update_of=999999)
        assert bad_update_id is not None
        bad_row = next(r for r in recent_stories() if r["id"] == bad_update_id)
        assert bad_row["update_of"] is None

        json.dumps(recent_stories())

        print("all tests passed")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

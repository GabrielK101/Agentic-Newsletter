"""tests/test_db.py - unit tests for db.py. Points DB_PATH at a temporary
directory so the real digest.db is never touched.

Run with: python tests/test_db.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # project root, for `import db`

import json
import shutil
import tempfile

import db

tmp_dir = tempfile.mkdtemp()
db.DB_PATH = Path(tmp_dir) / "test_digest.db"

try:
    db.init_db()
    db.init_db()  # must be able to run twice without error

    assert db.normalize_url("https://x.com/a/?utm_source=tw") == db.normalize_url("https://x.com/a")
    assert db.normalize_url("https://x.com/read?id=5") != db.normalize_url("https://x.com/read?id=6")
    assert db.normalize_url("http://X.com/a#top") == db.normalize_url("https://x.com/a")

    first_id = db.save_story("tech", "Headline", "Summary", "https://x.com/a")
    assert first_id is not None

    dup_id = db.save_story("tech", "Headline again", "Summary", "https://x.com/a/?utm_source=tw")
    assert dup_id is None

    bad_update_id = db.save_story("tech", "Follow-up", "Summary", "https://x.com/b", update_of=999999)
    assert bad_update_id is not None
    bad_row = next(r for r in db.recent_stories() if r["id"] == bad_update_id)
    assert bad_row["update_of"] is None

    json.dumps(db.recent_stories())

    print("all tests passed")
finally:
    shutil.rmtree(tmp_dir, ignore_errors=True)

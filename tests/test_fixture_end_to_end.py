"""pytest test: `python digest.py --fixture --dry-run` runs end to end
with no network calls (no model, no tools, no market/sports data APIs),
producing the email HTML, the plain-text part (verifiable via
email_render directly), and the web edition HTML under digests/.
Run with: pytest tests/test_fixture_end_to_end.py -q
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_fixture_dry_run_produces_all_three_files(tmp_path):
    out_dir = ROOT / "digests"
    before = set(out_dir.glob("*")) if out_dir.exists() else set()

    env = dict(os.environ)
    env["DIGEST_DB"] = str(tmp_path / "fixture-test.db")
    env["DIGEST_STORAGE"] = "local"

    result = subprocess.run(
        [sys.executable, "digest.py", "--fixture", "--dry-run"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    after = set(out_dir.glob("*"))
    new_files = after - before
    suffixes = {p.suffix for p in new_files} | {"".join(p.suffixes[-2:]) for p in new_files}
    assert any(p.name.endswith(".md") for p in new_files)
    assert any(p.name.endswith(".json") for p in new_files)
    assert any(p.name.endswith(".web.html") for p in new_files)
    assert any(p.name.endswith(".html") and not p.name.endswith(".web.html") for p in new_files)

    for p in new_files:
        p.unlink()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))

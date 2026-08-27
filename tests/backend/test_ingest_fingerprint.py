"""Re-ingest must skip work that is already done.

"Rebuild Local Downloads" re-extracted and re-parsed every archive on every run.
On a 16 GB library that is minutes of decompression spent rediscovering rows
that are already in pak_assets. A fingerprint lets an unchanged download be
skipped, and the skip must be exact: stale rows are worse than slow ones.
"""
from __future__ import annotations

import os
import time

import pytest

from scripts.ingest_download_assets import compute_fingerprint


@pytest.fixture()
def archive(tmp_path):
    p = tmp_path / "mod.zip"
    p.write_bytes(b"pretend archive")
    return p


class TestComputeFingerprint:
    def test_is_stable_for_an_untouched_file(self, archive):
        assert compute_fingerprint(archive) == compute_fingerprint(archive)

    def test_changes_when_the_contents_change(self, archive):
        before = compute_fingerprint(archive)
        # Same length would leave size equal, so mtime is what must move.
        time.sleep(0.01)
        archive.write_bytes(b"different content")
        assert compute_fingerprint(archive) != before

    def test_changes_when_only_the_size_changes(self, archive):
        before = compute_fingerprint(archive)
        # Restore the original mtime so size is the only signal left.
        st = archive.stat()
        archive.write_bytes(b"pretend archive with more bytes")
        os.utime(archive, ns=(st.st_atime_ns, st.st_mtime_ns))
        assert compute_fingerprint(archive) != before

    def test_changes_when_only_the_mtime_changes(self, archive):
        before = compute_fingerprint(archive)
        st = archive.stat()
        os.utime(archive, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
        assert compute_fingerprint(archive) != before

    def test_missing_file_yields_none_so_it_is_always_re_ingested(self, tmp_path):
        assert compute_fingerprint(tmp_path / "nope.zip") is None

    def test_a_directory_still_produces_something_hashable(self, tmp_path):
        # Folder downloads are handled without a fingerprint, but the helper
        # must not raise if it is ever pointed at one.
        assert compute_fingerprint(tmp_path) is not None

    def test_two_different_files_do_not_collide(self, tmp_path):
        a = tmp_path / "a.zip"
        b = tmp_path / "b.zip"
        a.write_bytes(b"a" * 10)
        b.write_bytes(b"b" * 20)
        assert compute_fingerprint(a) != compute_fingerprint(b)


def test_migration_adds_the_fingerprint_column(tmp_path):
    """The skip is only possible if the column actually exists."""
    import sqlite3

    from core.db.db import init_schema, run_migrations

    db = tmp_path / "m.db"
    conn = sqlite3.connect(db)
    try:
        init_schema(conn)
        run_migrations(conn)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(local_downloads)")]
        assert "assets_fingerprint" in cols
    finally:
        conn.close()


def test_migration_is_idempotent(tmp_path):
    """Running migrations twice must not fail on the added column."""
    import sqlite3

    from core.db.db import init_schema, run_migrations

    db = tmp_path / "m.db"
    conn = sqlite3.connect(db)
    try:
        init_schema(conn)
        run_migrations(conn)
        run_migrations(conn)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(local_downloads)")]
        assert cols.count("assets_fingerprint") == 1
    finally:
        conn.close()

"""Storing the same image twice must not create two rows.

mod_custom_images had no uniqueness and five code paths inserted into it — two
upload endpoints, upload-by-URL, and two restore modals. Every backup restore
re-added every image, so a real install held 1352 rows of which 1050 were
byte-identical duplicates: each picture stored 4-8 times over.

Deduplicating in each caller is what let this drift, so the guard lives at the
single insert helper and is tested there.
"""
from __future__ import annotations

import sqlite3

import pytest

from core.api import server


@pytest.fixture()
def cur():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE mod_custom_images ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, mod_id INTEGER NOT NULL, "
        "image_data TEXT NOT NULL, filename TEXT, mime_type TEXT, "
        "sort_order INTEGER, content_hash TEXT)"
    )
    yield conn.cursor()
    conn.close()


def count(cur, mod_id: int) -> int:
    return cur.execute(
        "SELECT COUNT(*) FROM mod_custom_images WHERE mod_id = ?", (mod_id,)
    ).fetchone()[0]


class TestInsertIsIdempotent:
    def test_the_same_image_twice_stores_one_row(self, cur):
        assert server._insert_mod_image(cur, -1, "AAAA", "a.png", "image/png") is not None
        assert server._insert_mod_image(cur, -1, "AAAA", "a.png", "image/png") is None
        assert count(cur, -1) == 1

    def test_replaying_a_restore_does_not_multiply_the_library(self, cur):
        """The actual reported bug: restore re-adding everything, repeatedly."""
        images = [("a.png", "AAAA"), ("b.png", "BBBB"), ("c.png", "CCCC")]
        for _ in range(6):  # six restores
            for name, data in images:
                server._insert_mod_image(cur, -918, data, name, "image/png")
        assert count(cur, -918) == 3

    def test_a_different_image_with_the_same_filename_is_kept(self, cur):
        # Identity is the content, not the name: two different screenshots both
        # called "1.png" are both real images.
        server._insert_mod_image(cur, -1, "AAAA", "1.png", "image/png")
        server._insert_mod_image(cur, -1, "BBBB", "1.png", "image/png")
        assert count(cur, -1) == 2

    def test_the_same_image_on_two_mods_is_kept_for_both(self, cur):
        server._insert_mod_image(cur, -1, "AAAA", "a.png", "image/png")
        server._insert_mod_image(cur, -2, "AAAA", "a.png", "image/png")
        assert count(cur, -1) == 1 and count(cur, -2) == 1

    def test_empty_data_is_not_stored(self, cur):
        assert server._insert_mod_image(cur, -1, "", "a.png", "image/png") is None
        assert count(cur, -1) == 0

    def test_the_hash_is_recorded_so_later_inserts_can_match(self, cur):
        server._insert_mod_image(cur, -1, "AAAA", "a.png", "image/png")
        stored = cur.execute("SELECT content_hash FROM mod_custom_images").fetchone()[0]
        assert stored == server._image_content_hash("AAAA")

    def test_hash_is_stable_and_distinguishing(self):
        assert server._image_content_hash("AAAA") == server._image_content_hash("AAAA")
        assert server._image_content_hash("AAAA") != server._image_content_hash("AAAB")


def test_migration_adds_content_hash(tmp_path):
    from core.db.db import init_schema, run_migrations

    db = tmp_path / "m.db"
    conn = sqlite3.connect(db)
    try:
        init_schema(conn)
        run_migrations(conn)
        run_migrations(conn)  # idempotent
        cols = [r[1] for r in conn.execute("PRAGMA table_info(mod_custom_images)")]
        assert cols.count("content_hash") == 1
    finally:
        conn.close()

"""Linking a download to a Nexus mod must not lose what the user attached.

Everything a user adds to an unlinked download — images, tags — is stored
against the negated download id, because that is the synthetic key the app uses
before a real mod id exists. Assigning an id changes which key the app reads
from, so the rows stayed in the table while nothing looked for them: the Images
tab went empty at the exact moment the user was told the mod was now linked.

Indistinguishable from deletion, and reported as such.
"""
from __future__ import annotations

import sqlite3

import pytest

import core.api.server as server


@pytest.fixture()
def conn(tmp_path):
    from core.db.db import init_schema, run_migrations

    c = sqlite3.connect(str(tmp_path / "m.db"))
    init_schema(c)
    run_migrations(c)
    for mod_id in (-7, 4242):
        c.execute(
            "INSERT OR REPLACE INTO mods(mod_id, game, name) VALUES(?, 'marvelrivals', 'M')",
            (mod_id,),
        )
    c.commit()
    yield c
    c.close()


def _add_image(conn, mod_id, data, filename, preview=0, digest=None):
    conn.execute(
        "INSERT INTO mod_custom_images (mod_id, image_data, filename, mime_type, is_preview, content_hash) "
        "VALUES (?, ?, ?, 'image/png', ?, ?)",
        (mod_id, data, filename, preview, digest or f"hash-{data}"),
    )
    conn.commit()


def _images(conn, mod_id):
    return {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT filename, is_preview FROM mod_custom_images WHERE mod_id = ?", (mod_id,)
        ).fetchall()
    }


class TestImagesSurviveLinking:
    def test_they_move_to_the_new_mod_id(self, conn):
        _add_image(conn, -7, "AAA", "mine.png")
        _add_image(conn, -7, "BBB", "second.png")

        server._migrate_local_mod_data(conn.cursor(), -7, 4242)
        conn.commit()

        assert sorted(_images(conn, 4242)) == ["mine.png", "second.png"]
        assert _images(conn, -7) == {}

    def test_the_first_one_becomes_the_preview(self, conn):
        """A linked mod gains a Nexus picture, which outranks unstarred images.
        Without recording a choice, the artwork the user was looking at would be
        replaced by the site's."""
        _add_image(conn, -7, "AAA", "mine.png")
        server._migrate_local_mod_data(conn.cursor(), -7, 4242)
        conn.commit()
        assert _images(conn, 4242)["mine.png"] == 1

    def test_an_existing_choice_is_respected(self, conn):
        _add_image(conn, 4242, "CCC", "already-chosen.png", preview=1)
        _add_image(conn, -7, "AAA", "mine.png")

        server._migrate_local_mod_data(conn.cursor(), -7, 4242)
        conn.commit()

        after = _images(conn, 4242)
        assert after["already-chosen.png"] == 1
        assert after["mine.png"] == 0

    def test_a_duplicate_is_dropped_not_doubled(self, conn):
        """The same picture may already be there from a Nexus sync."""
        _add_image(conn, 4242, "AAA", "from-nexus.png", digest="same")
        _add_image(conn, -7, "AAA", "mine.png", digest="same")

        server._migrate_local_mod_data(conn.cursor(), -7, 4242)
        conn.commit()

        assert list(_images(conn, 4242)) == ["from-nexus.png"]
        assert _images(conn, -7) == {}

    def test_it_works_before_the_target_mod_row_exists(self, tmp_path):
        """The failure that kept the images disappearing.

        mod_custom_images.mod_id is a foreign key onto mods, and the Nexus sync
        that creates that row runs *after* the link. Moving the images first
        raised "FOREIGN KEY constraint failed", which a broad except turned into
        a silent no-op — the pictures stayed under the old key and the log said
        nothing.
        """
        from core.db.db import init_schema, run_migrations

        c = sqlite3.connect(str(tmp_path / "fresh.db"))
        try:
            init_schema(c)
            run_migrations(c)
            c.execute("INSERT OR REPLACE INTO mods(mod_id, game, name) VALUES(-920,'g','local')")
            c.execute(
                "INSERT INTO mod_custom_images (mod_id, image_data, filename, mime_type, content_hash) "
                "VALUES (-920, 'AAA', 'mine.png', 'image/png', 'h1')"
            )
            c.commit()
            assert c.execute("SELECT 1 FROM mods WHERE mod_id = 5104").fetchone() is None

            moved = server._migrate_local_mod_data(c.cursor(), -920, 5104)
            c.commit()

            assert moved["images"] == 1
            assert (
                c.execute(
                    "SELECT mod_id FROM mod_custom_images WHERE filename = 'mine.png'"
                ).fetchone()[0]
                == 5104
            )
        finally:
            c.close()

    def test_a_mod_with_nothing_attached_is_a_no_op(self, conn):
        result = server._migrate_local_mod_data(conn.cursor(), -7, 4242)
        assert result == {"images": 0, "tags": 0}

    def test_migrating_onto_itself_changes_nothing(self, conn):
        _add_image(conn, 4242, "AAA", "mine.png")
        result = server._migrate_local_mod_data(conn.cursor(), 4242, 4242)
        assert result == {"images": 0, "tags": 0}
        assert list(_images(conn, 4242)) == ["mine.png"]


class TestMigrationRecoversAlreadyStrandedImages:
    """Assignment carries images across now, but a real library already had 31
    of them stranded from before the fix. Migration 0030 reunites those."""

    @staticmethod
    def _fresh(tmp_path):
        from core.db.db import init_schema, run_migrations

        c = sqlite3.connect(str(tmp_path / "old.db"))
        init_schema(c)
        run_migrations(c)
        return c

    def test_images_move_to_the_linked_mod(self, tmp_path):
        from core.db.db import run_migrations

        c = self._fresh(tmp_path)
        try:
            # The app creates a placeholder mods row for the synthetic negative
            # id; mod_custom_images has a foreign key onto it.
            c.execute("INSERT OR REPLACE INTO mods(mod_id, game, name) VALUES(500,'g','M')")
            c.execute("INSERT OR REPLACE INTO mods(mod_id, game, name) VALUES(-9,'g','local')")
            c.execute(
                "INSERT INTO local_downloads(path, id, name, mod_id, contents, active_paks) "
                "VALUES('a.zip', 9, 'A', 500, '[]', '[]')"
            )
            c.execute(
                "INSERT INTO mod_custom_images (mod_id, image_data, filename, mime_type, content_hash) "
                "VALUES (-9, 'AAA', 'mine.png', 'image/png', 'h1')"
            )
            c.commit()

            run_migrations(c)  # 0030 already applied above; force the statements
            c.executescript(
                (
                    __import__("pathlib").Path("core/db/migrations/0030_recover_orphaned_mod_images.sql")
                ).read_text(encoding="utf-8")
            )
            c.commit()

            owner = c.execute(
                "SELECT mod_id FROM mod_custom_images WHERE filename = 'mine.png'"
            ).fetchone()[0]
        finally:
            c.close()
        assert owner == 500

    def test_an_unlinked_download_is_left_alone(self, tmp_path):
        c = self._fresh(tmp_path)
        try:
            c.execute("INSERT OR REPLACE INTO mods(mod_id, game, name) VALUES(-8,'g','local')")
            c.execute(
                "INSERT INTO local_downloads(path, id, name, mod_id, contents, active_paks) "
                "VALUES('b.zip', 8, 'B', NULL, '[]', '[]')"
            )
            c.execute(
                "INSERT INTO mod_custom_images (mod_id, image_data, filename, mime_type, content_hash) "
                "VALUES (-8, 'BBB', 'still-local.png', 'image/png', 'h2')"
            )
            c.commit()
            c.executescript(
                (
                    __import__("pathlib").Path("core/db/migrations/0030_recover_orphaned_mod_images.sql")
                ).read_text(encoding="utf-8")
            )
            c.commit()
            owner = c.execute(
                "SELECT mod_id FROM mod_custom_images WHERE filename = 'still-local.png'"
            ).fetchone()[0]
        finally:
            c.close()
        assert owner == -8, "a download with no Nexus id has nowhere to move to"


class TestTagsSurviveLinking:
    def _tags(self, conn, mod_id):
        return sorted(
            r[0]
            for r in conn.execute(
                "SELECT tag FROM mod_custom_tags WHERE mod_id = ?", (mod_id,)
            ).fetchall()
        )

    def test_they_move_across(self, conn):
        for tag in ("jubilee", "favourite"):
            conn.execute(
                "INSERT INTO mod_custom_tags (mod_id, tag, added_at) VALUES (-7, ?, '')",
                (tag,),
            )
        conn.commit()

        server._migrate_local_mod_data(conn.cursor(), -7, 4242)
        conn.commit()

        assert self._tags(conn, 4242) == ["favourite", "jubilee"]
        assert self._tags(conn, -7) == []

    def test_a_tag_the_target_already_has_is_not_duplicated(self, conn):
        conn.execute("INSERT INTO mod_custom_tags (mod_id, tag, added_at) VALUES (4242, 'jubilee', '')")
        conn.execute("INSERT INTO mod_custom_tags (mod_id, tag, added_at) VALUES (-7, 'Jubilee', '')")
        conn.commit()

        server._migrate_local_mod_data(conn.cursor(), -7, 4242)
        conn.commit()

        assert self._tags(conn, 4242) == ["jubilee"]
        assert self._tags(conn, -7) == []

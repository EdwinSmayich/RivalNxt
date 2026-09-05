"""A mod's Nexus picture must be removable from its gallery.

The images tab mixes two sources: mods.picture_url, which Nexus owns and which
sat first in the list, and mod_custom_images, which the user owns. Only the
second had a delete button, so on any mod installed from the site the Nexus
picture was permanent — you could star your own screenshot but never be rid of
theirs.

The flag deliberately lives in its own table. `mods` is upserted wholesale by
the metadata sync, so a column there would be silently undone by the next
refresh.
"""
from __future__ import annotations

import sqlite3

import pytest

import core.api.server as server
from core.api.dependencies import invalidate_connection_pool


@pytest.fixture()
def db(monkeypatch, tmp_path):
    from core.db.db import init_schema, run_migrations

    invalidate_connection_pool()
    db_path = tmp_path / "mods.db"
    conn = sqlite3.connect(str(db_path))
    init_schema(conn)
    run_migrations(conn)
    conn.execute(
        "INSERT OR REPLACE INTO mods(mod_id, game, name, picture_url) "
        "VALUES(7956, 'marvelrivals', 'Maskless Malice', 'https://static/7956.png')"
    )
    conn.commit()
    conn.close()

    import core.config.settings as settings_mod

    monkeypatch.setattr(
        settings_mod,
        "SETTINGS",
        settings_mod.replace(settings_mod.SETTINGS, data_dir=tmp_path),
    )
    yield db_path
    invalidate_connection_pool()


def _add_custom(db_path, mod_id=7956, data="AAAA", preview=0):
    conn = sqlite3.connect(str(db_path))
    cur = conn.execute(
        "INSERT INTO mod_custom_images (mod_id, image_data, filename, mime_type, is_preview) "
        "VALUES (?, ?, 'mine.png', 'image/png', ?)",
        (mod_id, data, preview),
    )
    conn.commit()
    image_id = cur.lastrowid
    conn.close()
    return image_id


class TestHidingTheNexusPicture:
    def test_it_is_listed_by_default(self, db):
        result = server.get_mod_images(7956)
        assert [i["url"] for i in result["nexus_images"]] == ["https://static/7956.png"]
        assert result["nexus_image_hidden"] is False

    def test_hiding_removes_it_from_the_gallery(self, db):
        server.hide_nexus_image(7956)
        result = server.get_mod_images(7956)
        assert result["nexus_images"] == []
        assert result["nexus_image_hidden"] is True

    def test_showing_puts_it_back(self, db):
        server.hide_nexus_image(7956)
        server.show_nexus_image(7956)
        result = server.get_mod_images(7956)
        assert len(result["nexus_images"]) == 1
        assert result["nexus_image_hidden"] is False

    def test_hiding_twice_is_harmless(self, db):
        server.hide_nexus_image(7956)
        server.hide_nexus_image(7956)
        assert server.get_mod_images(7956)["nexus_images"] == []

    def test_showing_something_never_hidden_is_harmless(self, db):
        server.show_nexus_image(7956)
        assert len(server.get_mod_images(7956)["nexus_images"]) == 1

    def test_the_upstream_url_is_not_destroyed(self, db):
        """Hiding is a display choice, not a deletion — Nexus data stays intact."""
        server.hide_nexus_image(7956)
        conn = sqlite3.connect(str(db))
        try:
            url = conn.execute(
                "SELECT picture_url FROM mods WHERE mod_id = 7956"
            ).fetchone()[0]
        finally:
            conn.close()
        assert url == "https://static/7956.png"

    def test_a_metadata_resync_does_not_bring_it_back(self, db):
        """The whole reason the flag is not a column on `mods`."""
        server.hide_nexus_image(7956)
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT OR REPLACE INTO mods(mod_id, game, name, picture_url) "
            "VALUES(7956, 'marvelrivals', 'Maskless Malice', 'https://static/new.png')"
        )
        conn.commit()
        conn.close()
        assert server.get_mod_images(7956)["nexus_images"] == []

    def test_custom_images_are_unaffected(self, db):
        _add_custom(db)
        server.hide_nexus_image(7956)
        result = server.get_mod_images(7956)
        assert len(result["custom_images"]) == 1


class TestTheCardAgrees:
    """Hiding must also change what the mod card shows.

    The card prefers the Nexus picture unless the user made an explicit choice.
    Removing the Nexus picture is exactly such a choice, so without this the card
    would keep displaying the image the user had just deleted from the gallery.
    """

    def test_hiding_promotes_the_custom_image_on_the_card(self, db):
        _add_custom(db)
        before = server.get_custom_images_preview(mod_ids="7956")
        assert before["explicit"] == []

        server.hide_nexus_image(7956)
        after = server.get_custom_images_preview(mod_ids="7956")
        assert after["explicit"] == ["7956"]

    def test_a_starred_image_is_still_explicit(self, db):
        image_id = _add_custom(db, preview=1)
        assert image_id
        result = server.get_custom_images_preview(mod_ids="7956")
        assert result["explicit"] == ["7956"]

    def test_hiding_with_no_custom_images_reports_nothing(self, db):
        server.hide_nexus_image(7956)
        result = server.get_custom_images_preview(mod_ids="7956")
        # Nothing to promote; the card falls back to its own placeholder rather
        # than being handed an image that does not exist.
        assert result["images"] == {}
        assert result["explicit"] == []


class TestStarringTheNexusPicture:
    """The star was custom-only, so on a downloaded mod the image the app was
    actually showing had no star — and once you starred your own screenshot
    there was no way back to the original. The Nexus picture has no row to flag,
    so choosing it means clearing whichever custom image was starred: with
    nothing starred, picture_url is what everything already falls back to.
    """

    def test_it_is_starred_when_nothing_custom_is(self, db):
        result = server.get_mod_images(7956)
        assert result["nexus_images"][0]["isPreview"] is True

    def test_starring_a_custom_image_unstars_it(self, db):
        image_id = _add_custom(db)
        server.set_mod_image_preview(7956, image_id)
        result = server.get_mod_images(7956)
        assert result["nexus_images"][0]["isPreview"] is False
        assert result["custom_images"][0]["isPreview"] is True

    def test_starring_it_back_clears_the_custom_choice(self, db):
        image_id = _add_custom(db)
        server.set_mod_image_preview(7956, image_id)
        server.set_mod_image_preview(7956, 0)
        result = server.get_mod_images(7956)
        assert result["nexus_images"][0]["isPreview"] is True
        assert result["custom_images"][0]["isPreview"] is False

    def test_starring_it_also_brings_it_back_into_view(self, db):
        """Starring an image you cannot see would do nothing at all."""
        _add_custom(db)
        server.hide_nexus_image(7956)
        server.set_mod_image_preview(7956, 0)
        result = server.get_mod_images(7956)
        assert len(result["nexus_images"]) == 1
        assert result["nexus_image_hidden"] is False

    def test_the_card_stops_preferring_the_custom_image(self, db):
        image_id = _add_custom(db)
        server.set_mod_image_preview(7956, image_id)
        assert server.get_custom_images_preview(mod_ids="7956")["explicit"] == ["7956"]

        server.set_mod_image_preview(7956, 0)
        assert server.get_custom_images_preview(mod_ids="7956")["explicit"] == []

    def test_a_mod_with_no_picture_cannot_have_it_starred(self, db):
        from fastapi import HTTPException

        conn = sqlite3.connect(str(db))
        conn.execute("UPDATE mods SET picture_url = NULL WHERE mod_id = 7956")
        conn.commit()
        conn.close()
        with pytest.raises(HTTPException) as exc:
            server.set_mod_image_preview(7956, 0)
        assert exc.value.status_code == 404

    def test_starring_a_custom_image_of_another_mod_is_still_rejected(self, db):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            server.set_mod_image_preview(7956, 9999)
        assert exc.value.status_code == 404


def test_endpoints_are_registered():
    paths = {getattr(r, "path", None) for r in server.app.routes}
    assert "/api/mods/{mod_id}/images/nexus/hide" in paths
    assert "/api/mods/{mod_id}/images/nexus/show" in paths


def test_migration_creates_the_table(tmp_path):
    from core.db.db import init_schema, run_migrations

    db = tmp_path / "m.db"
    conn = sqlite3.connect(db)
    try:
        init_schema(conn)
        run_migrations(conn)
        run_migrations(conn)  # idempotent
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "mod_hidden_nexus_image" in tables
    finally:
        conn.close()

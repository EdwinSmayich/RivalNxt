"""Mod archives are the only reliable source of a mod's other preview images.

Nexus publishes exactly one picture per mod and its GraphQL API exposes no
gallery — verified against the live schema, where Mod has no images/media/
screenshots/gallery field and the root media query cannot be narrowed to a mod.
Scraping the website would break silently whenever their markup changed.

Archives are local and cannot change underneath us. Measured over a real
library: 55 of 123 zips ship loose images next to the .pak files, median 9 per
archive, and the filenames track the pak variants. They are also full
resolution — median 6MB, largest seen 27MB — so importing them untouched is
exactly how this project previously ended up with a 2.2GB database and a backup
that could not be serialised.
"""
from __future__ import annotations

import base64
import io
import sqlite3
import zipfile

import pytest

import core.api.server as server
from core.api.dependencies import invalidate_connection_pool

PIL = pytest.importorskip("PIL.Image")


def _png(width: int, height: int) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    # Noise-free but non-uniform, so JPEG encoding has something to do.
    img = Image.new("RGB", (width, height), (200, 40, 90))
    for x in range(0, width, 16):
        for y in range(0, height, 16):
            img.putpixel((x, y), (10, 200, 10))
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def env(monkeypatch, tmp_path):
    from core.db.db import init_schema, run_migrations

    invalidate_connection_pool()
    downloads = tmp_path / "downloads"
    downloads.mkdir()

    archive = downloads / "Maskless Malice.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("Maskless Malice/1.png", _png(1063, 1329))
        zf.writestr("Maskless Malice/Malice1.png", _png(1441, 977))
        zf.writestr("Maskless Malice/notes.txt", "read me")
        zf.writestr("Maskless Malice/A_Skin_9999999_P.pak", b"\x00" * 64)

    db_path = tmp_path / "mods.db"
    conn = sqlite3.connect(str(db_path))
    init_schema(conn)
    run_migrations(conn)
    conn.execute(
        "INSERT INTO local_downloads(path, id, name, mod_id, contents, active_paks) "
        "VALUES(?, 1, 'Maskless Malice', 7956, '[]', '[]')",
        (str(archive),),
    )
    conn.execute(
        "INSERT OR REPLACE INTO mods(mod_id, game, name) VALUES(7956, 'marvelrivals', 'Ace')"
    )
    # An unlinked drop: no mod_id at all.
    plain = downloads / "HandMade.zip"
    with zipfile.ZipFile(plain, "w") as zf:
        zf.writestr("shot.png", _png(900, 600))
    conn.execute(
        "INSERT INTO local_downloads(path, id, name, mod_id, contents, active_paks) "
        "VALUES(?, 2, 'HandMade', NULL, '[]', '[]')",
        (str(plain),),
    )
    conn.commit()
    conn.close()

    import core.config.settings as settings_mod

    monkeypatch.setattr(
        settings_mod,
        "SETTINGS",
        settings_mod.replace(
            settings_mod.SETTINGS,
            data_dir=tmp_path,
            marvel_rivals_local_downloads_root=downloads,
        ),
    )
    yield {"db": db_path, "downloads": downloads, "archive": archive}
    invalidate_connection_pool()


class TestListing:
    def test_it_finds_the_images_and_ignores_everything_else(self, env):
        result = server.list_archive_images(1)
        names = sorted(i["name"] for i in result["images"])
        assert names == ["1.png", "Malice1.png"], names

    def test_each_entry_carries_a_thumbnail_and_the_real_dimensions(self, env):
        image = next(
            i for i in server.list_archive_images(1)["images"] if i["name"] == "1.png"
        )
        assert image["width"] == 1063 and image["height"] == 1329
        assert image["thumbnail"].startswith("data:image/jpeg;base64,")

    def test_the_thumbnail_is_small(self, env):
        """It ships every candidate at once; full-size would be tens of MB."""
        image = server.list_archive_images(1)["images"][0]
        raw = base64.b64decode(image["thumbnail"].split(",", 1)[1])
        from PIL import Image

        assert max(Image.open(io.BytesIO(raw)).size) <= server._ARCHIVE_THUMB_SIZE

    def test_listing_stores_nothing(self, env):
        server.list_archive_images(1)
        conn = sqlite3.connect(str(env["db"]))
        try:
            count = conn.execute("SELECT COUNT(*) FROM mod_custom_images").fetchone()[0]
        finally:
            conn.close()
        assert count == 0

    def test_a_missing_file_is_a_404_not_a_crash(self, env):
        from fastapi import HTTPException

        env["archive"].unlink()
        with pytest.raises(HTTPException) as exc:
            server.list_archive_images(1)
        assert exc.value.status_code == 404

    def test_an_unknown_download_is_a_404(self, env):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            server.list_archive_images(999)
        assert exc.value.status_code == 404


class TestImporting:
    def test_it_stores_the_chosen_images(self, env):
        entries = [i["entry"] for i in server.list_archive_images(1)["images"]]
        result = server.import_archive_images(
            1, server.ArchiveImageImportPayload(entries=entries[:1])
        )
        assert result["imported"] == 1
        conn = sqlite3.connect(str(env["db"]))
        try:
            rows = conn.execute(
                "SELECT mod_id, filename, mime_type FROM mod_custom_images"
            ).fetchall()
        finally:
            conn.close()
        assert len(rows) == 1
        assert rows[0][0] == 7956
        assert rows[0][2] == "image/jpeg"

    def test_stored_images_are_downscaled(self, env, tmp_path):
        """The 2.2GB-database lesson: never store the archive's originals.

        Checked on dimensions, not bytes. Real mod screenshots are photographic
        and shrink by an order of magnitude, but a synthetic test image is flat
        colour, where PNG beats JPEG and a byte comparison would fail for a
        reason that has nothing to do with the behaviour under test.
        """
        oversized = env["downloads"] / "Huge.zip"
        with zipfile.ZipFile(oversized, "w") as zf:
            zf.writestr("huge.png", _png(4608, 2048))
        conn = sqlite3.connect(str(env["db"]))
        conn.execute(
            "INSERT INTO local_downloads(path, id, name, mod_id, contents, active_paks) "
            "VALUES(?, 3, 'Huge', 7956, '[]', '[]')",
            (str(oversized),),
        )
        conn.commit()
        conn.close()

        entry = server.list_archive_images(3)["images"][0]["entry"]
        server.import_archive_images(3, server.ArchiveImageImportPayload(entries=[entry]))

        conn = sqlite3.connect(str(env["db"]))
        try:
            data = conn.execute("SELECT image_data FROM mod_custom_images").fetchone()[0]
        finally:
            conn.close()
        from PIL import Image

        stored = Image.open(io.BytesIO(base64.b64decode(data)))
        assert max(stored.size) <= server._ARCHIVE_IMPORT_SIZE
        assert stored.size[0] < 4608, "a 4608px source must not be stored at full width"

    def test_importing_twice_adds_nothing(self, env):
        entry = server.list_archive_images(1)["images"][0]["entry"]
        first = server.import_archive_images(
            1, server.ArchiveImageImportPayload(entries=[entry])
        )
        second = server.import_archive_images(
            1, server.ArchiveImageImportPayload(entries=[entry])
        )
        assert first["imported"] == 1
        assert second["imported"] == 0 and second["duplicates"] == 1

    def test_an_unlinked_download_gets_the_negative_id_convention(self, env):
        """Hand-made .pak drops have no Nexus id; the rest of the app keys them
        by the negated download id, and this must not invent a second scheme."""
        entry = server.list_archive_images(2)["images"][0]["entry"]
        result = server.import_archive_images(
            2, server.ArchiveImageImportPayload(entries=[entry])
        )
        assert result["mod_id"] == -2
        assert result["imported"] == 1

    def test_an_entry_that_is_not_in_the_archive_is_counted_not_fatal(self, env):
        result = server.import_archive_images(
            1, server.ArchiveImageImportPayload(entries=["nope/missing.png"])
        )
        assert result["imported"] == 0 and result["failed"] == 1

    def test_selecting_nothing_is_rejected(self, env):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            server.import_archive_images(1, server.ArchiveImageImportPayload(entries=[]))
        assert exc.value.status_code == 400

    def test_imported_images_show_up_in_the_gallery(self, env):
        entries = [i["entry"] for i in server.list_archive_images(1)["images"]]
        server.import_archive_images(1, server.ArchiveImageImportPayload(entries=entries))
        gallery = server.get_mod_images(7956)
        assert len(gallery["custom_images"]) == 2


def test_endpoints_are_registered():
    paths = {getattr(r, "path", None) for r in server.app.routes}
    assert "/api/local_downloads/{download_id}/archive-images" in paths
    assert "/api/local_downloads/{download_id}/archive-images/import" in paths

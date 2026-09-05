"""Deleting a pak out of the mod's archive for good.

The destructive counterpart to hiding. Hiding is a view filter and is undone by
one click; this rewrites the .zip on disk, so nothing can bring the file back —
which is exactly why the UI asks first, and why these tests care most about what
happens when it goes wrong.

The archive is rebuilt beside the original and swapped in only once complete, so
a failure part-way must leave the original intact rather than half-written.
"""
from __future__ import annotations

import json
import sqlite3
import zipfile

import pytest

import core.api.server as server
from core.api.dependencies import invalidate_connection_pool

PAK = "LunaSnow_AbyssalGlow_Symbiote_9999999_P"
OTHER = "A_OtherVariant_9999999_P"


@pytest.fixture()
def env(monkeypatch, tmp_path):
    from core.db.db import init_schema, run_migrations

    invalidate_connection_pool()
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    archive = downloads / "mod.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        # A pak ships as up to three files sharing one stem.
        for ext in (".pak", ".utoc", ".ucas"):
            zf.writestr(f"{PAK}{ext}", b"\x00" * 32)
        zf.writestr(f"{OTHER}.pak", b"\x01" * 32)
        zf.writestr("readme.txt", "hello")

    db_path = tmp_path / "mods.db"
    conn = sqlite3.connect(str(db_path))
    init_schema(conn)
    run_migrations(conn)
    conn.execute(
        "INSERT INTO local_downloads(path, id, name, mod_id, contents, active_paks) "
        "VALUES(?, 1, 'Midnight', NULL, ?, '[]')",
        (str(archive), json.dumps([f"{PAK}.pak", f"{OTHER}.pak"])),
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
    yield {"db": db_path, "archive": archive}
    invalidate_connection_pool()


def _members(archive):
    with zipfile.ZipFile(archive) as zf:
        return sorted(zf.namelist())


def _contents(db):
    conn = sqlite3.connect(str(db))
    try:
        raw = conn.execute("SELECT contents FROM local_downloads WHERE id=1").fetchone()[0]
    finally:
        conn.close()
    return json.loads(raw)


class TestDeletingFromTheArchive:
    def test_the_whole_pak_bundle_goes_not_just_the_pak(self, env):
        """.pak/.utoc/.ucas are one pak; leaving two behind orphans them."""
        result = server.delete_download_file(
            1, server.RemoveDownloadFilePayload(pak_name=f"{PAK}.pak")
        )
        assert result["members_removed"] == 3
        assert _members(env["archive"]) == [f"{OTHER}.pak", "readme.txt"]

    def test_everything_else_survives(self, env):
        server.delete_download_file(
            1, server.RemoveDownloadFilePayload(pak_name=f"{PAK}.pak")
        )
        with zipfile.ZipFile(env["archive"]) as zf:
            assert zf.read("readme.txt") == b"hello"
            assert zf.read(f"{OTHER}.pak") == b"\x01" * 32

    def test_the_database_stops_listing_it(self, env):
        server.delete_download_file(
            1, server.RemoveDownloadFilePayload(pak_name=f"{PAK}.pak")
        )
        assert _contents(env["db"]) == [f"{OTHER}.pak"]

    def test_a_rebuild_cannot_bring_it_back(self, env):
        """The difference from hiding: the bytes are gone from the archive."""
        server.delete_download_file(
            1, server.RemoveDownloadFilePayload(pak_name=f"{PAK}.pak")
        )
        with zipfile.ZipFile(env["archive"]) as zf:
            assert not any(n.startswith(PAK) for n in zf.namelist())

    def test_deleting_clears_any_hidden_record_for_it(self, env):
        """A file that no longer exists cannot be 'hidden'."""
        conn = sqlite3.connect(str(env["db"]))
        conn.execute(
            "INSERT INTO mod_hidden_files (download_id, pak_name, hidden_at) "
            "VALUES (1, ?, '2026-01-01T00:00:00+00:00')",
            (f"{PAK}.pak",),
        )
        conn.commit()
        conn.close()

        server.delete_download_file(
            1, server.RemoveDownloadFilePayload(pak_name=f"{PAK}.pak")
        )
        assert server.get_local_download(1)["hidden_contents"] == []

    def test_it_is_recorded_in_the_history(self, env):
        server.delete_download_file(
            1, server.RemoveDownloadFilePayload(pak_name=f"{PAK}.pak")
        )
        entry = server.list_activity()["entries"][0]
        assert entry["kind"] == "file_deleted"
        assert "not recoverable" in (entry["detail"] or "")


class TestItRefusesRatherThanRisksTheArchive:
    def test_an_unknown_file_changes_nothing(self, env):
        from fastapi import HTTPException

        before = _members(env["archive"])
        with pytest.raises(HTTPException) as exc:
            server.delete_download_file(
                1, server.RemoveDownloadFilePayload(pak_name="not_here.pak")
            )
        assert exc.value.status_code == 404
        assert _members(env["archive"]) == before

    def test_a_blank_name_is_rejected(self, env):
        from fastapi import HTTPException

        before = _members(env["archive"])
        with pytest.raises(HTTPException) as exc:
            server.delete_download_file(
                1, server.RemoveDownloadFilePayload(pak_name="   ")
            )
        assert exc.value.status_code == 400
        assert _members(env["archive"]) == before

    def test_a_rar_is_refused_rather_than_guessed_at(self, env, monkeypatch, tmp_path):
        """rar/7z editing needs an external tool; not on someone's only copy."""
        from fastapi import HTTPException

        rar = tmp_path / "downloads" / "mod.rar"
        rar.write_bytes(b"Rar!\x1a\x07\x00")
        conn = sqlite3.connect(str(env["db"]))
        conn.execute("UPDATE local_downloads SET path = ? WHERE id = 1", (str(rar),))
        conn.commit()
        conn.close()

        with pytest.raises(HTTPException) as exc:
            server.delete_download_file(
                1, server.RemoveDownloadFilePayload(pak_name=f"{PAK}.pak")
            )
        assert exc.value.status_code == 400
        assert ".rar" in exc.value.detail

    def test_a_failed_rewrite_leaves_the_original_intact(self, env, monkeypatch):
        """The reason it builds beside the file instead of editing in place."""
        from fastapi import HTTPException

        before = _members(env["archive"])
        before_bytes = env["archive"].read_bytes()

        def explode(*_a, **_k):
            raise OSError("disk full")

        monkeypatch.setattr(server, "_rewrite_zip_without", explode)
        with pytest.raises(HTTPException) as exc:
            server.delete_download_file(
                1, server.RemoveDownloadFilePayload(pak_name=f"{PAK}.pak")
            )
        assert exc.value.status_code == 500
        assert _members(env["archive"]) == before
        assert env["archive"].read_bytes() == before_bytes
        assert not (env["archive"].parent / "mod.zip.rebuilding").exists()

    def test_a_missing_archive_is_a_404(self, env):
        from fastapi import HTTPException

        env["archive"].unlink()
        with pytest.raises(HTTPException) as exc:
            server.delete_download_file(
                1, server.RemoveDownloadFilePayload(pak_name=f"{PAK}.pak")
            )
        assert exc.value.status_code == 404


def test_endpoint_is_registered():
    paths = {getattr(r, "path", None) for r in server.app.routes}
    assert "/api/local_downloads/{download_id}/delete-file" in paths

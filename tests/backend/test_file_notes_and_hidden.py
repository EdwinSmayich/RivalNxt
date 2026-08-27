"""Per-pak notes, and removals that survive a rebuild.

Removing a pak edited local_downloads.contents. "Initial Database Build"
re-reads every archive and rewrites that column from scratch, so every removal
came back and there was no record that one had ever happened — nothing to undo,
nothing to ask about. The removal now lives in its own table that the rebuild
does not touch.

Notes exist because a mod routinely ships a dozen variants called A_rogueVA /
A_rogueVB / A_rogueVC, and nothing in the app said what any of them changed.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

import core.api.server as server
from core.api.dependencies import invalidate_connection_pool


@pytest.fixture()
def env(monkeypatch, tmp_path):
    from core.db.db import init_schema, run_migrations

    invalidate_connection_pool()
    db_path = tmp_path / "mods.db"
    conn = sqlite3.connect(str(db_path))
    init_schema(conn)
    run_migrations(conn)
    conn.execute(
        "INSERT INTO local_downloads(path, id, name, mod_id, contents, active_paks) "
        "VALUES('Rogue.zip', 1, 'Rogue', NULL, ?, '[]')",
        (json.dumps(["A_rogueVA_P.pak", "A_rogueVB_P.pak", "A_rogueVC_P.pak"]),),
    )
    conn.commit()
    conn.close()

    import core.config.settings as settings_mod

    monkeypatch.setattr(
        settings_mod,
        "SETTINGS",
        settings_mod.replace(settings_mod.SETTINGS, data_dir=tmp_path),
    )
    yield {"db": db_path}
    invalidate_connection_pool()


def _mark_hidden(db_path, pak_name, download_id=1):
    """Record a removal without going through the endpoint.

    remove_download_file deactivates the pak first, which needs a configured
    game folder and the real archive on disk. Those belong to
    test_remove_download_file.py; what is under test here is the read-side
    filter, so the record is written directly.
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR REPLACE INTO mod_hidden_files (download_id, pak_name, hidden_at) "
        "VALUES (?, ?, '2026-01-01T00:00:00+00:00')",
        (download_id, pak_name),
    )
    conn.commit()
    conn.close()


def _contents(db_path, download_id=1):
    conn = sqlite3.connect(str(db_path))
    try:
        raw = conn.execute(
            "SELECT contents FROM local_downloads WHERE id = ?", (download_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    return json.loads(raw)


def _rebuild_rewrites_contents(db_path, download_id=1):
    """What ingest_download_assets does: contents comes back from the archive."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE local_downloads SET contents = ? WHERE id = ?",
        (json.dumps(["A_rogueVA_P.pak", "A_rogueVB_P.pak", "A_rogueVC_P.pak"]), download_id),
    )
    conn.commit()
    conn.close()


class TestRemovalsSurviveARebuild:
    def test_removing_a_pak_records_it(self, env):
        server.remove_download_file(
            1, server.RemoveDownloadFilePayload(pak_name="A_rogueVB_P.pak")
        )
        hidden = server.list_hidden_files()
        assert hidden["count"] == 1
        assert hidden["files"][0]["pak_name"] == "A_rogueVB_P.pak"
        assert hidden["files"][0]["mod_name"] == "Rogue"

    def test_a_rebuild_puts_the_row_back_but_it_stays_out_of_the_list(self, env):
        server.remove_download_file(
            1, server.RemoveDownloadFilePayload(pak_name="A_rogueVB_P.pak")
        )
        _rebuild_rewrites_contents(env["db"])

        # The column really does have it again...
        assert "A_rogueVB_P.pak" in _contents(env["db"])
        # ...and the user still does not see it.
        listed = next(d for d in server.list_downloads() if d["id"] == 1)
        assert "A_rogueVB_P.pak" not in listed["contents"]
        assert sorted(listed["contents"]) == ["A_rogueVA_P.pak", "A_rogueVC_P.pak"]

    def test_restoring_brings_it_back(self, env):
        server.remove_download_file(
            1, server.RemoveDownloadFilePayload(pak_name="A_rogueVB_P.pak")
        )
        _rebuild_rewrites_contents(env["db"])
        result = server.restore_hidden_files(server.RestoreHiddenFilesPayload())
        assert result["restored"] == 1

        listed = next(d for d in server.list_downloads() if d["id"] == 1)
        assert "A_rogueVB_P.pak" in listed["contents"]

    def test_restoring_can_be_scoped_to_one_mod(self, env):
        conn = sqlite3.connect(str(env["db"]))
        conn.execute(
            "INSERT INTO local_downloads(path, id, name, mod_id, contents, active_paks) "
            "VALUES('Other.zip', 2, 'Other', NULL, ?, '[]')",
            (json.dumps(["other.pak"]),),
        )
        conn.commit()
        conn.close()

        server.remove_download_file(
            1, server.RemoveDownloadFilePayload(pak_name="A_rogueVB_P.pak")
        )
        server.remove_download_file(2, server.RemoveDownloadFilePayload(pak_name="other.pak"))

        server.restore_hidden_files(server.RestoreHiddenFilesPayload(download_ids=[1]))
        remaining = server.list_hidden_files()
        assert remaining["count"] == 1
        assert remaining["files"][0]["download_id"] == 2

    def test_nothing_hidden_is_reported_as_nothing(self, env):
        assert server.list_hidden_files() == {"ok": True, "files": [], "count": 0}

    def test_matching_ignores_the_folder_it_sits_in(self, env):
        """contents entries carry a relative path; the record is a basename."""
        conn = sqlite3.connect(str(env["db"]))
        conn.execute(
            "UPDATE local_downloads SET contents = ? WHERE id = 1",
            (json.dumps(["Rogue/A_rogueVA_P.pak", "Rogue/A_rogueVB_P.pak"]),),
        )
        conn.commit()
        conn.close()

        server.remove_download_file(
            1, server.RemoveDownloadFilePayload(pak_name="Rogue/A_rogueVB_P.pak")
        )
        _rebuild_rewrites_contents(env["db"])
        conn = sqlite3.connect(str(env["db"]))
        conn.execute(
            "UPDATE local_downloads SET contents = ? WHERE id = 1",
            (json.dumps(["Rogue/A_rogueVA_P.pak", "Rogue/A_rogueVB_P.pak"]),),
        )
        conn.commit()
        conn.close()

        listed = next(d for d in server.list_downloads() if d["id"] == 1)
        assert listed["contents"] == ["Rogue/A_rogueVA_P.pak"]


class TestTheModsOwnFileListHonoursIt:
    """get_local_download is what the mod's Files tab actually reads.

    Only list_downloads filtered removed files, so after "Initial Database
    Build" every removed pak was visibly back inside the mod — the record was
    kept, the panel counted them, and the one screen that mattered ignored it.
    """

    def test_a_removed_file_is_not_in_contents(self, env):
        server.remove_download_file(
            1, server.RemoveDownloadFilePayload(pak_name="A_rogueVB_P.pak")
        )
        _rebuild_rewrites_contents(env["db"])
        row = server.get_local_download(1)
        assert "A_rogueVB_P.pak" not in row["contents"]
        assert sorted(row["contents"]) == ["A_rogueVA_P.pak", "A_rogueVC_P.pak"]

    def test_it_is_reported_separately_so_the_mod_can_show_it(self, env):
        server.remove_download_file(
            1, server.RemoveDownloadFilePayload(pak_name="A_rogueVB_P.pak")
        )
        assert server.get_local_download(1)["hidden_contents"] == ["A_rogueVB_P.pak"]

    def test_nothing_hidden_means_an_empty_list_not_a_missing_key(self, env):
        assert server.get_local_download(1)["hidden_contents"] == []

    def test_a_hidden_file_is_never_reported_as_active(self, env):
        """It is out of the list, so there would be no way to switch it off.

        Removal deactivates the pak for real, but the read path must not depend
        on that having succeeded: a stale active_paks entry would otherwise show
        a mod as on with nothing on screen to turn off.
        """
        conn = sqlite3.connect(str(env["db"]))
        conn.execute(
            "UPDATE local_downloads SET active_paks = ? WHERE id = 1",
            (json.dumps(["A_rogueVA_P.pak", "A_rogueVB_P.pak"]),),
        )
        conn.commit()
        conn.close()

        _mark_hidden(env["db"], "A_rogueVB_P.pak")
        row = server.get_local_download(1)
        assert "A_rogueVB_P.pak" not in row["active_paks"]
        assert "A_rogueVA_P.pak" in row["active_paks"]

    def test_restoring_one_file_brings_back_only_that_one(self, env):
        for pak in ("A_rogueVB_P.pak", "A_rogueVC_P.pak"):
            server.remove_download_file(
                1, server.RemoveDownloadFilePayload(pak_name=pak)
            )
        result = server.restore_download_file(
            1, server.RemoveDownloadFilePayload(pak_name="A_rogueVB_P.pak")
        )
        assert result["restored"] == 1

        row = server.get_local_download(1)
        assert "A_rogueVB_P.pak" in row["contents"]
        assert row["hidden_contents"] == ["A_rogueVC_P.pak"]

    def test_restoring_takes_effect_without_a_rebuild(self, env):
        server.remove_download_file(
            1, server.RemoveDownloadFilePayload(pak_name="A_rogueVB_P.pak")
        )
        server.restore_download_file(
            1, server.RemoveDownloadFilePayload(pak_name="A_rogueVB_P.pak")
        )
        # No ingest ran in between; the file is simply visible again.
        assert "A_rogueVB_P.pak" in server.get_local_download(1)["contents"]

    def test_restoring_something_not_hidden_is_harmless(self, env):
        result = server.restore_download_file(
            1, server.RemoveDownloadFilePayload(pak_name="A_rogueVA_P.pak")
        )
        assert result["restored"] == 0

    def test_a_blank_name_is_rejected(self, env):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            server.restore_download_file(
                1, server.RemoveDownloadFilePayload(pak_name="   ")
            )
        assert exc.value.status_code == 400


class TestFileNotes:
    def test_saving_and_reading_a_note(self, env):
        server.set_file_note(
            1,
            server.ModFileNotePayload(pak_name="A_rogueVA_P.pak", note="no gloves"),
        )
        notes = server.get_file_notes(1)["notes"]
        assert notes["A_rogueVA_P.pak"]["note"] == "no gloves"

    def test_an_empty_note_deletes_it(self, env):
        server.set_file_note(
            1, server.ModFileNotePayload(pak_name="A_rogueVA_P.pak", note="temp")
        )
        server.set_file_note(
            1, server.ModFileNotePayload(pak_name="A_rogueVA_P.pak", note="   ")
        )
        assert server.get_file_notes(1)["notes"] == {}

    def test_saving_twice_replaces_rather_than_duplicating(self, env):
        for text in ("first", "second"):
            server.set_file_note(
                1, server.ModFileNotePayload(pak_name="A_rogueVA_P.pak", note=text)
            )
        notes = server.get_file_notes(1)["notes"]
        assert len(notes) == 1
        assert notes["A_rogueVA_P.pak"]["note"] == "second"

    def test_notes_are_scoped_to_one_download(self, env):
        """The same pak name under a different download is a different file."""
        conn = sqlite3.connect(str(env["db"]))
        conn.execute(
            "INSERT INTO local_downloads(path, id, name, mod_id, contents, active_paks) "
            "VALUES('Other.zip', 2, 'Other', NULL, ?, '[]')",
            (json.dumps(["A_rogueVA_P.pak"]),),
        )
        conn.commit()
        conn.close()

        server.set_file_note(
            1, server.ModFileNotePayload(pak_name="A_rogueVA_P.pak", note="mine")
        )
        assert server.get_file_notes(2)["notes"] == {}

    def test_a_blank_pak_name_is_rejected(self, env):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            server.set_file_note(1, server.ModFileNotePayload(pak_name="  ", note="x"))
        assert exc.value.status_code == 400

    def test_a_note_survives_removing_and_restoring_the_file(self, env):
        server.set_file_note(
            1, server.ModFileNotePayload(pak_name="A_rogueVB_P.pak", note="keep me")
        )
        server.remove_download_file(
            1, server.RemoveDownloadFilePayload(pak_name="A_rogueVB_P.pak")
        )
        server.restore_hidden_files(server.RestoreHiddenFilesPayload())
        assert server.get_file_notes(1)["notes"]["A_rogueVB_P.pak"]["note"] == "keep me"


def test_endpoints_are_registered():
    paths = {getattr(r, "path", None) for r in server.app.routes}
    assert "/api/local_downloads/hidden-files" in paths
    assert "/api/local_downloads/hidden-files/restore" in paths
    assert "/api/local_downloads/{download_id}/file-notes" in paths


def test_migration_creates_both_tables(tmp_path):
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
        assert "mod_file_notes" in tables
        assert "mod_hidden_files" in tables
    finally:
        conn.close()

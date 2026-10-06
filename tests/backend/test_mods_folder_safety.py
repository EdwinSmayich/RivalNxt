"""The other ways files leave or move within the game's mods folder.

Deleting a download, "disable all", sorting into character folders and
start-up recovery each had their own copy of the same habit: act on one file
at a time and ignore whatever fails. Each had its own way of going wrong.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import core.api.server as server
from core.api.services.downloads import PART_SUFFIX, describe_archive_failure
from core.utils import mod_files
from core.utils.mod_files import (
    GONE_SUFFIX,
    NEW_SUFFIX,
    OLD_SUFFIX,
    FileInUseError,
    find_mod_files,
    recover_interrupted,
    remove_all_or_nothing,
)

STEM = "Mod_9999999_P"
TRIPLE = (f"{STEM}.pak", f"{STEM}.utoc", f"{STEM}.ucas")
SYMBIOTE = "LunaSnow_AbyssalGlow_Symbiote_9999999_P"
windows_only = pytest.mark.skipif(os.name != "nt", reason="open files are only locked on Windows")


def put(folder: Path, names=TRIPLE, body: bytes = b"data") -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for name in names:
        path = folder / name
        path.write_bytes(body + b":" + name.encode())
        out.append(path)
    return out


def tree(folder: Path) -> list[str]:
    return sorted(
        str(p.relative_to(folder)).replace("\\", "/") for p in folder.rglob("*") if p.is_file()
    )


def refuse_replace(monkeypatch, when) -> None:
    real = os.replace

    def guarded(src, dst):
        if when(Path(src)):
            raise PermissionError(13, "The process cannot access the file", str(src))
        return real(src, dst)

    monkeypatch.setattr(mod_files.os, "replace", guarded)


# --------------------------------------------------------------------------
# find_mod_files / remove_all_or_nothing
# --------------------------------------------------------------------------
class TestFindModFiles:
    def test_by_stem_in_any_folder(self, tmp_path):
        put(tmp_path / "hela")
        put(tmp_path, ("Other_P.pak",))
        found = find_mod_files(tmp_path, stems=[STEM.upper()])
        assert sorted(p.name for p in found) == sorted(TRIPLE)

    def test_by_name(self, tmp_path):
        put(tmp_path, ("Other_P.pak", "Other_P.utoc"))
        assert [p.name for p in find_mod_files(tmp_path, names=["sub/OTHER_P.PAK"])] == ["Other_P.pak"]

    def test_a_stem_only_matches_what_a_mod_is_made_of(self, tmp_path):
        put(tmp_path, (f"{STEM}.pak", f"{STEM}.txt", f"{STEM}.sig"))
        assert [p.suffix for p in find_mod_files(tmp_path, stems=[STEM])] == [".pak"]

    def test_a_signature_file_is_only_found_when_asked_for(self, tmp_path):
        """This app never installs one, so it could not put one back."""
        put(tmp_path, (f"{STEM}.pak", f"{STEM}.sig"))
        found = find_mod_files(tmp_path, stems=[STEM], exts=mod_files.MOD_FILE_EXTS)
        assert sorted(p.suffix for p in found) == [".pak", ".sig"]

    def test_nothing_asked_for_finds_nothing(self, tmp_path):
        put(tmp_path)
        assert find_mod_files(tmp_path) == []

    def test_a_missing_folder_finds_nothing(self, tmp_path):
        assert find_mod_files(tmp_path / "nope", stems=[STEM]) == []


class TestRemoveAllOrNothing:
    def test_removes_everything(self, tmp_path):
        files = put(tmp_path)
        assert sorted(p.name for p in remove_all_or_nothing(files)) == sorted(TRIPLE)
        assert tree(tmp_path) == []

    def test_one_file_in_use_keeps_them_all(self, tmp_path, monkeypatch):
        files = put(tmp_path)
        before = {p.name: p.read_bytes() for p in files}
        refuse_replace(monkeypatch, lambda p: p.suffix == ".ucas")

        with pytest.raises(FileInUseError) as caught:
            remove_all_or_nothing(files)

        assert caught.value.path.name == f"{STEM}.ucas"
        assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before

    def test_files_already_gone_are_skipped(self, tmp_path):
        files = put(tmp_path, (f"{STEM}.pak",))
        assert len(remove_all_or_nothing([*files, tmp_path / "never_there.pak"])) == 1

    @windows_only
    def test_with_a_file_that_really_is_open(self, tmp_path):
        files = put(tmp_path)
        with open(tmp_path / f"{STEM}.ucas", "rb"):
            with pytest.raises(FileInUseError):
                remove_all_or_nothing(files)
        assert tree(tmp_path) == sorted(TRIPLE)

    def test_what_a_dead_removal_left_is_cleared_not_restored(self, tmp_path):
        """A file on its way out must not come back as a mod nobody installed."""
        leftover = tmp_path / f"{STEM}.pak.0123abcd{GONE_SUFFIX}"
        leftover.write_bytes(b"was being deleted")

        report = recover_interrupted(tmp_path)

        assert tree(tmp_path) == []
        assert report["restored"] == []


# --------------------------------------------------------------------------
# Deleting a download
# --------------------------------------------------------------------------
@pytest.fixture
def library(monkeypatch, tmp_path, schema_db):
    """A game folder, a downloads folder and one active download with an archive."""
    from core.config.settings import get_mods_dir
    import core.config.settings as settings_mod

    game_root = tmp_path / "game"
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    mods_dir = get_mods_dir(game_root)
    mods_dir.mkdir(parents=True)

    archive = downloads / "TheMod.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for name in TRIPLE:
            zf.writestr(name, b"x")

    monkeypatch.setattr(
        settings_mod,
        "SETTINGS",
        settings_mod.replace(
            settings_mod.SETTINGS,
            marvel_rivals_root=game_root,
            marvel_rivals_local_downloads_root=downloads,
        ),
    )
    schema_db.execute(
        "INSERT INTO local_downloads(path, id, name, mod_id, version, contents, active_paks) "
        "VALUES(?, 1, 'The Mod', NULL, '1.0', ?, ?)",
        (str(archive), json.dumps([f"{STEM}.pak"]), json.dumps(sorted(TRIPLE))),
    )
    schema_db.commit()
    put(mods_dir / "hela")

    class _NoClose:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def close(self):
            pass

    monkeypatch.setattr(server, "get_db", lambda: _NoClose(schema_db))
    monkeypatch.setattr(server, "_get_current_settings", lambda: settings_mod.SETTINGS)
    monkeypatch.setattr(server, "_safe_rebuild_conflicts", lambda *a, **k: None)
    monkeypatch.setattr(server, "scan_active_main", lambda *a, **k: None)
    monkeypatch.setattr(server, "_log_activity", lambda *a, **k: None)
    return {"mods_dir": mods_dir, "archive": archive, "db": schema_db, "game_root": game_root}


def rows(db) -> int:
    return db.execute("SELECT COUNT(*) FROM local_downloads").fetchone()[0]


class TestDeletingADownload:
    def test_it_takes_its_files_out_of_the_game(self, library):
        from core.db.db import delete_local_downloads

        deleted, _mods, _paths = delete_local_downloads(library["db"], [1])

        assert deleted == 1
        assert tree(library["mods_dir"]) == []

    def test_a_file_the_game_has_open_stops_the_delete_before_it_starts(self, library, monkeypatch):
        """Was: record and archive deleted, the mod left in the game with no owner."""
        from core.db.db import delete_local_downloads

        refuse_replace(monkeypatch, lambda p: p.suffix == ".ucas")

        with pytest.raises(FileInUseError):
            delete_local_downloads(library["db"], [1])

        assert rows(library["db"]) == 1
        assert tree(library["mods_dir"]) == sorted(f"hela/{n}" for n in TRIPLE)
        active = json.loads(
            library["db"].execute("SELECT active_paks FROM local_downloads WHERE id = 1").fetchone()[0]
        )
        assert sorted(active) == sorted(TRIPLE)

    def test_the_endpoint_answers_423_and_keeps_the_archive(self, library, monkeypatch):
        refuse_replace(monkeypatch, lambda p: p.suffix == ".ucas")
        # The route runs on a worker thread, which needs a connection of its own.
        db_file = library["db"].execute("PRAGMA database_list").fetchone()[2]
        monkeypatch.setattr(server, "get_db", lambda: sqlite3.connect(db_file))
        client = TestClient(server.app, raise_server_exceptions=False)

        response = client.post("/api/local_downloads/delete", json={"download_ids": [1]})

        assert response.status_code == 423
        body = response.json()
        assert body["error"] == "file_in_use"
        assert f"{STEM}.ucas is in use" in body["detail"]
        assert "Close the game" in body["detail"]
        assert library["archive"].exists()
        assert rows(library["db"]) == 1

    def test_deleting_does_take_the_signature_file_as_it_always_did(self, library):
        from core.db.db import delete_local_downloads

        (library["mods_dir"] / "hela" / f"{STEM}.sig").write_bytes(b"signature")

        delete_local_downloads(library["db"], [1])

        assert tree(library["mods_dir"]) == []

    def test_a_download_that_is_not_active_is_deleted_as_before(self, library):
        from core.db.db import delete_local_downloads

        library["db"].execute("UPDATE local_downloads SET active_paks = '[]' WHERE id = 1")
        library["db"].commit()

        deleted, _mods, _paths = delete_local_downloads(library["db"], [1])

        assert deleted == 1
        # Not recorded as active, so its files are none of this call's business.
        assert len(tree(library["mods_dir"])) == 3


class TestDeactivateByName:
    def refuse_unlink(self, monkeypatch, when) -> None:
        real = Path.unlink

        def guarded(path, *args, **kwargs):
            if when(path):
                raise PermissionError(13, "The process cannot access the file", str(path))
            return real(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", guarded)
        monkeypatch.setattr(mod_files.os, "chmod", lambda *_a, **_k: None)

    def test_removes_the_mod(self, library):
        result = server.deactivate_by_name({"name": "The Mod"})
        assert result["ok"] and result["locked"] == []
        assert tree(library["mods_dir"]) == []

    def test_a_signature_file_beside_it_is_left_alone(self, library):
        """Switching the mod back on would not bring it back."""
        signature = library["mods_dir"] / "hela" / f"{STEM}.sig"
        signature.write_bytes(b"signature")

        server.deactivate_by_name({"name": "The Mod"})

        assert tree(library["mods_dir"]) == [f"hela/{STEM}.sig"]

    def test_a_stuck_container_is_reported(self, library, monkeypatch):
        self.refuse_unlink(monkeypatch, lambda p: p.suffix == ".ucas")
        result = server.deactivate_by_name({"name": "The Mod"})
        assert result["locked"] == [f"{STEM}.ucas"]

    def test_a_stuck_pak_is_an_error_and_the_mod_stays_whole(self, library, monkeypatch):
        self.refuse_unlink(monkeypatch, lambda p: p.suffix == ".pak")

        with pytest.raises(HTTPException) as caught:
            server.deactivate_by_name({"name": "The Mod"})

        assert caught.value.status_code == 423
        assert len(tree(library["mods_dir"])) == 3


# --------------------------------------------------------------------------
# "Disable all"
# --------------------------------------------------------------------------
class TestDisableAll:
    def test_mods_we_installed_are_removed(self, library):
        result = server.disable_all_mods()

        assert result["ok"] is True
        assert result["removed"] == 3
        assert tree(library["mods_dir"]) == []

    def test_mods_put_there_by_hand_are_moved_out_not_destroyed(self, library):
        """Was: every file under ~mods deleted, with no archive to restore from."""
        put(library["mods_dir"] / "magik", ("Handmade_P.pak", "Handmade_P.utoc", "Handmade_P.ucas"), b"mine")
        put(library["mods_dir"], ("Loose_P.pak",), b"mine")

        result = server.disable_all_mods()

        assert tree(library["mods_dir"]) == []
        holding = Path(result["holding_dir"])
        assert tree(holding) == [
            "Loose_P.pak",
            "magik/Handmade_P.pak",
            "magik/Handmade_P.ucas",
            "magik/Handmade_P.utoc",
        ]
        assert (holding / "magik" / "Handmade_P.ucas").read_bytes() == b"mine:Handmade_P.ucas"
        assert sorted(result["moved_out"]) == ["Handmade_P.pak", "Handmade_P.ucas", "Handmade_P.utoc", "Loose_P.pak"]

    def test_they_go_somewhere_the_game_does_not_read(self, library):
        put(library["mods_dir"], ("Handmade_P.pak",))

        result = server.disable_all_mods()

        holding = Path(result["holding_dir"])
        paks = library["mods_dir"].parent
        assert paks not in holding.parents, "anything under Content/Paks is still loaded"
        assert library["game_root"] in holding.parents

    def test_the_answer_says_where_they_went(self, library):
        put(library["mods_dir"], ("Handmade_P.pak",))
        result = server.disable_all_mods()
        assert "1 file(s) that RivalNxt did not install were moved to" in result["warning"]
        assert result["holding_dir"] in result["warning"]

    def test_with_nothing_unmanaged_there_is_no_holding_folder(self, library):
        result = server.disable_all_mods()
        assert result["holding_dir"] is None
        assert "warning" not in result
        assert not (library["game_root"] / server.DISABLED_MODS_FOLDER_NAME).exists()

    def test_files_the_game_does_not_load_are_left_where_they_are(self, library):
        note = library["mods_dir"] / "readme.txt"
        note.write_text("my notes")

        result = server.disable_all_mods()

        assert note.read_text() == "my notes"
        assert result["moved_out"] == []

    def test_signature_files_stay_where_they_are(self, library):
        """Not loaded on their own, and not something this app can restore."""
        ours = library["mods_dir"] / "hela" / f"{STEM}.sig"
        ours.write_bytes(b"signature")
        theirs = library["mods_dir"] / "Handmade_P.sig"
        theirs.write_bytes(b"signature")
        put(library["mods_dir"], ("Handmade_P.pak",))

        result = server.disable_all_mods()

        assert ours.read_bytes() == b"signature" and theirs.read_bytes() == b"signature"
        assert result["moved_out"] == ["Handmade_P.pak"]

    def test_every_download_is_recorded_as_off(self, library):
        server.disable_all_mods()
        stored = library["db"].execute("SELECT active_paks FROM local_downloads WHERE id = 1").fetchone()[0]
        assert json.loads(stored) == []

    def test_a_mod_that_could_not_be_moved_out_is_named(self, library, monkeypatch):
        put(library["mods_dir"], ("Handmade_P.pak",))
        real = mod_files.shutil.move

        def refusing(src, dst):
            if "Handmade" in str(src):
                raise PermissionError(13, "in use", src)
            return real(src, dst)

        monkeypatch.setattr(mod_files.shutil, "move", refusing)
        result = server.disable_all_mods()

        assert result["still_on"] == ["Handmade_P.pak"]
        assert (library["mods_dir"] / "Handmade_P.pak").exists()
        assert "still in the mods folder" in result["warning"]


# --------------------------------------------------------------------------
# Sorting into character folders
# --------------------------------------------------------------------------
@pytest.fixture
def sorting(tmp_path, monkeypatch):
    mods_dir = tmp_path / "~mods"
    mods_dir.mkdir()
    db_path = tmp_path / "mods.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE local_downloads (id INTEGER PRIMARY KEY, name TEXT, mod_id INTEGER, active_paks TEXT);
        CREATE TABLE pak_tags_json (pak_name TEXT PRIMARY KEY, tags_json TEXT);
        CREATE TABLE mod_custom_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT, mod_id INTEGER NOT NULL,
            tag TEXT NOT NULL COLLATE NOCASE, added_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE characters (character_id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE skins (skin_id TEXT PRIMARY KEY, character_id TEXT, variant TEXT, name TEXT);
        CREATE TABLE activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
            kind TEXT NOT NULL, summary TEXT NOT NULL, detail TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO local_downloads (id, name, mod_id, active_paks) VALUES (153, 'symbiote.zip', 5399, ?)",
        (json.dumps([f"{SYMBIOTE}.pak"]),),
    )
    conn.execute(
        "INSERT INTO pak_tags_json (pak_name, tags_json) VALUES (?, ?)",
        (f"{SYMBIOTE}.pak", json.dumps(["Luna Snow"])),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(server, "_mods_folder_from_env", lambda: mods_dir)
    monkeypatch.setattr(server, "get_db", lambda: sqlite3.connect(str(db_path)))
    monkeypatch.setattr(server, "_SKIN_INDEX", None, raising=False)
    for ext in (".pak", ".utoc", ".ucas"):
        (mods_dir / f"{SYMBIOTE}{ext}").write_bytes(b"\x00")
    return mods_dir


class TestSortingWithTheGameRunning:
    def test_a_container_in_use_leaves_the_whole_mod_where_it_was(self, sorting, monkeypatch):
        """Was: .pak and .utoc in the hero folder, .ucas still at the root."""
        real = os.rename

        def guarded(src, dst):
            if str(src).endswith(".ucas"):
                raise PermissionError(13, "The process cannot access the file", str(src))
            return real(src, dst)

        monkeypatch.setattr(mod_files.os, "rename", guarded)

        result = server._refile_active_paks()

        assert tree(sorting) == sorted(f"{SYMBIOTE}{ext}" for ext in (".pak", ".utoc", ".ucas"))
        assert result["moved"] == 0
        assert result["in_use"] == 1
        assert result["in_use_files"] == [f"{SYMBIOTE}.ucas"]

    def test_and_the_next_pass_moves_it_once_the_game_lets_go(self, sorting):
        result = server._refile_active_paks()
        assert result["moved"] == 3 and result["in_use"] == 0
        assert tree(sorting) == sorted(f"luna_snow/{SYMBIOTE}{ext}" for ext in (".pak", ".utoc", ".ucas"))

    def test_a_companion_whose_name_is_taken_holds_the_whole_mod_back(self, sorting):
        """One file skipped and two moved is a mod in two places."""
        (sorting / "luna_snow").mkdir()
        (sorting / "luna_snow" / f"{SYMBIOTE}.utoc").write_bytes(b"other")

        result = server._refile_active_paks()

        assert result["moved"] == 0
        assert result["conflicting_files"] == [f"{SYMBIOTE}.utoc"]
        assert (sorting / f"{SYMBIOTE}.pak").exists()

    @windows_only
    def test_with_a_container_that_really_is_open(self, sorting):
        with open(sorting / f"{SYMBIOTE}.ucas", "rb"):
            result = server._refile_active_paks()
        assert result["moved"] == 0 and result["in_use"] == 1
        assert not (sorting / "luna_snow" / f"{SYMBIOTE}.pak").exists()


# --------------------------------------------------------------------------
# Start-up
# --------------------------------------------------------------------------
class TestStartupHousekeeping:
    def test_it_runs_when_the_server_starts(self, monkeypatch):
        ran: list[str] = []
        monkeypatch.setattr(server, "_startup_housekeeping", lambda: ran.append("yes"))

        with TestClient(server.app):
            pass

        assert ran == ["yes"]

    def test_a_failure_in_it_does_not_stop_the_server(self, monkeypatch):
        def explode():
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(server, "_startup_housekeeping", explode)

        with TestClient(server.app) as client:
            assert client.get("/api/does-not-exist").status_code == 404

    def test_it_does_all_three_jobs(self, monkeypatch):
        done: list[str] = []
        monkeypatch.setattr(server, "_sweep_partial_downloads", lambda: done.append("downloads") or 0)
        monkeypatch.setattr(server, "_recover_interrupted_installs", lambda: done.append("installs") or {})
        monkeypatch.setattr(server, "_repair_misparsed_mod_ids", lambda: done.append("ids") or 0)

        server._startup_housekeeping()

        assert done == ["downloads", "installs", "ids"]

    def test_misfiled_downloads_are_moved_and_the_move_is_recorded(self, library, monkeypatch):
        logged: list[tuple] = []
        monkeypatch.setattr(server, "_log_activity", lambda *a, **k: logged.append(a))
        library["db"].execute(
            "INSERT INTO local_downloads(path, id, name, mod_id, version, contents, active_paks) "
            "VALUES('the-ting-v1-1-6853-1.1-1771860521.zip', 50, 'x', 1, '1.1', '[]', '[]')"
        )
        library["db"].commit()

        assert server._repair_misparsed_mod_ids() == 1

        assert library["db"].execute("SELECT mod_id FROM local_downloads WHERE id = 50").fetchone()[0] == 6853
        assert logged and logged[0][0] == "repaired"
        assert "mod 1 -> 6853" in logged[0][2]

    def test_a_database_that_cannot_be_opened_does_not_stop_start_up(self, monkeypatch):
        def broken():
            raise RuntimeError("database is locked")

        monkeypatch.setattr(server, "get_db", broken)
        assert server._repair_misparsed_mod_ids() == 0

    def test_importing_the_module_does_not_run_it(self):
        """It was a bare call at module level, so every import swept a downloads folder."""
        source = Path(server.__file__).read_text(encoding="utf-8")
        assert "\n_sweep_partial_downloads()\n" not in source
        assert "\n_startup_housekeeping()\n" not in source

    def test_an_interrupted_install_is_put_right(self, library):
        aside = library["mods_dir"] / "hela" / f"Other_P.pak.0123abcd{OLD_SUFFIX}"
        aside.write_bytes(b"the working mod")
        staged = library["mods_dir"] / "hela" / f"Other_P.pak.0123abcd{NEW_SUFFIX}"
        staged.write_bytes(b"half")

        report = server._recover_interrupted_installs()

        assert report["restored"] == ["Other_P.pak"]
        assert (library["mods_dir"] / "hela" / "Other_P.pak").read_bytes() == b"the working mod"
        assert not staged.exists()

    def test_recovery_without_a_game_folder_is_a_no_op(self, monkeypatch):
        import core.config.settings as settings_mod

        monkeypatch.setattr(server, "load_settings", lambda: settings_mod.AppSettings())
        assert server._recover_interrupted_installs() == {"restored": [], "discarded": []}

    def test_a_download_still_being_written_is_not_swept(self, library, monkeypatch, tmp_path):
        import core.config.settings as settings_mod

        downloads = library["archive"].parent
        monkeypatch.setattr(server, "load_settings", lambda: settings_mod.SETTINGS)
        live = downloads / f"Busy.zip.abcd1234{PART_SUFFIX}"
        live.write_bytes(b"arriving")
        dead = downloads / f"Dead.zip.abcd1234{PART_SUFFIX}"
        dead.write_bytes(b"abandoned")
        long_ago = time.time() - 3600
        os.utime(dead, (long_ago, long_ago))

        removed = server._sweep_partial_downloads()

        assert removed == 1
        assert live.exists() and not dead.exists()


# --------------------------------------------------------------------------
# Saying "the archive is damaged" for every way a library says it
# --------------------------------------------------------------------------
class TestDamagedArchiveWording:
    @pytest.mark.parametrize(
        "error",
        [
            zipfile.BadZipFile("Bad CRC-32 for file 'Mod_P.ucas'"),
            zipfile.BadZipFile("File is not a zip file"),
            EOFError("Compressed file ended before the end-of-stream marker was reached"),
            RuntimeError("rar member extraction failed after reconfiguration: Failed the read enough data: req=1048576 got=1018368"),
            RuntimeError("invalid header data"),
        ],
        ids=["zip-crc", "not-a-zip", "eof", "rar-short-read", "7z-header"],
    )
    def test_it_is_recognised(self, error):
        text = describe_archive_failure(error, "Mod.zip")
        assert text and "Mod.zip is damaged or incomplete" in text

    def test_a_py7zr_checksum_failure_has_no_words_of_its_own(self):
        """Its text is a tuple; that tuple is what the user was shown."""
        import py7zr.exceptions

        error = py7zr.exceptions.CrcError(297193375, 2584611980, "Mod_P.ucas")
        assert "damaged" not in str(error).lower()
        assert describe_archive_failure(error, "Mod.7z")

    def test_a_zlib_failure_is_recognised_by_type(self):
        import zlib

        try:
            zlib.decompress(b"not deflate data at all")
        except zlib.error as error:
            assert describe_archive_failure(error)

    def test_the_real_error_under_a_wrapper_is_found(self):
        try:
            try:
                raise zipfile.BadZipFile("Bad CRC-32 for file 'Mod_P.ucas'")
            except zipfile.BadZipFile as inner:
                raise RuntimeError("could not install") from inner
        except RuntimeError as outer:
            assert describe_archive_failure(outer)

    @pytest.mark.parametrize(
        "error",
        [
            RuntimeError("member not found in rar"),
            PermissionError(13, "Permission denied"),
            FileNotFoundError(2, "No such file or directory"),
            OSError(28, "No space left on device"),
        ],
        ids=["missing-member", "permission", "not-found", "disk-full"],
    )
    def test_other_failures_are_not_blamed_on_the_archive(self, error):
        assert describe_archive_failure(error, "Mod.zip") is None

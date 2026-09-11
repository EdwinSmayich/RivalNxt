"""When the game was patched, and which mods moved after it.

On 2026-09-11 a game patch broke an entire mod library at once: the containers
were rewritten at 13:03 and afterwards one mod out of ~180 still applied.
Nothing in the manager was wrong -- the files were where they belonged, the AES
key still decrypted the game's containers, the overlaid assets still existed --
but there was no way to see which mods their authors had rebuilt since, short
of opening every card.
"""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.game.patch import detect_patch_time, mods_updated_since, patch_status


@pytest.fixture()
def game(tmp_path):
    """A game folder with containers, and a ~mods folder inside it."""
    paks = tmp_path / "MarvelGame" / "Marvel" / "Content" / "Paks"
    paks.mkdir(parents=True)
    (paks / "~mods").mkdir()
    return {"root": tmp_path, "paks": paks}


@pytest.fixture()
def conn(tmp_path):
    c = sqlite3.connect(str(tmp_path / "m.db"))
    c.execute(
        "CREATE TABLE mods (mod_id INTEGER PRIMARY KEY, name TEXT, author TEXT, "
        "version TEXT, updated_timestamp INTEGER, picture_url TEXT)"
    )
    yield c
    c.close()


def write(path: Path, when: float | None = None) -> Path:
    path.write_bytes(b"\x00" * 16)
    if when is not None:
        os.utime(path, (when, when))
    return path


class TestDetectingThePatch:
    def test_the_newest_container_is_the_patch(self, game):
        old = time.time() - 86400 * 30
        write(game["paks"] / "pakchunk0-Windows.pak", old)
        write(game["paks"] / "pakchunkCharacter-Windows.utoc", old)
        newest = write(game["paks"] / "pakchunkUI-Windows.pak", time.time() - 60)

        found = detect_patch_time(game["root"])

        assert found is not None
        assert found["detected_from"] == newest.name

    def test_activating_a_mod_is_not_a_patch(self, game):
        """~mods is inside Paks; a freshly copied mod must not look like a patch."""
        write(game["paks"] / "pakchunk0-Windows.pak", time.time() - 86400)
        write(game["paks"] / "~mods" / "A_Something_9999999_P.pak", time.time())

        found = detect_patch_time(game["root"])

        assert found["detected_from"] == "pakchunk0-Windows.pak"

    def test_sig_files_count_too(self, game):
        """The 2026-09-11 patch added a .sig beside every container."""
        write(game["paks"] / "pakchunk0-Windows.pak", time.time() - 86400)
        write(game["paks"] / "pakchunk0-Windows.sig", time.time() - 30)

        assert detect_patch_time(game["root"])["detected_from"] == "pakchunk0-Windows.sig"

    def test_unrelated_files_are_ignored(self, game):
        write(game["paks"] / "pakchunk0-Windows.pak", time.time() - 86400)
        write(game["paks"] / "readme.txt", time.time())

        assert detect_patch_time(game["root"])["detected_from"] == "pakchunk0-Windows.pak"

    def test_an_unset_root_is_not_an_error(self):
        assert detect_patch_time(None) is None
        assert detect_patch_time("") is None

    def test_a_wrong_root_is_not_an_error(self, tmp_path):
        assert detect_patch_time(tmp_path / "not-the-game") is None

    def test_an_empty_paks_folder_yields_nothing(self, game):
        assert detect_patch_time(game["root"]) is None


class TestWhichModsMovedAfterIt:
    @staticmethod
    def add(conn, mod_id, name, updated_epoch):
        conn.execute(
            "INSERT INTO mods (mod_id, name, author, version, updated_timestamp) "
            "VALUES (?,?,?,?,?)",
            (mod_id, name, "someone", "1.0", updated_epoch),
        )
        conn.commit()

    def test_only_mods_updated_after_the_patch_are_listed(self, conn):
        patch = 1_757_589_780  # 2026-09-11 13:03
        self.add(conn, 1, "rebuilt after", patch + 3600)
        self.add(conn, 2, "untouched", patch - 86400)

        names = [m["name"] for m in mods_updated_since(conn, patch)]

        assert names == ["rebuilt after"]

    def test_newest_first(self, conn):
        patch = 1_757_589_780
        self.add(conn, 1, "an hour after", patch + 3600)
        self.add(conn, 2, "a day after", patch + 86400)

        assert [m["name"] for m in mods_updated_since(conn, patch)] == [
            "a day after", "an hour after"
        ]

    def test_a_mod_updated_exactly_at_the_patch_does_not_count(self, conn):
        patch = 1_757_589_780
        self.add(conn, 1, "same second", patch)
        assert mods_updated_since(conn, patch) == []

    def test_mods_without_a_timestamp_are_skipped(self, conn):
        self.add(conn, 1, "never synced", None)
        assert mods_updated_since(conn, 0) == []

    def test_the_timestamp_is_rendered_as_iso(self, conn):
        patch = 1_757_589_780
        self.add(conn, 1, "rebuilt", patch + 60)
        entry = mods_updated_since(conn, patch)[0]
        assert entry["updated_at"].startswith(
            datetime.fromtimestamp(patch + 60, tz=timezone.utc).strftime("%Y-%m-%d")
        )


class TestTheWholeAnswer:
    def test_it_reports_the_patch_and_the_count(self, game, conn):
        write(game["paks"] / "pakchunk0-Windows.pak", 1_757_589_780)
        conn.execute(
            "INSERT INTO mods (mod_id, name, updated_timestamp) VALUES (1,'rebuilt',?)",
            (1_757_589_780 + 3600,),
        )
        conn.execute(
            "INSERT INTO mods (mod_id, name, updated_timestamp) VALUES (2,'stale',?)",
            (1_757_589_780 - 3600,),
        )
        conn.commit()

        status = patch_status(conn, game["root"])

        assert status["known"] is True
        assert status["mods_total"] == 2
        assert status["updated_count"] == 1
        assert status["updated"][0]["name"] == "rebuilt"

    def test_an_unconfigured_game_says_so_instead_of_failing(self, conn):
        status = patch_status(conn, None)
        assert status["known"] is False
        assert "folder is not set" in status["reason"]

    def test_a_database_without_a_mods_table_does_not_raise(self, game, tmp_path):
        write(game["paks"] / "pakchunk0-Windows.pak", 1_757_589_780)
        bare = sqlite3.connect(str(tmp_path / "bare.db"))
        try:
            status = patch_status(bare, game["root"])
            assert status["known"] is True
            assert status["updated_count"] == 0
        finally:
            bare.close()

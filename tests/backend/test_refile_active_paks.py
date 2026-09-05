"""Already-active paks must end up in the character folder they resolve to now.

set_active_paks decides the ~mods subfolder once, at activation, from what the
database knows at that moment. A mod activated before its pak tags had been
extracted has no character to file under, so it lands at the root of ~mods --
and nothing ever revisits it.

In one real library that left 23 paks loose beside 20 correct character
folders. Every one of them had a correct tag by the time it was noticed:
`A_MrsX_VD_9999999_P.pak` was tagged ROGUE and sat at the root, while
`A_rogueVA_9999999_P.pak` carried the same tag and sat in `rogue/`. Re-tagging
by hand did not help either, because tags are read when activating and the
activation had already happened.

These tests use that pair as the fixture: same tag, different location, only
one of them should move.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import core.api.server as server

MRS_X = "A_MrsX_VD_9999999_P"
ROGUE_VA = "A_rogueVA_9999999_P"
MYSTERY = "SomethingUnrecognisable_P"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """A ~mods folder and a database, wired into the module under test."""
    mods_dir = tmp_path / "~mods"
    mods_dir.mkdir()
    db_path = tmp_path / "mods.db"

    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE local_downloads (
            id INTEGER PRIMARY KEY, name TEXT, mod_id INTEGER, active_paks TEXT
        );
        CREATE TABLE pak_tags_json (pak_name TEXT PRIMARY KEY, tags_json TEXT);
        CREATE TABLE mod_custom_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT, mod_id INTEGER NOT NULL,
            tag TEXT NOT NULL COLLATE NOCASE,
            added_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE characters (character_id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE skins (
            skin_id TEXT PRIMARY KEY, character_id TEXT, variant TEXT, name TEXT
        );
        CREATE TABLE activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
            kind TEXT NOT NULL, summary TEXT NOT NULL, detail TEXT
        );
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(server, "_mods_folder_from_env", lambda: mods_dir)
    monkeypatch.setattr(server, "get_db", lambda: sqlite3.connect(str(db_path)))
    # Module-level caches would otherwise carry a previous test's data in.
    monkeypatch.setattr(server, "_SKIN_INDEX", None, raising=False)

    return {"mods_dir": mods_dir, "db": db_path}


def add_download(env, dl_id: int, name: str, active: list[str], mod_id=None) -> None:
    conn = sqlite3.connect(str(env["db"]))
    conn.execute(
        "INSERT INTO local_downloads (id, name, mod_id, active_paks) VALUES (?,?,?,?)",
        (dl_id, name, mod_id, json.dumps(active)),
    )
    conn.commit()
    conn.close()


def tag_pak(env, pak: str, tags: list[str]) -> None:
    conn = sqlite3.connect(str(env["db"]))
    conn.execute(
        "INSERT OR REPLACE INTO pak_tags_json (pak_name, tags_json) VALUES (?,?)",
        (pak, json.dumps(tags)),
    )
    conn.commit()
    conn.close()


def place(mods_dir: Path, rel: str, body: bytes = b"\x00") -> Path:
    target = mods_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    return target


class TestTheLoosePakGetsFiled:
    def test_a_loose_pak_moves_into_its_character_folder(self, env):
        place(env["mods_dir"], f"{MRS_X}.pak")
        tag_pak(env, f"{MRS_X}.pak", ["ROGUE", "mrs. x,material"])
        add_download(env, 153, "sexy-mrsx-v1-1-6853-1.1.zip", [f"{MRS_X}.pak"], mod_id=6853)

        result = server._refile_active_paks()

        assert result["moved"] == 1
        assert not (env["mods_dir"] / f"{MRS_X}.pak").exists()
        assert (env["mods_dir"] / "rogue" / f"{MRS_X}.pak").is_file()

    def test_a_pak_already_in_the_right_folder_is_not_touched(self, env):
        already = place(env["mods_dir"], f"rogue/{ROGUE_VA}.pak")
        before = already.stat().st_mtime_ns
        tag_pak(env, f"{ROGUE_VA}.pak", ["ROGUE", "default,material"])
        add_download(env, 160, "rogue-mod.zip", [f"{ROGUE_VA}.pak"], mod_id=99)

        result = server._refile_active_paks()

        assert result["moved"] == 0
        assert already.is_file()
        assert already.stat().st_mtime_ns == before

    def test_the_same_tag_moves_one_and_leaves_the_other(self, env):
        """The pair from the real library: identical tag, different locations."""
        place(env["mods_dir"], f"{MRS_X}.pak")
        place(env["mods_dir"], f"rogue/{ROGUE_VA}.pak")
        tag_pak(env, f"{MRS_X}.pak", ["ROGUE"])
        tag_pak(env, f"{ROGUE_VA}.pak", ["ROGUE"])
        add_download(env, 153, "mrsx.zip", [f"{MRS_X}.pak"], mod_id=6853)
        add_download(env, 160, "rogue.zip", [f"{ROGUE_VA}.pak"], mod_id=99)

        result = server._refile_active_paks()

        assert result["moved"] == 1
        assert result["downloads"] == 1
        assert (env["mods_dir"] / "rogue" / f"{MRS_X}.pak").is_file()
        assert (env["mods_dir"] / "rogue" / f"{ROGUE_VA}.pak").is_file()


class TestWhatTravelsAndWhatDoesNot:
    def test_iostore_companions_travel_with_the_pak(self, env):
        """A .pak without its .utoc/.ucas is ignored by the game."""
        for ext in (".pak", ".utoc", ".ucas"):
            place(env["mods_dir"], f"{MRS_X}{ext}")
        tag_pak(env, f"{MRS_X}.pak", ["ROGUE"])
        add_download(env, 153, "mrsx.zip", [f"{MRS_X}.pak"], mod_id=6853)

        result = server._refile_active_paks()

        assert result["moved"] == 3
        for ext in (".pak", ".utoc", ".ucas"):
            assert (env["mods_dir"] / "rogue" / f"{MRS_X}{ext}").is_file()
            assert not (env["mods_dir"] / f"{MRS_X}{ext}").exists()

    def test_a_download_whose_character_is_unknown_is_left_alone(self, env):
        """No character means no folder to move it to. Leave it where it is."""
        loose = place(env["mods_dir"], f"{MYSTERY}.pak")
        add_download(env, 200, "mystery.zip", [f"{MYSTERY}.pak"])

        result = server._refile_active_paks()

        assert result["moved"] == 0
        assert result["unresolved"] == 1
        assert loose.is_file()

    def test_inactive_downloads_are_ignored(self, env):
        place(env["mods_dir"], f"{MRS_X}.pak")
        tag_pak(env, f"{MRS_X}.pak", ["ROGUE"])
        add_download(env, 153, "mrsx.zip", [], mod_id=6853)

        assert server._refile_active_paks()["moved"] == 0
        assert (env["mods_dir"] / f"{MRS_X}.pak").is_file()


class TestSafety:
    def test_dry_run_reports_without_moving_anything(self, env):
        loose = place(env["mods_dir"], f"{MRS_X}.pak")
        tag_pak(env, f"{MRS_X}.pak", ["ROGUE"])
        add_download(env, 153, "mrsx.zip", [f"{MRS_X}.pak"], mod_id=6853)

        result = server._refile_active_paks(dry_run=True)

        assert result["moved"] == 1
        assert result["details"][0] == {"file": f"{MRS_X}.pak", "to": "rogue"}
        assert loose.is_file(), "dry run moved a file"
        assert not (env["mods_dir"] / "rogue").exists()

    def test_a_name_collision_is_reported_not_overwritten(self, env):
        """Same basename in both places: moving would destroy one of them."""
        loose = place(env["mods_dir"], f"{MRS_X}.pak", b"loose")
        existing = place(env["mods_dir"], f"rogue/{MRS_X}.pak", b"already-there")
        tag_pak(env, f"{MRS_X}.pak", ["ROGUE"])
        add_download(env, 153, "mrsx.zip", [f"{MRS_X}.pak"], mod_id=6853)

        result = server._refile_active_paks()

        assert result["moved"] == 0
        assert result["conflicts"] == 1
        assert result["conflicting_files"] == [f"{MRS_X}.pak"]
        assert loose.read_bytes() == b"loose"
        assert existing.read_bytes() == b"already-there"

    def test_a_hand_written_tag_decides_the_folder(self, env):
        """The user's own tag outranks everything, as it does on activation."""
        place(env["mods_dir"], f"{MYSTERY}.pak")
        conn = sqlite3.connect(str(env["db"]))
        conn.execute("INSERT INTO mod_custom_tags (mod_id, tag) VALUES (?,?)", (-200, "Magik"))
        conn.commit()
        conn.close()
        add_download(env, 200, "mystery.zip", [f"{MYSTERY}.pak"])

        server._refile_active_paks()

        assert (env["mods_dir"] / "magik" / f"{MYSTERY}.pak").is_file()

    def test_the_move_is_recorded_in_history(self, env):
        place(env["mods_dir"], f"{MRS_X}.pak")
        tag_pak(env, f"{MRS_X}.pak", ["ROGUE"])
        add_download(env, 153, "mrsx.zip", [f"{MRS_X}.pak"], mod_id=6853)

        server._refile_active_paks()

        conn = sqlite3.connect(str(env["db"]))
        rows = conn.execute("SELECT kind, summary FROM activity_log").fetchall()
        conn.close()
        assert rows and rows[0][0] == "refile"
        assert "1 file" in rows[0][1]

    def test_a_row_with_no_file_on_disk_is_reported_as_missing(self, env):
        """Moving cannot conjure a file; only a re-extract can."""
        tag_pak(env, f"{MRS_X}.pak", ["ROGUE"])
        add_download(env, 153, "mrsx.zip", [f"{MRS_X}.pak"], mod_id=6853)

        result = server._refile_active_paks()

        assert result["moved"] == 0
        assert result["missing_downloads"] == [153]

    def test_a_present_file_is_not_reported_as_missing(self, env):
        place(env["mods_dir"], f"{MRS_X}.pak")
        tag_pak(env, f"{MRS_X}.pak", ["ROGUE"])
        add_download(env, 153, "mrsx.zip", [f"{MRS_X}.pak"], mod_id=6853)

        assert server._refile_active_paks()["missing_downloads"] == []

    def test_nothing_is_logged_when_nothing_moved(self, env):
        place(env["mods_dir"], f"rogue/{ROGUE_VA}.pak")
        tag_pak(env, f"{ROGUE_VA}.pak", ["ROGUE"])
        add_download(env, 160, "rogue.zip", [f"{ROGUE_VA}.pak"], mod_id=99)

        server._refile_active_paks()

        conn = sqlite3.connect(str(env["db"]))
        count = conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0]
        conn.close()
        assert count == 0


class TestTheSettingsTask:
    """"Sort Mods Into Folders" must not rewrite the library from its archives.

    It used to call set_active_paks for every active download, and that unlinks
    and re-extracts each destination whether or not it is already correct. On a
    library with hundreds of active paks, sorting three strays re-extracted all
    of them -- and any mod whose archive had since been moved raised 404 and
    could never be sorted.
    """

    def test_it_moves_files_without_touching_any_archive(self, env, monkeypatch):
        called: list[int] = []
        monkeypatch.setattr(
            server, "set_active_paks", lambda dl, payload: called.append(dl)
        )
        place(env["mods_dir"], f"{MRS_X}.pak")
        place(env["mods_dir"], f"rogue/{ROGUE_VA}.pak")
        tag_pak(env, f"{MRS_X}.pak", ["ROGUE"])
        tag_pak(env, f"{ROGUE_VA}.pak", ["ROGUE"])
        add_download(env, 153, "mrsx.zip", [f"{MRS_X}.pak"], mod_id=6853)
        add_download(env, 160, "rogue.zip", [f"{ROGUE_VA}.pak"], mod_id=99)

        code, summary = server._task_reorganize_mods()

        assert code == 0
        assert called == [], "re-extracted an archive it did not need"
        assert summary["files_moved"] == 1
        assert (env["mods_dir"] / "rogue" / f"{MRS_X}.pak").is_file()

    def test_it_re_extracts_only_the_rows_whose_file_is_gone(self, env, monkeypatch):
        called: list[int] = []
        monkeypatch.setattr(
            server, "set_active_paks", lambda dl, payload: called.append(dl)
        )
        place(env["mods_dir"], f"{MRS_X}.pak")
        tag_pak(env, f"{MRS_X}.pak", ["ROGUE"])
        tag_pak(env, f"{ROGUE_VA}.pak", ["ROGUE"])
        add_download(env, 153, "mrsx.zip", [f"{MRS_X}.pak"], mod_id=6853)
        # Active according to the row, but no such file under ~mods.
        add_download(env, 160, "rogue.zip", [f"{ROGUE_VA}.pak"], mod_id=99)

        server._task_reorganize_mods()

        assert called == [160]

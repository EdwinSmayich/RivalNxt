"""Switching a mod on or off, end to end, when something goes wrong half-way.

The three files of a mod were written and deleted one at a time and every
failure was swallowed. With a damaged archive, or with the game running and
holding a container open, that left:

* a new ``.pak`` and ``.utoc`` beside the previous version's ``.ucas``;
* a mod recorded as off whose files were all still there;
* ``.ucas`` files with nothing left to load them, never cleaned up.
"""
from __future__ import annotations

import json
import os
import threading
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import HTTPException

import core.api.server as server
from core.utils import mod_files

STEM = "Mod_9999999_P"
TRIPLE = (f"{STEM}.pak", f"{STEM}.utoc", f"{STEM}.ucas")
UCAS_DATA = bytes(range(256)) * 200
windows_only = pytest.mark.skipif(os.name != "nt", reason="open files are only locked on Windows")


def new_bytes(name: str) -> bytes:
    return UCAS_DATA if name.endswith(".ucas") else b"new:" + name.encode()


def old_bytes(name: str) -> bytes:
    return b"old:" + name.encode()


def build_archive(path: Path, names=TRIPLE) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        for name in names:
            zf.writestr(f"TheMod/{name}", new_bytes(name))
    return path


def damage_the_container(path: Path) -> None:
    """Corrupt the .ucas data, as a download cut short does. The index is intact."""
    raw = bytearray(path.read_bytes())
    at = raw.find(UCAS_DATA[:64]) + 4000
    assert at > 4000
    for i in range(at, at + 32):
        raw[i] ^= 0xFF
    path.write_bytes(bytes(raw))


def snapshot(folder: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(folder)).replace("\\", "/"): p.read_bytes()
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


@pytest.fixture
def env(monkeypatch, tmp_path, schema_db):
    from core.config.settings import get_mods_dir
    import core.config.settings as settings_mod

    game_root = tmp_path / "game"
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    mods_dir = get_mods_dir(game_root)
    mods_dir.mkdir(parents=True)

    archive = build_archive(downloads / "TheMod.zip")

    monkeypatch.setattr(
        settings_mod,
        "SETTINGS",
        settings_mod.replace(
            settings_mod.SETTINGS,
            marvel_rivals_root=game_root,
            marvel_rivals_local_downloads_root=downloads,
        ),
    )

    schema_db.execute("INSERT OR REPLACE INTO mods(mod_id, game, name) VALUES(7, 'marvelrivals', 'The Mod')")
    schema_db.execute(
        "INSERT INTO local_downloads(path, id, name, mod_id, version, contents, active_paks) "
        "VALUES(?, 1, 'The Mod', 7, '1.0', ?, '[]')",
        (str(archive), json.dumps([f"TheMod/{STEM}.pak"])),
    )
    schema_db.commit()

    class _NoClose:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def close(self):
            pass

    monkeypatch.setattr(server, "get_db", lambda: _NoClose(schema_db))
    monkeypatch.setattr(server, "_safe_rebuild_conflicts", lambda *a, **k: None)
    monkeypatch.setattr(server, "scan_active_main", lambda *a, **k: None)
    monkeypatch.setattr(server, "_log_activity", lambda *a, **k: None)

    def active() -> list[str]:
        row = schema_db.execute("SELECT active_paks FROM local_downloads WHERE id = 1").fetchone()
        return json.loads(row[0]) if row and row[0] else []

    def install_previous_version() -> dict[str, bytes]:
        for name in TRIPLE:
            (mods_dir / name).write_bytes(old_bytes(name))
        schema_db.execute(
            "UPDATE local_downloads SET active_paks = ? WHERE id = 1",
            (json.dumps(sorted([f"TheMod/{STEM}.pak", f"{STEM}.utoc", f"{STEM}.ucas"])),),
        )
        schema_db.commit()
        return snapshot(mods_dir)

    return {
        "mods_dir": mods_dir,
        "archive": archive,
        "db": schema_db,
        "active": active,
        "install_previous_version": install_previous_version,
        "downloads": downloads,
    }


def switch_on() -> dict:
    return server.set_active_paks(1, {"active_paks": [f"TheMod/{STEM}.pak"]})


def switch_off() -> dict:
    return server.set_active_paks(1, {"active_paks": []})


def refuse_replace(monkeypatch, when) -> None:
    real = os.replace

    def guarded(src, dst):
        if when(Path(src), Path(dst)):
            raise PermissionError(13, "The process cannot access the file", str(src))
        return real(src, dst)

    monkeypatch.setattr(mod_files.os, "replace", guarded)


@contextmanager
def unlink_refused(monkeypatch, when):
    """Deletes fail for the files ``when`` picks out, for the length of the block."""
    real = Path.unlink

    def guarded(self, *args, **kwargs):
        if when(self):
            raise PermissionError(13, "The process cannot access the file", str(self))
        return real(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", guarded)
        patch.setattr(mod_files.os, "chmod", lambda *_a, **_k: None)
        yield


# --------------------------------------------------------------------------
class TestSwitchingOn:
    def test_all_three_files_arrive(self, env):
        result = switch_on()

        assert snapshot(env["mods_dir"]) == {name: new_bytes(name) for name in TRIPLE}
        assert result["locked"] == []
        assert {os.path.basename(a) for a in env["active"]()} == set(TRIPLE)

    def test_a_previous_version_is_replaced_completely(self, env):
        env["install_previous_version"]()

        switch_on()

        assert snapshot(env["mods_dir"]) == {name: new_bytes(name) for name in TRIPLE}

    def test_nothing_in_transit_is_left_behind(self, env):
        env["install_previous_version"]()
        switch_on()

        names = [p.name for p in env["mods_dir"].rglob("*")]
        assert sorted(names) == sorted(TRIPLE)


class TestADamagedArchive:
    def test_the_installed_version_is_untouched(self, env):
        """Was: new .pak and .utoc, and a broken .ucas between them."""
        before = env["install_previous_version"]()
        damage_the_container(env["archive"])

        with pytest.raises(HTTPException) as caught:
            switch_on()

        assert caught.value.status_code == 422
        assert "damaged or incomplete" in caught.value.detail
        assert snapshot(env["mods_dir"]) == before

    def test_nothing_is_installed_when_there_was_nothing_before(self, env):
        damage_the_container(env["archive"])

        with pytest.raises(HTTPException):
            switch_on()

        assert snapshot(env["mods_dir"]) == {}

    def test_the_record_still_says_what_is_on_disk(self, env):
        env["install_previous_version"]()
        recorded = env["active"]()
        damage_the_container(env["archive"])

        with pytest.raises(HTTPException):
            switch_on()

        assert env["active"]() == recorded


class TestSwitchingOnWithTheGameRunning:
    def test_a_container_in_use_changes_nothing(self, env, monkeypatch):
        before = env["install_previous_version"]()
        refuse_replace(monkeypatch, lambda src, _dst: src.name == f"{STEM}.ucas")

        with pytest.raises(HTTPException) as caught:
            switch_on()

        assert caught.value.status_code == 423
        assert f"{STEM}.ucas is in use" in caught.value.detail
        assert "Close the game" in caught.value.detail
        assert snapshot(env["mods_dir"]) == before

    def test_the_record_is_not_changed_either(self, env, monkeypatch):
        env["install_previous_version"]()
        recorded = env["active"]()
        refuse_replace(monkeypatch, lambda src, _dst: src.name == f"{STEM}.ucas")

        with pytest.raises(HTTPException):
            switch_on()

        assert env["active"]() == recorded

    @windows_only
    def test_with_a_file_that_really_is_open(self, env):
        before = env["install_previous_version"]()

        with open(env["mods_dir"] / f"{STEM}.ucas", "rb"):
            with pytest.raises(HTTPException) as caught:
                switch_on()

        assert caught.value.status_code == 423
        assert snapshot(env["mods_dir"]) == before


class TestSwitchingOffWithTheGameRunning:
    def test_a_container_in_use_is_reported(self, env, monkeypatch):
        """The mod is off -- its .pak is gone -- and the answer says what stayed."""
        env["install_previous_version"]()
        with unlink_refused(monkeypatch, lambda p: p.suffix == ".ucas"):
            result = switch_off()

        assert result["ok"] is True
        assert result["locked"] == [f"{STEM}.ucas"]
        assert "still has 1 of its files open" in result["warning"]
        assert sorted(snapshot(env["mods_dir"])) == [f"{STEM}.ucas"]

    def test_and_the_mod_is_recorded_as_off(self, env, monkeypatch):
        env["install_previous_version"]()
        with unlink_refused(monkeypatch, lambda p: p.suffix == ".ucas"):
            switch_off()

        assert env["active"]() == []

    def test_a_pak_in_use_fails_loudly_and_keeps_the_mod_whole(self, env, monkeypatch):
        """Was: .utoc and .ucas deleted, .pak left, mod recorded as off."""
        before = env["install_previous_version"]()
        with unlink_refused(monkeypatch, lambda p: p.suffix == ".pak"):
            with pytest.raises(HTTPException) as caught:
                switch_off()

        assert caught.value.status_code == 423
        assert "its mod is still on" in caught.value.detail
        assert snapshot(env["mods_dir"]) == before

    def test_a_mod_that_could_not_be_removed_stays_recorded_as_on(self, env, monkeypatch):
        env["install_previous_version"]()
        with unlink_refused(monkeypatch, lambda p: p.suffix == ".pak"):
            with pytest.raises(HTTPException):
                switch_off()

        assert {os.path.basename(a) for a in env["active"]()} == set(TRIPLE)

    def test_an_ordinary_switch_off_reports_nothing_locked(self, env):
        env["install_previous_version"]()

        result = switch_off()

        assert result["locked"] == []
        assert "warning" not in result
        assert snapshot(env["mods_dir"]) == {}

    @windows_only
    def test_with_a_container_that_really_is_open(self, env):
        env["install_previous_version"]()

        with open(env["mods_dir"] / f"{STEM}.ucas", "rb"):
            result = switch_off()

        assert result["locked"] == [f"{STEM}.ucas"]
        assert env["active"]() == []


class TestLeftoverContainers:
    """What an earlier switch-off with the game running left in the folder."""

    @pytest.fixture(autouse=True)
    def no_waiting(self, monkeypatch):
        monkeypatch.setattr(mod_files, "ORPHAN_MIN_AGE_SECONDS", 0.0)

    def add_other_download(self, env, stem: str) -> None:
        env["db"].execute(
            "INSERT INTO local_downloads(path, id, name, mod_id, version, contents, active_paks) "
            "VALUES(?, 2, 'Other', NULL, '1.0', ?, '[]')",
            (str(env["downloads"] / "Other.zip"), json.dumps([f"{stem}.pak"])),
        )
        env["db"].commit()

    def test_one_from_a_mod_we_installed_is_removed(self, env):
        self.add_other_download(env, "Other_9999999_P")
        orphan = env["mods_dir"] / "hela" / "Other_9999999_P.ucas"
        orphan.parent.mkdir()
        orphan.write_bytes(b"x" * 100)

        switch_on()

        assert not orphan.exists()
        assert not orphan.parent.exists(), "the folder it emptied should go too"

    def test_one_we_know_nothing_about_is_left_alone(self, env):
        stranger = env["mods_dir"] / "Handmade_P.ucas"
        stranger.write_bytes(b"x")

        switch_on()

        assert stranger.exists()

    def test_a_recent_one_is_left_alone(self, env, monkeypatch):
        monkeypatch.setattr(mod_files, "ORPHAN_MIN_AGE_SECONDS", 600.0)
        self.add_other_download(env, "Other_9999999_P")
        orphan = env["mods_dir"] / "Other_9999999_P.ucas"
        orphan.write_bytes(b"x")

        switch_on()

        assert orphan.exists()

    def test_what_was_just_installed_is_never_swept(self, env):
        switch_on()
        assert sorted(snapshot(env["mods_dir"])) == sorted(TRIPLE)

    def test_the_container_just_left_behind_is_picked_up_next_time(self, env, monkeypatch):
        env["install_previous_version"]()
        with unlink_refused(monkeypatch, lambda p: p.suffix == ".ucas"):
            switch_off()
        assert sorted(snapshot(env["mods_dir"])) == [f"{STEM}.ucas"]

        # The game has been closed. Any later change tidies up.
        switch_off()

        assert snapshot(env["mods_dir"]) == {}


class TestOneAtATime:
    def test_the_folder_lock_is_held_for_the_whole_request(self, env, monkeypatch):
        seen: list[bool] = []
        real = server._set_active_paks_locked

        def watching(download_id, payload):
            got: list[bool] = []
            probe = threading.Thread(target=lambda: got.append(mod_files.MODS_FOLDER_LOCK.acquire(blocking=False)))
            probe.start()
            probe.join()
            seen.append(got[0])
            return real(download_id, payload)

        monkeypatch.setattr(server, "_set_active_paks_locked", watching)
        switch_on()

        assert seen == [False], "another request could have got in"

    def test_the_lock_is_released_afterwards(self, env):
        switch_on()
        got: list[bool] = []

        def probe():
            ok = mod_files.MODS_FOLDER_LOCK.acquire(blocking=False)
            got.append(ok)
            if ok:
                mod_files.MODS_FOLDER_LOCK.release()

        thread = threading.Thread(target=probe)
        thread.start()
        thread.join()

        assert got == [True]

    def test_and_after_a_failure_too(self, env):
        damage_the_container(env["archive"])
        with pytest.raises(HTTPException):
            switch_on()
        got: list[bool] = []

        def probe():
            ok = mod_files.MODS_FOLDER_LOCK.acquire(blocking=False)
            got.append(ok)
            if ok:
                mod_files.MODS_FOLDER_LOCK.release()

        thread = threading.Thread(target=probe)
        thread.start()
        thread.join()

        assert got == [True]

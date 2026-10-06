"""settings.json must not be lost to a crash, a race or one bad read.

It holds the Nexus API key and both folders. It used to be written by opening
it for writing, which empties the file before the first byte goes in:

* a process killed at that moment left an empty file;
* another thread reading at that moment (every scan re-reads the settings)
  saw an empty file, fell back to the defaults and made them the live
  settings -- and the next save wrote those defaults to disk;
* a file that could not be parsed was treated as "no settings", and the save
  that runs at every start replaced it.

All three ended the same way: the key and the folders gone, with no copy.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest
from fastapi import HTTPException

from core.config import settings as cfg

KEY = "k" * 40


def make(data_dir: Path, **overrides) -> cfg.AppSettings:
    values = dict(
        data_dir=data_dir,
        marvel_rivals_root=data_dir / "game",
        marvel_rivals_local_downloads_root=data_dir / "downloads",
        nexus_api_key=KEY,
    )
    values.update(overrides)
    return cfg.AppSettings(**values)


@pytest.fixture
def data_dir(tmp_path, monkeypatch) -> Path:
    """A private data directory that load_settings() looks in and nowhere else."""
    monkeypatch.setattr(cfg, "_candidate_data_dirs", lambda: [tmp_path])
    return tmp_path


def settings_file(data_dir: Path) -> Path:
    return data_dir / "settings.json"


class TestAnInterruptedSave:
    def test_a_write_that_dies_halfway_leaves_the_old_file_whole(self, data_dir, monkeypatch):
        assert cfg.save_settings(make(data_dir))
        before = settings_file(data_dir).read_text(encoding="utf-8")

        real_open = open

        class DiesAfterTheFirstBytes:
            def __init__(self, handle):
                self._handle = handle

            def write(self, text):
                self._handle.write(text[:5])
                self._handle.flush()
                raise OSError(28, "No space left on device")

            def __getattr__(self, name):
                return getattr(self._handle, name)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self._handle.close()
                return False

        def failing_open(file, mode="r", *args, **kwargs):
            handle = real_open(file, mode, *args, **kwargs)
            return DiesAfterTheFirstBytes(handle) if "w" in mode else handle

        monkeypatch.setattr(cfg, "open", failing_open, raising=False)
        saved = cfg.save_settings(make(data_dir, nexus_api_key="changed"))
        monkeypatch.undo()

        assert saved is False
        assert settings_file(data_dir).read_text(encoding="utf-8") == before
        assert json.loads(before)["nexus_api_key"] == KEY

    def test_nothing_is_left_lying_about_afterwards(self, data_dir, monkeypatch):
        cfg.save_settings(make(data_dir))

        def refuse(src, dst):
            raise PermissionError(13, "in use")

        monkeypatch.setattr(cfg.os, "replace", refuse)
        monkeypatch.setattr(cfg.time, "sleep", lambda _s: None)
        assert cfg.save_settings(make(data_dir, nexus_api_key="changed")) is False

        assert sorted(p.name for p in data_dir.iterdir() if p.is_file()) == ["settings.json"]

    def test_the_failure_is_recorded_and_cleared_by_the_next_success(self, data_dir, monkeypatch):
        cfg.save_settings(make(data_dir))
        real_replace = os.replace
        monkeypatch.setattr(cfg.os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError(13, "in use")))
        monkeypatch.setattr(cfg.time, "sleep", lambda _s: None)
        cfg.save_settings(make(data_dir, nexus_api_key="changed"))
        assert cfg.LAST_SAVE_ERROR and "settings.json" in cfg.LAST_SAVE_ERROR

        monkeypatch.setattr(cfg.os, "replace", real_replace)
        assert cfg.save_settings(make(data_dir, nexus_api_key="changed"))
        assert cfg.LAST_SAVE_ERROR is None

    def test_a_reader_in_the_way_is_waited_out(self, data_dir, monkeypatch):
        """Windows refuses to replace a file another handle has open."""
        cfg.save_settings(make(data_dir))
        real_replace = os.replace
        calls = {"n": 0}

        def busy_twice(src, dst):
            calls["n"] += 1
            if str(dst).endswith("settings.json") and calls["n"] <= 2:
                raise PermissionError(13, "in use")
            return real_replace(src, dst)

        monkeypatch.setattr(cfg.os, "replace", busy_twice)
        monkeypatch.setattr(cfg.time, "sleep", lambda _s: None)

        assert cfg.save_settings(make(data_dir, nexus_api_key="changed"))
        assert json.loads(settings_file(data_dir).read_text())["nexus_api_key"] == "changed"


class TestReadingWhileSaving:
    def test_a_reader_never_sees_a_half_written_file(self, data_dir):
        """The race that turned a scan during a save into wiped settings."""
        cfg.save_settings(make(data_dir))
        stop = threading.Event()
        bad: list[str] = []

        def reader():
            path = settings_file(data_dir)
            while not stop.is_set():
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    continue  # mid-replace on Windows; load_settings retries this
                try:
                    if json.loads(text).get("nexus_api_key") is None:
                        bad.append(text[:40])
                except ValueError:
                    bad.append(repr(text[:40]))

        thread = threading.Thread(target=reader)
        thread.start()
        try:
            for i in range(150):
                cfg.save_settings(make(data_dir, nexus_api_key=f"key-{i}"))
        finally:
            stop.set()
            thread.join()

        assert bad == []

    def test_load_settings_never_falls_back_to_defaults_mid_save(self, data_dir):
        cfg.save_settings(make(data_dir))
        stop = threading.Event()
        lost: list[object] = []

        def reader():
            while not stop.is_set():
                loaded = cfg.load_settings()
                if loaded.marvel_rivals_root is None:
                    lost.append(loaded)

        thread = threading.Thread(target=reader)
        thread.start()
        try:
            for i in range(150):
                cfg.save_settings(make(data_dir, nexus_api_key=f"key-{i}"))
        finally:
            stop.set()
            thread.join()

        assert lost == []


class TestAFileThatCannotBeRead:
    def test_the_last_good_copy_is_used(self, data_dir):
        cfg.save_settings(make(data_dir))
        cfg.save_settings(make(data_dir, allow_direct_api_downloads=True))  # leaves a .bak
        settings_file(data_dir).write_text("", encoding="utf-8")

        loaded = cfg.load_settings()

        assert loaded.nexus_api_key == KEY
        assert loaded.marvel_rivals_root == (data_dir / "game").resolve()

    def test_a_first_save_already_leaves_a_copy(self, data_dir):
        """Upgrading users have no .bak; saving the same values must make one."""
        settings = make(data_dir)
        cfg.save_settings(settings)
        assert not (data_dir / "settings.json.bak").exists()

        cfg.save_settings(settings)

        assert json.loads((data_dir / "settings.json.bak").read_text())["nexus_api_key"] == KEY

    def test_it_is_set_aside_rather_than_written_over(self, data_dir):
        remains = '{"nexus_api_key": "' + KEY + '", "marvel_rivals_root": "D:\\\\Games'
        settings_file(data_dir).write_text(remains, encoding="utf-8")

        loaded = cfg.load_settings()
        assert loaded.nexus_api_key == ""  # nothing usable, so the defaults
        cfg.save_settings(make(data_dir, nexus_api_key=""))

        # What was there can still be recovered by hand.
        assert (data_dir / "settings.json.corrupt").read_text(encoding="utf-8") == remains
        assert json.loads(settings_file(data_dir).read_text())["nexus_api_key"] == ""

    def test_a_broken_file_never_replaces_the_good_copy(self, data_dir):
        cfg.save_settings(make(data_dir))
        cfg.save_settings(make(data_dir, allow_direct_api_downloads=True))
        good_backup = (data_dir / "settings.json.bak").read_text()
        settings_file(data_dir).write_text("{ not json", encoding="utf-8")

        cfg.save_settings(make(data_dir, nexus_api_key=""))

        assert (data_dir / "settings.json.bak").read_text() == good_backup

    def test_json_that_is_not_an_object_counts_as_unreadable(self, data_dir):
        cfg.save_settings(make(data_dir))
        cfg.save_settings(make(data_dir, allow_direct_api_downloads=True))
        settings_file(data_dir).write_text("null", encoding="utf-8")

        assert cfg.load_settings().nexus_api_key == KEY

    def test_deleting_the_file_still_resets_the_app(self, data_dir):
        """The backup is for damage, not for undoing a deliberate reset."""
        cfg.save_settings(make(data_dir))
        cfg.save_settings(make(data_dir, allow_direct_api_downloads=True))
        settings_file(data_dir).unlink()

        loaded = cfg.load_settings()

        assert loaded.nexus_api_key == ""
        assert loaded.marvel_rivals_root is None


class TestTheBackupCopy:
    def test_it_holds_the_version_before_the_change(self, data_dir):
        cfg.save_settings(make(data_dir, nexus_api_key="first"))
        cfg.save_settings(make(data_dir, nexus_api_key="second"))

        assert json.loads((data_dir / "settings.json.bak").read_text())["nexus_api_key"] == "first"
        assert json.loads(settings_file(data_dir).read_text())["nexus_api_key"] == "second"

    def test_saving_the_same_values_does_not_touch_the_file(self, data_dir):
        """configure() saves at every start; most of the time nothing changed."""
        settings = make(data_dir)
        cfg.save_settings(settings)
        cfg.save_settings(settings)
        stamp = settings_file(data_dir).stat().st_mtime_ns
        backup_stamp = (data_dir / "settings.json.bak").stat().st_mtime_ns

        assert cfg.save_settings(settings) is True

        assert settings_file(data_dir).stat().st_mtime_ns == stamp
        assert (data_dir / "settings.json.bak").stat().st_mtime_ns == backup_stamp


class TestTheSettingsRoute:
    def test_a_save_that_did_not_reach_the_disk_is_not_reported_as_saved(self, monkeypatch):
        import core.api.server as server

        current = cfg.AppSettings(data_dir=cfg.SETTINGS.data_dir)
        monkeypatch.setattr(server, "configure", lambda **_kw: current)
        monkeypatch.setattr(server, "_seed_env_from_settings", lambda: None)
        monkeypatch.setattr(cfg, "LAST_SAVE_ERROR", "settings.json: [Errno 13] Permission denied")

        with pytest.raises(HTTPException) as caught:
            server._apply_settings_update(server.SettingsUpdatePayload(nexus_api_key="abc"))

        assert caught.value.status_code == 500
        assert "could not be written" in caught.value.detail

    def test_a_normal_save_goes_through(self, monkeypatch):
        import core.api.server as server

        current = cfg.AppSettings(data_dir=cfg.SETTINGS.data_dir)
        monkeypatch.setattr(server, "configure", lambda **_kw: current)
        monkeypatch.setattr(server, "_seed_env_from_settings", lambda: None)
        monkeypatch.setattr(cfg, "LAST_SAVE_ERROR", None)

        result = server._apply_settings_update(server.SettingsUpdatePayload(nexus_api_key="abc"))

        assert isinstance(result, dict)

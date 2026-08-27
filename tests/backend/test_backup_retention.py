"""Backups must rotate.

Nothing was ever deleted from the backups directory: every manual snapshot,
every pre-restore safety copy and every pre-compact copy accumulated, and each
one is a full database. A backup system that fills the disk is its own failure
mode.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from core.backup import service


def _archive(dirpath, name: str, created_at: str, payload: bytes = b"x" * 128):
    """Write a minimal but structurally valid backup archive."""
    path = dirpath / f"{name}.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            service.MANIFEST_NAME,
            json.dumps({"manifest_version": 2, "created_at": created_at, "name": name}),
        )
        zf.writestr(service.DB_ENTRY_NAME, payload)
    return path


@pytest.fixture()
def backups(tmp_path):
    d = service.backups_dir(tmp_path)
    made = [
        _archive(d, "oldest", "2026-01-01T00:00:00+00:00"),
        _archive(d, "older", "2026-02-01T00:00:00+00:00"),
        _archive(d, "middle", "2026-03-01T00:00:00+00:00"),
        _archive(d, "newer", "2026-04-01T00:00:00+00:00"),
        _archive(d, "newest", "2026-05-01T00:00:00+00:00"),
    ]
    return tmp_path, made


def test_keeps_the_newest_and_deletes_the_rest(backups):
    root, _ = backups

    removed = service.prune_backups(keep=2, data_dir=root)

    assert len(removed) == 3
    remaining = [b["name"] for b in service.list_backups(data_dir=root)]
    assert remaining == ["newest", "newer"]


def test_the_most_recent_archive_is_never_a_candidate(backups):
    """The newest archive is usually the undo for whatever just happened."""
    root, _ = backups

    service.prune_backups(keep=1, data_dir=root)

    remaining = [b["name"] for b in service.list_backups(data_dir=root)]
    assert remaining == ["newest"]


def test_keeping_more_than_exist_deletes_nothing(backups):
    root, _ = backups
    assert service.prune_backups(keep=99, data_dir=root) == []
    assert len(service.list_backups(data_dir=root)) == 5


def test_keep_below_one_is_refused(backups):
    """Honouring keep=0 would delete every backup the user has."""
    root, _ = backups

    with pytest.raises(service.BackupError, match="at least 1"):
        service.prune_backups(keep=0, data_dir=root)

    assert len(service.list_backups(data_dir=root)) == 5


def test_prune_on_an_empty_directory_is_a_no_op(tmp_path):
    assert service.prune_backups(keep=3, data_dir=tmp_path) == []


class TestCreateBackupRotates:
    def test_new_archive_is_written_before_rotation_counts_it(self, tmp_path, monkeypatch):
        """The backup just requested must survive its own retention pass."""
        d = service.backups_dir(tmp_path)
        for i in range(5):
            _archive(d, f"old{i}", f"2026-0{i + 1}-01T00:00:00+00:00")

        db = tmp_path / "mods.db"
        import sqlite3

        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE local_downloads (id INTEGER PRIMARY KEY, active_paks TEXT)")
        conn.commit()
        conn.close()

        result = service.create_backup(
            name="fresh",
            timestamp="2026-12-01T00:00:00+00:00",
            data_dir=tmp_path,
            keep=2,
        )

        names = [b["name"] for b in service.list_backups(data_dir=tmp_path)]
        assert "fresh" in names, "rotation deleted the backup it was triggered by"
        assert len(names) == 2
        assert len(result["pruned"]) == 4

    def test_keep_none_disables_rotation(self, tmp_path):
        d = service.backups_dir(tmp_path)
        for i in range(3):
            _archive(d, f"old{i}", f"2026-0{i + 1}-01T00:00:00+00:00")

        import sqlite3

        conn = sqlite3.connect(tmp_path / "mods.db")
        conn.execute("CREATE TABLE local_downloads (id INTEGER PRIMARY KEY, active_paks TEXT)")
        conn.commit()
        conn.close()

        result = service.create_backup(
            name="fresh", timestamp="2026-12-01T00:00:00+00:00", data_dir=tmp_path, keep=None
        )

        assert result["pruned"] == []
        assert len(service.list_backups(data_dir=tmp_path)) == 4


class TestBackupsExplainThemselves:
    """The list showed bare internal names with no date and no explanation.

    "pre-compact-images" and "pre-restore safety snapshot / date unknown" told
    the user nothing about what the archive was or whether it was safe to
    delete. Worse, the missing date was a bug: restore_backup computed a real
    timestamp for the filename but wrote the raw (None) argument into the
    manifest.
    """

    def test_a_manual_backup_carries_kind_and_description(self, tmp_path):
        import sqlite3

        conn = sqlite3.connect(tmp_path / "mods.db")
        conn.execute("CREATE TABLE local_downloads (id INTEGER PRIMARY KEY, active_paks TEXT)")
        conn.commit()
        conn.close()

        service.create_backup(name="mine", data_dir=tmp_path, timestamp="2026-05-01T00:00:00+00:00")
        entry = service.list_backups(data_dir=tmp_path)[0]

        assert entry["kind"] == "manual"
        assert entry["description"]
        assert entry["created_at"] == "2026-05-01T00:00:00+00:00"

    def test_an_archive_with_no_created_at_falls_back_to_its_mtime(self, tmp_path):
        """Older safety snapshots have created_at: null and must still date."""
        import json
        import zipfile

        d = service.backups_dir(tmp_path)
        p = d / "pre-restore-legacy.zip"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr(service.MANIFEST_NAME, json.dumps({"manifest_version": 2, "created_at": None}))
            zf.writestr(service.DB_ENTRY_NAME, b"x")

        entry = service.list_backups(data_dir=tmp_path)[0]
        assert entry["created_at"], "no date shown for an archive that has one on disk"
        assert entry["kind"] == "pre-restore"
        assert "undo" in entry["description"].lower()

    def test_kind_is_inferred_from_the_filename_for_old_archives(self, tmp_path):
        import json
        import zipfile

        d = service.backups_dir(tmp_path)
        for name in (
            "pre-compact-images-x.zip",
            "pre-image-shrink-x.zip",
            "pre-restore-x.zip",
            "something-else.zip",
        ):
            p = d / name
            with zipfile.ZipFile(p, "w") as zf:
                zf.writestr(service.MANIFEST_NAME, json.dumps({"manifest_version": 2}))
                zf.writestr(service.DB_ENTRY_NAME, b"x")

        by_path = {Path(e["path"]).name: e for e in service.list_backups(data_dir=tmp_path)}
        assert by_path["pre-compact-images-x.zip"]["kind"] == "pre-compact"
        assert by_path["pre-image-shrink-x.zip"]["kind"] == "pre-compact"
        assert by_path["pre-restore-x.zip"]["kind"] == "pre-restore"
        assert by_path["something-else.zip"]["kind"] == "manual"


class TestDeleteBackup:
    def test_deletes_an_archive_in_the_backups_folder(self, backups):
        root, made = backups
        target = str(made[0])

        result = service.delete_backup(target, data_dir=root)

        assert result["ok"] is True
        assert not Path(target).exists()
        assert len(service.list_backups(data_dir=root)) == 4

    def test_refuses_a_path_outside_the_backups_folder(self, tmp_path):
        """The path comes from the client; an unchecked unlink is a foot-gun."""
        outsider = tmp_path / "important.zip"
        outsider.write_bytes(b"not a backup")

        with pytest.raises(service.BackupError, match="outside the backups folder"):
            service.delete_backup(str(outsider), data_dir=tmp_path / "data")

        assert outsider.exists()

    def test_refuses_a_non_zip(self, tmp_path):
        d = service.backups_dir(tmp_path)
        other = d / "mods.db"
        other.write_bytes(b"database")

        with pytest.raises(service.BackupError, match="only backup archives"):
            service.delete_backup(str(other), data_dir=tmp_path)

        assert other.exists()

    def test_missing_archive_reports_clearly(self, tmp_path):
        d = service.backups_dir(tmp_path)
        with pytest.raises(service.BackupError, match="not found"):
            service.delete_backup(str(d / "nope.zip"), data_dir=tmp_path)

"""The compact_images maintenance task.

Normalising on upload only helps images added afterwards. A library built before
that existed keeps every original, so mods.db stays at its grown size. This task
applies the same normalization to rows already stored.

It rewrites the user's only copy of their mod library, so the properties pinned
here are the ones that make it safe to run: it refuses to start without a
backup, it never enlarges a row, it leaves already-small rows untouched, and
running it twice is a no-op.
"""
from __future__ import annotations

import base64
import io
import random
import sqlite3

import pytest

import core.api.server as server

Image = pytest.importorskip("PIL.Image", reason="Pillow is required for image compaction")


def _photo(w: int, h: int) -> str:
    """Textured image: large as PNG, small as JPEG — the shape being compacted."""
    rnd = random.Random(99)
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            n = rnd.randint(-30, 30)
            px[x, y] = (
                max(0, min(255, x % 256 + n)),
                max(0, min(255, y % 256 + n)),
                max(0, min(255, 100 + n)),
            )
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=0)
    return base64.b64encode(buf.getvalue()).decode()


@pytest.fixture
def image_db(tmp_path, monkeypatch):
    """A data dir with a mods.db holding one oversized and one tiny image."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_file = data_dir / "mods.db"

    conn = sqlite3.connect(db_file)
    # Production runs in WAL mode, and that materially changes what VACUUM does
    # to the file on disk. A fixture using the default rollback journal would
    # pass while the real database never shrank.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE mod_custom_images ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, mod_id INTEGER, "
        "image_data TEXT, filename TEXT, mime_type TEXT)"
    )
    big = _photo(1400, 900)
    assert len(big) > server._COMPACT_MIN_BYTES, "fixture must exceed the threshold"
    tiny = base64.b64encode(b"x" * 64).decode()
    conn.execute(
        "INSERT INTO mod_custom_images (mod_id, image_data, filename, mime_type) VALUES (?,?,?,?)",
        (1, big, "big.png", "image/png"),
    )
    conn.execute(
        "INSERT INTO mod_custom_images (mod_id, image_data, filename, mime_type) VALUES (?,?,?,?)",
        (2, tiny, "tiny.png", "image/png"),
    )
    conn.commit()
    conn.close()

    class _Settings:
        pass

    settings = _Settings()
    settings.data_dir = data_dir

    import core.config.settings as settings_module

    monkeypatch.setattr(settings_module, "SETTINGS", settings, raising=False)
    monkeypatch.setattr(server, "get_db", lambda: sqlite3.connect(db_file))
    monkeypatch.setattr(
        server, "create_backup", lambda **kw: {"path": str(tmp_path / "fake.zip")}, raising=False
    )

    return db_file, len(big), len(tiny)


def _rows(db_file):
    conn = sqlite3.connect(db_file)
    try:
        return {
            r[0]: (r[1], r[2])
            for r in conn.execute("SELECT filename, image_data, mime_type FROM mod_custom_images")
        }
    finally:
        conn.close()


def test_refuses_to_run_without_a_safety_backup(image_db, monkeypatch):
    db_file, big_len, _ = image_db

    def _boom(**kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr("core.backup.create_backup", _boom)

    code, meta = server._task_compact_images()

    assert code == 1
    assert meta["aborted"] == "backup_failed"
    # The library must be exactly as it was.
    assert len(_rows(db_file)["big.png"][0]) == big_len


def test_shrinks_oversized_rows_and_relabels_the_mime(image_db, monkeypatch):
    db_file, big_len, tiny_len = image_db
    monkeypatch.setattr("core.backup.create_backup", lambda **kw: {"path": "x.zip"})

    code, meta = server._task_compact_images()

    assert code == 0
    rows = _rows(db_file)
    assert len(rows["big.png"][0]) < big_len
    assert rows["big.png"][1] == "image/jpeg", "stored bytes are JPEG, label must follow"
    assert meta["rewritten"] == 1
    assert meta["row_bytes_after"] < meta["row_bytes_before"]


def test_leaves_already_small_rows_untouched(image_db, monkeypatch):
    db_file, _, tiny_len = image_db
    monkeypatch.setattr("core.backup.create_backup", lambda **kw: {"path": "x.zip"})

    server._task_compact_images()

    rows = _rows(db_file)
    assert len(rows["tiny.png"][0]) == tiny_len
    assert rows["tiny.png"][1] == "image/png"


def test_second_run_is_a_no_op(image_db, monkeypatch):
    db_file, _, _ = image_db
    monkeypatch.setattr("core.backup.create_backup", lambda **kw: {"path": "x.zip"})

    server._task_compact_images()
    after_first = _rows(db_file)["big.png"][0]

    _, meta = server._task_compact_images()

    # Size is the progress marker, so a compacted row falls below the threshold
    # and is never re-encoded again — no generational JPEG loss.
    assert meta["rewritten"] == 0
    assert _rows(db_file)["big.png"][0] == after_first


def test_task_is_accepted_by_the_run_task_endpoint():
    """The task name must be in the request Literal, not just in the runner.

    Regression: the runner branch and the Settings UI entry both existed while
    SettingsTaskName still omitted the name, so the button returned a 422 and
    the task was unreachable. Nothing in the unit tests noticed.
    """
    import typing

    from core.api.server import SettingsTaskName

    assert "compact_images" in typing.get_args(SettingsTaskName)


def test_the_file_on_disk_actually_shrinks(image_db, monkeypatch):
    """Rewriting rows is not enough — the point is to give the space back.

    Regression: VACUUM ran but no WAL checkpoint did, so the rebuilt database
    stayed in the -wal file and mods.db kept every original page. The rows were
    85% smaller and the file was 1% *larger*.
    """
    db_file, _, _ = image_db
    monkeypatch.setattr("core.backup.create_backup", lambda **kw: {"path": "x.zip"})

    _, meta = server._task_compact_images()

    assert meta["vacuumed"] is True
    assert meta["db_bytes_after"] < meta["db_bytes_before"]
    # Measured independently of what the task reported.
    on_disk = db_file.stat().st_size + sum(
        p.stat().st_size for p in db_file.parent.glob("mods.db-*")
    )
    assert on_disk < meta["db_bytes_before"]


def test_reports_database_size_before_and_after(image_db, monkeypatch):
    _, _, _ = image_db
    monkeypatch.setattr("core.backup.create_backup", lambda **kw: {"path": "x.zip"})

    _, meta = server._task_compact_images()

    assert meta["db_bytes_before"] > 0
    assert meta["db_bytes_after"] > 0
    assert "vacuumed" in meta

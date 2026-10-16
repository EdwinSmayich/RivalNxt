"""Files new in the downloads folder join the library without a full rebuild.

Another program -- the voice-subtitle tool -- puts mod archives into the
downloads folder. Only a full "Initial Database Build" used to bring such a
file into the library, re-reading every archive and asking Nexus about every
mod on the way. Adding the new ones must leave every existing row as it was.
"""
from __future__ import annotations

import json
import zipfile

from core.ingestion.scan_mod_downloads import register_new_downloads


def archive(path, *paks):
    with zipfile.ZipFile(path, "w") as z:
        for name in paks:
            z.writestr(name, b"pak")
    return path


def rows(db):
    return {path: (name, json.loads(active or "[]")) for path, name, active in
            db.execute("SELECT path, name, active_paks FROM local_downloads ORDER BY path")}


def test_only_the_new_file_is_added(schema_db, tmp_path):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    archive(downloads / "Old Mod.zip", "OldMod_P.pak")
    schema_db.execute(
        "INSERT INTO local_downloads(path, id, name, contents, active_paks) VALUES('Old Mod.zip', 5, 'Old Mod', ?, ?)",
        (json.dumps(["OldMod_P.pak"]), json.dumps(["OldMod_P.pak"])),
    )
    schema_db.commit()
    archive(downloads / "RU Subtitles - Storm - Voice.zip", "RU_Subtitles_Storm_Voice_9999999_P.pak")

    added = register_new_downloads(downloads, schema_db)

    found = rows(schema_db)
    assert set(found) == {"Old Mod.zip", "RU Subtitles - Storm - Voice.zip"}
    assert found["Old Mod.zip"] == ("Old Mod", ["OldMod_P.pak"])
    # Named the way the library names any download: by its file name.
    assert added == [found["RU Subtitles - Storm - Voice.zip"][0]]
    assert "Storm" in added[0]


def test_a_row_whose_file_is_missing_is_not_taken_out(schema_db, tmp_path):
    """Pruning is the full rebuild's business, not this one's."""
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    schema_db.execute("INSERT INTO local_downloads(path, id, name, contents) VALUES('Gone.zip', 1, 'Gone', '[]')")
    schema_db.commit()
    archive(downloads / "New.zip", "New_P.pak")

    register_new_downloads(downloads, schema_db)

    assert set(rows(schema_db)) == {"Gone.zip", "New.zip"}


def test_files_without_a_pak_are_ignored(schema_db, tmp_path):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    (downloads / "readme.txt").write_text("hello")
    archive(downloads / "Pictures.zip", "shot.png")

    assert register_new_downloads(downloads, schema_db) == []
    assert rows(schema_db) == {}


def test_a_second_call_adds_nothing(schema_db, tmp_path):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    archive(downloads / "New.zip", "New_P.pak")

    assert len(register_new_downloads(downloads, schema_db)) == 1
    assert register_new_downloads(downloads, schema_db) == []

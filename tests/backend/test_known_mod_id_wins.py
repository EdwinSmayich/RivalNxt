"""An id that came with the download outranks one guessed from the file name.

A download started from Nexus arrives knowing its mod id -- it is in the link.
The renaming step then parsed the file name anyway and used *that* id if it
found one, falling back to the known id only when the name had none. So a name
the parser misread did not just stay misread: it overwrote the right answer.
That is how downloads from mods 6853, 7345 and 8567 ended up filed under mods
1, 1 and 3.
"""
from __future__ import annotations

import sqlite3

import pytest

from core.utils import normalize_mod_filename as norm

GAME = "marvelrivals"


@pytest.fixture
def db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "mods.db"))
    conn.execute("CREATE TABLE mod_id_overrides (local_path TEXT PRIMARY KEY, nexus_mod_id INTEGER)")
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def nexus(monkeypatch):
    """Nexus as it answers for three mods; anything else is not found."""
    asked: list[int] = []
    files = {
        6853: [{"file_id": 1, "file_name": "The Ting-6853-1-1-1771860521.zip", "size_in_bytes": 4, "version": "1.1", "uploaded_timestamp": 1771860521}],
        4985: [{"file_id": 2, "file_name": "x.zip", "size_in_bytes": 4, "version": "1.0", "uploaded_timestamp": 1763999096}],
    }

    def get_mod_files(api_key, game, mod_id):
        asked.append(int(mod_id))
        if int(mod_id) in files:
            return 200, {"files": files[int(mod_id)]}
        return 404, {"error": True, "message": "HTTP Error 404: Not Found"}

    monkeypatch.setattr(norm, "get_mod_files", get_mod_files)
    monkeypatch.setattr(norm, "get_mod_by_md5", lambda *a, **k: (404, {"error": True}))
    return asked


def make(tmp_path, name: str):
    path = tmp_path / name
    path.write_bytes(b"data")
    return path


def test_the_known_id_is_used_when_the_name_says_otherwise(tmp_path, db, nexus):
    """A name an older version of the parser would read as mod 1."""
    path = make(tmp_path, "the-ting-v1-1-6853-1-1-1771860521.zip")

    result = norm.normalize_mod_filename(path, GAME, api_key="k", db_conn=db, known_mod_id=6853)

    assert result["backendModId"] == 6853
    assert nexus[0] == 6853, "Nexus was asked about the guessed id first"


def test_even_when_the_name_carries_a_different_plausible_id(tmp_path, db, nexus):
    path = make(tmp_path, "the-ting-4985-1-0-1763999096.zip")

    result = norm.normalize_mod_filename(path, GAME, api_key="k", db_conn=db, known_mod_id=6853)

    assert result["backendModId"] == 6853


def test_without_a_known_id_the_name_is_still_read(tmp_path, db, nexus):
    path = make(tmp_path, "the-ting-4985-1-0-1763999096.zip")

    result = norm.normalize_mod_filename(path, GAME, api_key="k", db_conn=db)

    assert result["backendModId"] == 4985
    assert result["needsManualModId"] is False


def test_a_name_with_no_id_and_nothing_known_asks_the_user(tmp_path, db, nexus):
    path = make(tmp_path, "TheTing_9999999_P.zip")

    result = norm.normalize_mod_filename(path, GAME, api_key="", db_conn=db)

    assert result["backendModId"] is None
    assert result["needsManualModId"] is True


def test_the_known_id_survives_nexus_not_answering(tmp_path, db, monkeypatch):
    monkeypatch.setattr(norm, "get_mod_files", lambda *a, **k: (0, {"error": True, "message": "offline"}))
    monkeypatch.setattr(norm, "get_mod_by_md5", lambda *a, **k: (0, {"error": True}))
    path = make(tmp_path, "the-ting-v1-1-6853-1-1-1771860521.zip")

    result = norm.normalize_mod_filename(path, GAME, api_key="k", db_conn=db, known_mod_id=6853)

    assert result["backendModId"] == 6853
    assert result["renamed"] is False

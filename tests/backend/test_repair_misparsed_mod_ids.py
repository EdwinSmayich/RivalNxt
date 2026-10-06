"""Downloads already filed under a number from their own name are moved back.

Fixing the parser stops new downloads being misfiled. The ones written before
the fix keep the wrong id until the library is rebuilt -- and until then they
show another mod's name and picture, or none, since the ids involved (1, 3)
belong to mods that left Nexus long ago.

The repair runs at start-up and is deliberately hard to trigger: a real mod
whose version happens to contain a large number must never be "corrected".
"""
from __future__ import annotations

import pytest

from core.db.db import repair_misparsed_mod_ids
from core.utils.mod_filename import parse_mod_filename


def add_download(db, dl_id: int, path: str, mod_id) -> None:
    db.execute(
        "INSERT INTO local_downloads(path, id, name, mod_id, version, contents, active_paks) "
        "VALUES(?, ?, 'x', ?, '1.0', '[]', '[]')",
        (path, dl_id, mod_id),
    )
    db.commit()


def add_mod(db, mod_id: int, name) -> None:
    db.execute("INSERT OR REPLACE INTO mods(mod_id, game, name) VALUES(?, 'marvelrivals', ?)", (mod_id, name))
    db.commit()


def mod_of(db, dl_id: int):
    return db.execute("SELECT mod_id FROM local_downloads WHERE id = ?", (dl_id,)).fetchone()[0]


class TestWhatIsRepaired:
    @pytest.mark.parametrize(
        "path,stored,real",
        [
            ("the-ting-v1-1-6853-1.1-1771860521.zip", 1, 6853),
            ("makeup-file-guardians-vol-3-8567-1.0-1778344834.zip", 3, 8567),
            ("theting-9999999-p-12746-1-1788950166.rar", 9999999, 12746),
        ],
    )
    def test_an_id_that_was_a_number_in_the_name(self, schema_db, path, stored, real):
        add_download(schema_db, 10, path, stored)
        add_mod(schema_db, stored, None)  # Nexus knows nothing by that id

        changed = repair_misparsed_mod_ids(schema_db)

        assert changed == [(10, stored, real)]
        assert mod_of(schema_db, 10) == real

    def test_when_the_wrong_mod_has_no_row_at_all(self, schema_db):
        add_download(schema_db, 10, "the-ting-v1-1-6853-1.1-1771860521.zip", 1)
        assert repair_misparsed_mod_ids(schema_db) == [(10, 1, 6853)]

    def test_a_path_with_folders_in_it(self, schema_db):
        add_download(schema_db, 10, "sub\\folder\\the-ting-v1-1-6853-1.1-1771860521.zip", 1)
        assert repair_misparsed_mod_ids(schema_db) == [(10, 1, 6853)]

    def test_running_it_again_finds_nothing(self, schema_db):
        add_download(schema_db, 10, "the-ting-v1-1-6853-1.1-1771860521.zip", 1)
        repair_misparsed_mod_ids(schema_db)
        assert repair_misparsed_mod_ids(schema_db) == []


class TestWhatIsLeftAlone:
    def test_a_download_whose_id_already_matches_its_name(self, schema_db):
        add_download(schema_db, 10, "the-ting-6853-1-0-1771860521.zip", 6853)
        assert repair_misparsed_mod_ids(schema_db) == []

    def test_an_id_the_user_assigned_by_hand(self, schema_db):
        path = "the-ting-v1-1-6853-1.1-1771860521.zip"
        add_download(schema_db, 10, path, 1)
        schema_db.execute("INSERT INTO mod_id_overrides(local_path, nexus_mod_id) VALUES(?, 1)", (path,))
        schema_db.commit()

        assert repair_misparsed_mod_ids(schema_db) == []
        assert mod_of(schema_db, 10) == 1

    def test_a_stored_id_that_nexus_has_a_name_for(self, schema_db):
        """A real mod, however its file name reads, is not second-guessed."""
        add_download(schema_db, 10, "the-ting-6853-1-2024-0-1771860521.zip", 6853)
        add_mod(schema_db, 6853, "The Ting")
        assert parse_mod_filename("the-ting-6853-1-2024-0-1771860521.zip")[1] != 6853, "fixture no longer ambiguous"

        assert repair_misparsed_mod_ids(schema_db) == []
        assert mod_of(schema_db, 10) == 6853

    def test_a_stored_id_that_is_not_in_the_name(self, schema_db):
        """It came from somewhere else -- the download link -- and stays."""
        add_download(schema_db, 10, "the-ting-6853-1-0-1771860521.zip", 4242)
        assert repair_misparsed_mod_ids(schema_db) == []

    def test_a_stored_id_that_appears_only_after_the_real_one(self, schema_db):
        add_download(schema_db, 10, "the-ting-6853-1-0-1771860521.zip", 1)
        assert repair_misparsed_mod_ids(schema_db) == []

    def test_a_name_with_no_id_in_it(self, schema_db):
        add_download(schema_db, 10, "TheTing_9999999_P.zip", 5)
        assert repair_misparsed_mod_ids(schema_db) == []

    def test_a_local_mod_with_no_id(self, schema_db):
        add_download(schema_db, 10, "the-ting-v1-1-6853-1.1-1771860521.zip", None)
        assert repair_misparsed_mod_ids(schema_db) == []


class TestADateForAVersion:
    """Four digits before the version is what an id looks like -- and what a year looks like."""

    @pytest.mark.parametrize(
        "filename,mod_id,version",
        [
            ("the-ting-6853-2025-01-15-1771860521.zip", 6853, "2025.01.15"),
            ("the-ting-6853-2025-01-1771860521.zip", 6853, "2025.01"),
            ("the-ting-v2-6853-2024-12-25-1771860521.zip", 6853, "2024.12.25"),
        ],
    )
    def test_the_year_is_not_taken_for_the_id(self, filename, mod_id, version):
        _name, got_id, got_version = parse_mod_filename(filename)
        assert (got_id, got_version) == (mod_id, version)

    @pytest.mark.parametrize(
        "filename,mod_id",
        [
            # An id that happens to fall in 1900-2099, with an ordinary version.
            ("the-ting-2050-1-0-1771860521.zip", 2050),
            ("the-ting-v1-1-2050-1-1-1771860521.zip", 2050),
            ("the-ting-2025-2-1771860521.zip", 2025),
            ("the-ting-2099-1.0-1771860521.zip", 2099),
        ],
    )
    def test_an_id_that_looks_like_a_year_is_still_an_id(self, filename, mod_id):
        assert parse_mod_filename(filename)[1] == mod_id

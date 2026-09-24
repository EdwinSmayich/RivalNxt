"""Character names must not be lost to a failed extraction.

The character filter showed "character 1015", "character 1016", "character
1020" where it had shown Storm, Loki and Mantis. All 64 rows in the characters
table were placeholders and none were real names.

Two faults, and the second is what made the first permanent:

* get_all_locres_strings created its scratch directory from a *relative* path,
  so it landed wherever the process was running. The Tauri shell sets no
  working directory for the backend, so that is inherited from however the app
  was launched. Reproduced: run the extraction from C:\\Windows\\System32 and
  it returns 0 names where any writable directory returns 80. The handler
  swallows the error and returns {}, and the combine step then names every
  character "Character <id>".

* insert_characters used INSERT OR REPLACE, so those placeholders overwrote
  the real names. One failed rebuild was enough, and nothing said so: the task
  finished green.
"""
from __future__ import annotations

import sqlite3

import pytest

from core.db.db import insert_characters


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE characters (character_id TEXT PRIMARY KEY, name TEXT)")
    yield c
    c.close()


def name_of(conn, character_id: str) -> str | None:
    row = conn.execute(
        "SELECT name FROM characters WHERE character_id = ?", (character_id,)
    ).fetchone()
    return row[0] if row else None


class TestAPlaceholderNeverReplacesARealName:
    def test_a_failed_rebuild_leaves_the_names_alone(self, conn):
        insert_characters(conn, [("1015", "Storm"), ("1016", "Loki")])
        # What a rebuild writes when the extraction returned nothing.
        insert_characters(conn, [("1015", "Character 1015"), ("1016", "Character 1016")])

        assert name_of(conn, "1015") == "Storm"
        assert name_of(conn, "1016") == "Loki"

    def test_repeated_failures_do_not_wear_it_down(self, conn):
        insert_characters(conn, [("1015", "Storm")])
        for _ in range(5):
            insert_characters(conn, [("1015", "Character 1015")])
        assert name_of(conn, "1015") == "Storm"

    def test_a_placeholder_is_still_recorded_when_nothing_is_known(self, conn):
        """A character seen for the first time has to be stored under some name."""
        insert_characters(conn, [("4043", "Character 4043")])
        assert name_of(conn, "4043") == "Character 4043"

    def test_a_real_name_replaces_a_placeholder(self, conn):
        """The recovery path: once the extraction works, names must land."""
        insert_characters(conn, [("1015", "Character 1015")])
        insert_characters(conn, [("1015", "Storm")])
        assert name_of(conn, "1015") == "Storm"

    def test_a_rename_between_two_real_names_still_applies(self, conn):
        insert_characters(conn, [("1015", "Storm")])
        insert_characters(conn, [("1015", "Ororo Munroe")])
        assert name_of(conn, "1015") == "Ororo Munroe"

    def test_another_characters_placeholder_is_not_special(self, conn):
        """Only the row's own id forms its placeholder; a name that happens to
        look like one for a different id is a real value."""
        insert_characters(conn, [("1015", "Storm")])
        insert_characters(conn, [("1015", "Character 9999")])
        assert name_of(conn, "1015") == "Character 9999"


class TestSkinNamesAreGuardedTheSameWay:
    """The skins table has the same shape of fallback: f"variant {variant}".

    Skin names survived the incident only because combine_extraction_data has a
    Fandom Wiki fallback that character names do not -- 479 real names against
    208 placeholders. That is luck, not a guarantee.
    """

    @pytest.fixture()
    def skinned(self):
        c = sqlite3.connect(":memory:")
        c.execute(
            "CREATE TABLE skins (skin_id TEXT PRIMARY KEY, character_id TEXT, "
            "variant TEXT, name TEXT)"
        )
        yield c
        c.close()

    @staticmethod
    def name_of(conn, skin_id: str):
        row = conn.execute("SELECT name FROM skins WHERE skin_id = ?", (skin_id,)).fetchone()
        return row[0] if row else None

    def test_a_placeholder_does_not_replace_a_real_skin_name(self, skinned):
        from core.db.db import insert_skins

        insert_skins(skinned, [("1031500", "1031", "500", "mirae 2099")])
        insert_skins(skinned, [("1031500", "1031", "500", "variant 500")])

        assert self.name_of(skinned, "1031500") == "mirae 2099"

    def test_a_real_name_still_replaces_a_placeholder(self, skinned):
        from core.db.db import insert_skins

        insert_skins(skinned, [("1031500", "1031", "500", "variant 500")])
        insert_skins(skinned, [("1031500", "1031", "500", "mirae 2099")])

        assert self.name_of(skinned, "1031500") == "mirae 2099"

    def test_a_first_sighting_is_stored_even_as_a_placeholder(self, skinned):
        from core.db.db import insert_skins

        insert_skins(skinned, [("1031500", "1031", "500", "variant 500")])
        assert self.name_of(skinned, "1031500") == "variant 500"


class TestTheExtractionDoesNotDependOnTheWorkingDirectory:
    def test_scratch_directories_are_not_relative(self):
        """A relative scratch path is what tied this to however the app started."""
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[2]
            / "core" / "extraction" / "marvel_rivals_ids.py"
        ).read_text(encoding="utf-8")

        assert 'Path(f"temp_locres_' not in source, (
            "the locres scratch directory is relative again; it must come from "
            "tempfile so an unwritable working directory cannot erase every name"
        )
        assert "tempfile.mkdtemp(prefix=" in source

    def test_the_bundle_check_covers_pylocres(self):
        """Character names are read through pylocres; losing it renames everyone."""
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[2] / "scripts" / "verify_bundle.py"
        ).read_text(encoding="utf-8")
        assert '"pylocres"' in source

"""A mod id assigned by hand must survive "Initial Database Build".

local_downloads.mod_id is derived by parsing the download's filename, and
replace_local_downloads rewrites it from that parse on every rebuild. Once the
app has renamed a file, its new name no longer carries a parseable id — so the
rebuild set mod_id back to NULL and the download detached from its mod. The same
mod then showed up twice: once with artwork, and once as a nameless row asking
to have its id assigned. Every rebuild, again.

Measured on a real library: 48 of 212 downloads had lost their mod id this way,
while mod_id_overrides still held 46 assignments nobody was reading.
"""
from __future__ import annotations

import sqlite3

import pytest

from core.db.db import init_schema, replace_local_downloads, run_migrations


@pytest.fixture()
def conn(tmp_path):
    c = sqlite3.connect(str(tmp_path / "m.db"))
    init_schema(c)
    run_migrations(c)
    yield c
    c.close()


def _scan_row(path: str, name: str, mod_id=None):
    """What a folder scan produces: mod id only if the filename gives one up."""
    row = {"path": path, "name": name, "contents": ["a.pak"], "active_paks": []}
    if mod_id is not None:
        row["modID"] = mod_id
    return row


def _mod_id(conn, path: str):
    return conn.execute(
        "SELECT mod_id FROM local_downloads WHERE path = ?", (path,)
    ).fetchone()[0]


RENAMED = "BodyReshape_JubileeMidnightMutant_Base_11019_1_2026-07-17T20-04Z_e3jCYfIEI.rar"


class TestManualAssignmentSurvives:
    def test_a_rebuild_no_longer_wipes_it(self, conn):
        replace_local_downloads(conn, [_scan_row(RENAMED, "BodyReshape Jubilee")])
        assert _mod_id(conn, RENAMED) is None, "the scan cannot parse this name"

        conn.execute(
            "INSERT INTO mod_id_overrides (local_path, nexus_mod_id) VALUES (?, ?)",
            (RENAMED, 11019),
        )
        conn.commit()

        # The rebuild runs again and re-derives everything from the filename.
        replace_local_downloads(conn, [_scan_row(RENAMED, "BodyReshape Jubilee")])
        assert _mod_id(conn, RENAMED) == 11019

    def test_it_survives_repeated_rebuilds(self, conn):
        conn.execute(
            "INSERT INTO mod_id_overrides (local_path, nexus_mod_id) VALUES (?, ?)",
            (RENAMED, 11019),
        )
        conn.commit()
        for _ in range(3):
            replace_local_downloads(conn, [_scan_row(RENAMED, "BodyReshape Jubilee")])
            assert _mod_id(conn, RENAMED) == 11019

    def test_an_explicit_assignment_outranks_the_filename_guess(self, conn):
        """Assign Mod ID is a deliberate correction; parsing is a heuristic."""
        path = "maskless-malice-remesh-2811-1-1-1746649625.zip"
        replace_local_downloads(conn, [_scan_row(path, "Maskless Malice", mod_id=9999)])
        assert _mod_id(conn, path) == 9999

        conn.execute(
            "INSERT INTO mod_id_overrides (local_path, nexus_mod_id) VALUES (?, ?)",
            (path, 2811),
        )
        conn.commit()
        replace_local_downloads(conn, [_scan_row(path, "Maskless Malice", mod_id=9999)])
        assert _mod_id(conn, path) == 2811

    def test_downloads_without_an_override_are_untouched(self, conn):
        path = "plain-mod-4242-1.0-123.zip"
        replace_local_downloads(conn, [_scan_row(path, "Plain", mod_id=4242)])
        replace_local_downloads(conn, [_scan_row(path, "Plain", mod_id=4242)])
        assert _mod_id(conn, path) == 4242

    def test_two_downloads_of_one_mod_stay_grouped(self, conn):
        """The visible symptom: one mod appearing as two cards."""
        renamed = RENAMED
        original = "bodyreshape-jubileemidnightmutant-base-11019-1-1784318692.rar"
        conn.execute(
            "INSERT INTO mod_id_overrides (local_path, nexus_mod_id) VALUES (?, ?)",
            (renamed, 11019),
        )
        conn.commit()

        replace_local_downloads(
            conn,
            [
                _scan_row(renamed, "BodyReshape Jubilee"),
                _scan_row(original, "bodyreshape-jubileemidnightmutant-base", mod_id=11019),
            ],
        )
        ids = [
            r[0]
            for r in conn.execute("SELECT mod_id FROM local_downloads ORDER BY path")
        ]
        assert ids == [11019, 11019], "both downloads must point at the same mod"

    def test_a_database_without_the_override_table_still_works(self, tmp_path):
        """Older installs predate 0016; the rebuild must not fall over."""
        c = sqlite3.connect(str(tmp_path / "old.db"))
        try:
            init_schema(c)
            run_migrations(c)
            c.execute("DROP TABLE mod_id_overrides")
            c.commit()
            replace_local_downloads(c, [_scan_row("x.zip", "X", mod_id=1)])
            assert _mod_id(c, "x.zip") == 1
        finally:
            c.close()


class TestARescanNeverDowngradesWhatIsKnown:
    """A rescan that cannot read an id must not erase the one already stored.

    The upsert set ``mod_id=excluded.mod_id`` unconditionally, so a scan that
    came back with nothing wrote NULL over a perfectly good id. Overrides were
    re-applied afterwards, which covered ids the user had assigned by hand --
    but not ids that came from a Nexus sync, or from a filename shape the
    parser did not know.

    That is what made an "Addons" download detach from its base mod on every
    rebuild: both are grouped by mod id, and so is their artwork. Measured on
    one library, 12 of 209 downloads lost their id to this, eight of them
    ``_Addons_`` files.
    """

    ADDONS = "BodyReshape_MagikSoullessSword_Addons_9902_1_2026-06-20T19-12Z_V1FxDq0Zh.rar"

    def test_a_scan_without_an_id_keeps_the_stored_one(self, conn):
        replace_local_downloads(conn, [_scan_row(self.ADDONS, "Magik Addons", mod_id=9902)])
        assert _mod_id(conn, self.ADDONS) == 9902

        # Rebuild, this time the scan yields no id at all.
        replace_local_downloads(conn, [_scan_row(self.ADDONS, "Magik Addons")])
        assert _mod_id(conn, self.ADDONS) == 9902, "the rebuild ungrouped the mod"

    def test_repeated_rebuilds_do_not_erode_it(self, conn):
        replace_local_downloads(conn, [_scan_row(self.ADDONS, "Magik Addons", mod_id=9902)])
        for _ in range(5):
            replace_local_downloads(conn, [_scan_row(self.ADDONS, "Magik Addons")])
        assert _mod_id(conn, self.ADDONS) == 9902

    def test_a_scan_that_does_find_an_id_still_wins(self, conn):
        """Only NULL is refused; a real correction must still apply."""
        replace_local_downloads(conn, [_scan_row(self.ADDONS, "Magik Addons", mod_id=9902)])
        replace_local_downloads(conn, [_scan_row(self.ADDONS, "Magik Addons", mod_id=1234)])
        assert _mod_id(conn, self.ADDONS) == 1234

    def test_the_base_and_its_addons_stay_on_one_mod_id(self, conn):
        """The user-visible symptom: one mod becoming two cards."""
        base = "BodyReshape_MagikSoullessSword_Base.rar"
        replace_local_downloads(conn, [
            _scan_row(base, "Magik Base", mod_id=9902),
            _scan_row(self.ADDONS, "Magik Addons", mod_id=9902),
        ])
        # Neither filename gives an id up on the next scan.
        replace_local_downloads(conn, [
            _scan_row(base, "Magik Base"),
            _scan_row(self.ADDONS, "Magik Addons"),
        ])
        ids = {r[0] for r in conn.execute("SELECT mod_id FROM local_downloads")}
        assert ids == {9902}, f"the pair split across {ids}"

    def test_a_version_is_kept_the_same_way(self, conn):
        row = _scan_row(self.ADDONS, "Magik Addons", mod_id=9902)
        row["version"] = "1.2"
        replace_local_downloads(conn, [row])
        replace_local_downloads(conn, [_scan_row(self.ADDONS, "Magik Addons")])
        version = conn.execute(
            "SELECT version FROM local_downloads WHERE path = ?", (self.ADDONS,)
        ).fetchone()[0]
        assert version == "1.2"

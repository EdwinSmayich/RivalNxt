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
        path = "sexy-jubilee-remove-jacket-10878-1.0-1783976607.zip"
        replace_local_downloads(conn, [_scan_row(path, "Sexy Jubilee", mod_id=9999)])
        assert _mod_id(conn, path) == 9999

        conn.execute(
            "INSERT INTO mod_id_overrides (local_path, nexus_mod_id) VALUES (?, ?)",
            (path, 10878),
        )
        conn.commit()
        replace_local_downloads(conn, [_scan_row(path, "Sexy Jubilee", mod_id=9999)])
        assert _mod_id(conn, path) == 10878

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

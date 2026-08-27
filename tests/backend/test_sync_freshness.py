"""Nexus sync must not re-download metadata it already has.

Every rebuild re-synced all 128 linked mods: three HTTP requests each plus a
fixed sleep between them. The freshness check is what makes a repeated rebuild
cheap, and it has to be conservative — skipping a mod that genuinely changed is
worse than an extra request.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from scripts import sync_nexus_to_db as sync


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE mods (mod_id INTEGER PRIMARY KEY, last_synced_at TEXT)")
    yield c
    c.close()


def stamp(conn, mod_id: int, hours_ago: float) -> None:
    when = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO mods (mod_id, last_synced_at) VALUES (?, ?)", (mod_id, when)
    )
    conn.commit()


class TestFreshModIds:
    def test_recently_synced_mods_are_skipped(self, conn):
        stamp(conn, 1, hours_ago=1)
        assert sync._fresh_mod_ids(conn, [1], max_age_hours=12) == {1}

    def test_stale_mods_are_not_skipped(self, conn):
        stamp(conn, 1, hours_ago=48)
        assert sync._fresh_mod_ids(conn, [1], max_age_hours=12) == set()

    def test_never_synced_mods_are_not_skipped(self, conn):
        conn.execute("INSERT INTO mods (mod_id, last_synced_at) VALUES (1, NULL)")
        conn.commit()
        assert sync._fresh_mod_ids(conn, [1], max_age_hours=12) == set()

    def test_unknown_mods_are_not_skipped(self, conn):
        assert sync._fresh_mod_ids(conn, [999], max_age_hours=12) == set()

    def test_zero_max_age_forces_a_full_sync(self, conn):
        stamp(conn, 1, hours_ago=0.01)
        assert sync._fresh_mod_ids(conn, [1], max_age_hours=0) == set()

    def test_only_the_requested_ids_are_considered(self, conn):
        stamp(conn, 1, hours_ago=1)
        stamp(conn, 2, hours_ago=1)
        assert sync._fresh_mod_ids(conn, [1], max_age_hours=12) == {1}

    def test_empty_request_is_a_no_op(self, conn):
        assert sync._fresh_mod_ids(conn, [], max_age_hours=12) == set()

    def test_a_missing_column_syncs_everything(self):
        """An un-migrated database must sync, not silently skip."""
        c = sqlite3.connect(":memory:")
        try:
            c.execute("CREATE TABLE mods (mod_id INTEGER PRIMARY KEY)")
            assert sync._fresh_mod_ids(c, [1, 2, 3], max_age_hours=12) == set()
        finally:
            c.close()

    def test_boundary_just_inside_the_window_is_fresh(self, conn):
        stamp(conn, 1, hours_ago=11.9)
        assert sync._fresh_mod_ids(conn, [1], max_age_hours=12) == {1}

    def test_boundary_just_outside_the_window_is_stale(self, conn):
        stamp(conn, 1, hours_ago=12.1)
        assert sync._fresh_mod_ids(conn, [1], max_age_hours=12) == set()


class TestBootstrapHonoursFreshness:
    """Initial Database Build has its own sync loop, and it ignored all of this.

    scripts/rebuild_sqlite.py duplicates the fetch-and-store logic instead of
    calling sync_mods, so the freshness check above never applied to it and it
    never stamped last_synced_at either. Two consequences, both real: pressing
    the button twice refetched every linked mod, and because the stamp was never
    written, the standalone Sync Nexus task afterwards also saw every mod as
    never-synced. On a free Nexus key that is 100 requests an hour against ~390
    needed.
    """

    @staticmethod
    def _sync(conn, mod_ids, calls, monkeypatch):
        import logging

        from scripts import rebuild_sqlite as rebuild

        monkeypatch.setattr(rebuild, "get_api_key", lambda: "key")
        monkeypatch.setattr(rebuild, "load_prefs", lambda: {})
        monkeypatch.setattr(rebuild, "filter_aggregate_payload", lambda p, _: p)
        monkeypatch.setattr(rebuild, "extract_description_text", lambda _: "")
        monkeypatch.setattr(rebuild, "derive_changelogs_from_files", lambda _: {})
        monkeypatch.setattr(rebuild, "upsert_api_cache", lambda *a, **k: None)
        monkeypatch.setattr(rebuild, "upsert_mod_info", lambda *a, **k: None)
        monkeypatch.setattr(rebuild, "replace_mod_files", lambda *a, **k: None)
        monkeypatch.setattr(rebuild, "replace_mod_changelogs", lambda *a, **k: None)

        def fake_collect(_key, _game, mod_id):
            calls.append(mod_id)
            return {"mod_info_status": 200, "files_status": 200, "changelogs_status": 200}

        monkeypatch.setattr(rebuild, "collect_all_for_mod", fake_collect)
        return rebuild._sync_mod_metadata(
            conn, mod_ids, game="marvelrivals", rate_delay=0, log=logging.getLogger("t")
        )

    def test_a_freshly_synced_mod_is_not_refetched(self, conn, monkeypatch):
        stamp(conn, 1, hours_ago=1)
        stamp(conn, 2, hours_ago=99)
        calls: list[int] = []
        self._sync(conn, [1, 2], calls, monkeypatch)
        assert calls == [2], "mod 1 was synced an hour ago and must not be refetched"

    def test_a_first_build_still_fetches_everything(self, conn, monkeypatch):
        # Nothing has ever been synced, so the *initial* build is unaffected.
        calls: list[int] = []
        self._sync(conn, [1, 2, 3], calls, monkeypatch)
        assert sorted(calls) == [1, 2, 3]

    def test_it_stamps_last_synced_at_so_the_next_run_can_skip(self, conn, monkeypatch):
        conn.execute("INSERT INTO mods (mod_id, last_synced_at) VALUES (1, NULL)")
        conn.commit()
        self._sync(conn, [1], [], monkeypatch)
        assert sync._fresh_mod_ids(conn, [1], max_age_hours=12) == {1}

    def test_nothing_to_do_returns_zero_without_calling_the_api(self, conn, monkeypatch):
        stamp(conn, 1, hours_ago=1)
        calls: list[int] = []
        assert self._sync(conn, [1], calls, monkeypatch) == 0
        assert calls == []


def test_migration_adds_last_synced_at(tmp_path):
    from core.db.db import init_schema, run_migrations

    db = tmp_path / "m.db"
    c = sqlite3.connect(db)
    try:
        init_schema(c)
        run_migrations(c)
        run_migrations(c)  # idempotent
        cols = [r[1] for r in c.execute("PRAGMA table_info(mods)")]
        assert cols.count("last_synced_at") == 1
    finally:
        c.close()

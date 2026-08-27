"""Activity history, and operating on many mods at once.

History exists because every action reported itself in a toast that was gone
four seconds later. "Did that apply?" had no answer short of reading
backend.log, which is a developer artifact.

Bulk operations exist because a 200-mod library could only be worked one card at
a time — and each activation triggers a conflict rebuild, which is the expensive
part. Batching that rebuild is the whole point, so the tests check it happens
once rather than per mod.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

import core.api.server as server
from core.api.dependencies import invalidate_connection_pool


@pytest.fixture()
def env(monkeypatch, tmp_path):
    from core.db.db import init_schema, run_migrations

    invalidate_connection_pool()
    db_path = tmp_path / "mods.db"
    conn = sqlite3.connect(str(db_path))
    init_schema(conn)
    run_migrations(conn)
    for dl_id, name in ((1, "Rogue"), (2, "Magik"), (3, "Luna")):
        conn.execute(
            "INSERT INTO local_downloads(path, id, name, mod_id, contents, active_paks) "
            "VALUES(?, ?, ?, NULL, ?, '[]')",
            (f"{name}.zip", dl_id, name, json.dumps([f"{name}_P.pak"])),
        )
        conn.execute(
            "INSERT OR REPLACE INTO mods(mod_id, game, name) VALUES(?, 'marvelrivals', ?)",
            (-dl_id, name),
        )
    conn.commit()
    conn.close()

    import core.config.settings as settings_mod

    monkeypatch.setattr(
        settings_mod,
        "SETTINGS",
        settings_mod.replace(settings_mod.SETTINGS, data_dir=tmp_path),
    )
    yield {"db": db_path}
    invalidate_connection_pool()


class TestActivityHistory:
    def test_an_entry_can_be_recorded_and_read_back(self, env):
        server._log_activity("activated", "Enabled Rogue", "1 file")
        entries = server.list_activity()["entries"]
        assert len(entries) == 1
        assert entries[0]["summary"] == "Enabled Rogue"
        assert entries[0]["kind"] == "activated"
        assert entries[0]["detail"] == "1 file"

    def test_newest_first(self, env):
        for i in range(3):
            server._log_activity("activated", f"Action {i}")
        assert [e["summary"] for e in server.list_activity()["entries"]] == [
            "Action 2",
            "Action 1",
            "Action 0",
        ]

    def test_it_never_raises_when_the_table_is_missing(self, env):
        """It is called from inside operations that already succeeded — a
        failure to write history must not turn those into an error."""
        conn = sqlite3.connect(str(env["db"]))
        conn.execute("DROP TABLE activity_log")
        conn.commit()
        conn.close()
        invalidate_connection_pool()

        server._log_activity("activated", "should not explode")  # must not raise
        assert server.list_activity() == {"ok": True, "entries": [], "count": 0}

    def test_old_entries_are_pruned(self, env, monkeypatch):
        monkeypatch.setattr(server, "_ACTIVITY_KEEP", 5)
        for i in range(12):
            server._log_activity("activated", f"Action {i}")
        entries = server.list_activity()["entries"]
        assert len(entries) <= 6, f"kept {len(entries)}"
        assert entries[0]["summary"] == "Action 11"

    def test_clearing_empties_it(self, env):
        server._log_activity("activated", "Enabled Rogue")
        assert server.clear_activity()["removed"] == 1
        assert server.list_activity()["count"] == 0

    def test_the_limit_is_capped(self, env):
        for i in range(5):
            server._log_activity("activated", f"Action {i}")
        assert server.list_activity(limit=2)["count"] == 2
        # A silly value must not become a silly query.
        assert server.list_activity(limit=100000)["count"] == 5


class TestBulkActivate:
    @staticmethod
    def _patch(monkeypatch, calls, rebuilds):
        monkeypatch.setattr(
            server,
            "set_active_paks",
            lambda dl_id, payload: calls.append((dl_id, payload)),
        )
        monkeypatch.setattr(
            server,
            "_safe_rebuild_conflicts",
            lambda *a, **k: rebuilds.append(k.get("purpose")),
        )

    def test_it_enables_every_selected_mod(self, env, monkeypatch):
        calls, rebuilds = [], []
        self._patch(monkeypatch, calls, rebuilds)

        result = server.bulk_activate_downloads(
            server.BulkActivatePayload(download_ids=[1, 2, 3], activate=True)
        )
        assert result["changed"] == 3
        assert sorted(c[0] for c in calls) == [1, 2, 3]
        assert calls[0][1]["active_paks"] == ["Rogue_P.pak"]

    def test_the_conflict_rebuild_happens_once_for_the_whole_batch(
        self, env, monkeypatch
    ):
        """The reason this endpoint exists: rebuilding per mod is what made a
        40-mod selection take minutes."""
        calls, rebuilds = [], []
        self._patch(monkeypatch, calls, rebuilds)

        server.bulk_activate_downloads(
            server.BulkActivatePayload(download_ids=[1, 2, 3], activate=True)
        )
        assert rebuilds == ["bulk_activate"]
        for _dl_id, payload in calls:
            assert payload["rebuild_conflicts"] is False

    def test_disabling_asks_for_an_empty_selection(self, env, monkeypatch):
        calls, rebuilds = [], []
        self._patch(monkeypatch, calls, rebuilds)
        conn = sqlite3.connect(str(env["db"]))
        conn.execute("UPDATE local_downloads SET active_paks = ?", (json.dumps(["Rogue_P.pak"]),))
        conn.commit()
        conn.close()

        server.bulk_activate_downloads(
            server.BulkActivatePayload(download_ids=[1], activate=False)
        )
        assert calls[0][1]["active_paks"] == []

    def test_mods_already_in_that_state_are_skipped_not_reapplied(self, env, monkeypatch):
        calls, rebuilds = [], []
        self._patch(monkeypatch, calls, rebuilds)

        result = server.bulk_activate_downloads(
            server.BulkActivatePayload(download_ids=[1, 2, 3], activate=False)
        )
        # Nothing was active, so disabling is a no-op for all three.
        assert result["skipped"] == 3
        assert calls == []
        assert rebuilds == [], "nothing changed, so nothing to rebuild"

    def test_hidden_files_are_not_enabled(self, env, monkeypatch):
        """A file the user removed must not come back through a bulk enable."""
        calls, rebuilds = [], []
        self._patch(monkeypatch, calls, rebuilds)
        conn = sqlite3.connect(str(env["db"]))
        conn.execute(
            "INSERT INTO mod_hidden_files (download_id, pak_name, hidden_at) "
            "VALUES (1, 'Rogue_P.pak', '2026-01-01T00:00:00+00:00')"
        )
        conn.commit()
        conn.close()

        result = server.bulk_activate_downloads(
            server.BulkActivatePayload(download_ids=[1], activate=True)
        )
        # Its only pak is hidden, so the wanted state is empty — same as now.
        assert result["changed"] == 0
        assert calls == []

    def test_one_broken_mod_does_not_abort_the_rest(self, env, monkeypatch):
        from fastapi import HTTPException

        rebuilds = []
        seen = []

        def flaky(dl_id, payload):
            seen.append(dl_id)
            if dl_id == 2:
                raise HTTPException(status_code=404, detail="gone")

        monkeypatch.setattr(server, "set_active_paks", flaky)
        monkeypatch.setattr(
            server, "_safe_rebuild_conflicts", lambda *a, **k: rebuilds.append(1)
        )

        result = server.bulk_activate_downloads(
            server.BulkActivatePayload(download_ids=[1, 2, 3], activate=True)
        )
        assert result["changed"] == 2
        assert result["failed"] == 1
        assert sorted(seen) == [1, 2, 3]

    def test_an_unknown_id_is_counted_not_fatal(self, env, monkeypatch):
        calls, rebuilds = [], []
        self._patch(monkeypatch, calls, rebuilds)
        result = server.bulk_activate_downloads(
            server.BulkActivatePayload(download_ids=[1, 99999], activate=True)
        )
        assert result["changed"] == 1
        assert result["failed"] == 1

    def test_an_empty_selection_is_rejected(self, env):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            server.bulk_activate_downloads(
                server.BulkActivatePayload(download_ids=[], activate=True)
            )
        assert exc.value.status_code == 400

    def test_it_is_recorded_in_the_history(self, env, monkeypatch):
        calls, rebuilds = [], []
        self._patch(monkeypatch, calls, rebuilds)
        server.bulk_activate_downloads(
            server.BulkActivatePayload(download_ids=[1, 2], activate=True)
        )
        entries = server.list_activity()["entries"]
        assert entries[0]["summary"] == "Enabled 2 mod(s)"


class TestBulkTag:
    def test_it_tags_every_selected_mod(self, env):
        result = server.bulk_tag_mods(
            server.BulkTagPayload(mod_ids=[-1, -2, -3], tag="favourites")
        )
        assert result["added"] == 3
        conn = sqlite3.connect(str(env["db"]))
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM mod_custom_tags WHERE tag = 'favourites'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert n == 3

    def test_a_mod_that_already_has_it_is_skipped(self, env):
        server.bulk_tag_mods(server.BulkTagPayload(mod_ids=[-1], tag="pvp"))
        result = server.bulk_tag_mods(
            server.BulkTagPayload(mod_ids=[-1, -2], tag="pvp")
        )
        assert result["added"] == 1
        assert result["skipped"] == 1

    def test_matching_ignores_case(self, env):
        server.bulk_tag_mods(server.BulkTagPayload(mod_ids=[-1], tag="PvP"))
        result = server.bulk_tag_mods(server.BulkTagPayload(mod_ids=[-1], tag="pvp"))
        assert result["skipped"] == 1

    def test_a_blank_tag_is_rejected(self, env):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            server.bulk_tag_mods(server.BulkTagPayload(mod_ids=[-1], tag="  "))
        assert exc.value.status_code == 400

    def test_an_empty_selection_is_rejected(self, env):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            server.bulk_tag_mods(server.BulkTagPayload(mod_ids=[], tag="x"))
        assert exc.value.status_code == 400


def test_endpoints_are_registered():
    paths = {getattr(r, "path", None) for r in server.app.routes}
    assert "/api/activity" in paths
    assert "/api/activity/clear" in paths
    assert "/api/local_downloads/bulk-activate" in paths
    assert "/api/mods/bulk-tag" in paths


def test_migration_creates_the_table(tmp_path):
    from core.db.db import init_schema, run_migrations

    db = tmp_path / "m.db"
    conn = sqlite3.connect(db)
    try:
        init_schema(conn)
        run_migrations(conn)
        run_migrations(conn)  # idempotent
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "activity_log" in tables
    finally:
        conn.close()

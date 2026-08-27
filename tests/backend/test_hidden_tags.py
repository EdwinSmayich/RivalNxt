"""Auto-detected tags must be removable.

Tags on a mod come from two sources: rows the user created in mod_custom_tags,
and tags derived from Nexus metadata / pak extraction. Only the first kind could
ever be removed, so a wrong character or skin tag from extraction was stuck on
the mod forever.

Deleting a derived tag at its source does not stick — extraction recomputes it
and a Nexus sync overwrites it — so a suppression is recorded instead and the
read paths filter against it.
"""
from __future__ import annotations

import sqlite3

import pytest

from core.api import server


@pytest.fixture()
def cur(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.execute(
        "CREATE TABLE mod_hidden_tags ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, mod_id INTEGER NOT NULL, "
        "tag TEXT NOT NULL COLLATE NOCASE, "
        "hidden_at TEXT NOT NULL DEFAULT (datetime('now')), UNIQUE(mod_id, tag))"
    )
    yield conn.cursor()
    conn.close()


def hide(cur, mod_id: int, tag: str) -> None:
    cur.execute("INSERT OR IGNORE INTO mod_hidden_tags (mod_id, tag) VALUES (?,?)", (mod_id, tag))


class TestWithoutHiddenTags:
    def test_passes_everything_through_when_nothing_is_hidden(self, cur):
        tags = ["Magik", "Skin", "4K"]
        assert server._without_hidden_tags(cur, 1, tags) == tags

    def test_removes_a_hidden_tag(self, cur):
        hide(cur, 1, "Magik")
        assert server._without_hidden_tags(cur, 1, ["Magik", "Skin"]) == ["Skin"]

    def test_matching_ignores_case_and_padding(self, cur):
        # The stored tag and the derived one rarely agree on casing.
        hide(cur, 1, "magik")
        assert server._without_hidden_tags(cur, 1, ["  MAGIK  ", "Skin"]) == ["Skin"]

    def test_suppression_is_scoped_to_one_mod(self, cur):
        hide(cur, 1, "Magik")
        assert server._without_hidden_tags(cur, 2, ["Magik"]) == ["Magik"]

    def test_works_for_local_mods_addressed_by_negative_id(self, cur):
        # Local mods have no row in `mods`, which is why the table has no FK.
        hide(cur, -45, "Local")
        assert server._without_hidden_tags(cur, -45, ["Local", "Keep"]) == ["Keep"]

    def test_empty_input_short_circuits(self, cur):
        assert server._without_hidden_tags(cur, 1, []) == []

    def test_a_missing_table_never_breaks_the_mod_list(self, tmp_path):
        """Filtering is best-effort: a query failure must not 500 the mod list."""
        conn = sqlite3.connect(tmp_path / "empty.db")
        try:
            tags = ["Magik"]
            assert server._without_hidden_tags(conn.cursor(), 1, tags) == tags
        finally:
            conn.close()

    def test_hiding_every_tag_yields_an_empty_list(self, cur):
        hide(cur, 1, "Magik")
        hide(cur, 1, "Skin")
        assert server._without_hidden_tags(cur, 1, ["Magik", "Skin"]) == []

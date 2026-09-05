"""Guessing which Nexus mod a download is, and protecting a chosen preview.

Assigning a mod id meant reading the number off the website and typing it in.
The download already carries two usable signals — its file name, which authors
derive from the mod title, and whatever character tags exist for it.

The hard part is the name. A download the app has renamed looks like
``BodyReshape_JubileeMidnightMutant_Base_11019_1_2026-07-17T20-04Z_e3jCYfIEI``,
and searching that verbatim matches nothing at all.
"""
from __future__ import annotations

import sqlite3

import pytest

import core.api.server as server
from core.api.dependencies import invalidate_connection_pool


class TestTitleWords:
    """What survives cleaning is what gets searched."""

    def test_a_renamed_download_reduces_to_its_title(self):
        assert (
            server._title_words(
                "BodyReshape_JubileeMidnightMutant_Base_11019_1_2026-07-17T20-04Z_e3jCYfIEI"
            )
            == "Body Reshape Jubilee Midnight Mutant"
        )

    def test_the_random_suffix_does_not_survive_camelcase_splitting(self):
        """Splitting before filtering turned "e3jCYfIEI" into "CYf IEI", and
        those two halves have no digits, so they sailed through the filter and
        poisoned every search."""
        out = server._title_words("Thing_e3jCYfIEI")
        assert "CYf" not in out and "IEI" not in out

    def test_ids_versions_and_timestamps_are_dropped(self):
        out = server._title_words("Maskless_Malice_Remesh_2811_1.0_2026-07-16T17-02Z_8nhyujCzj")
        assert out == "Maskless Malice Remesh"

    def test_parenthetical_asides_go(self):
        assert server._title_words("The Ting (support+content)") == "The Ting"

    def test_packaging_words_go(self):
        assert server._title_words("lunasnow-abyssalglow-symbiote-5399-1.0-1784607682") == (
            "lunasnow abyssalglow symbiote"
        )

    def test_it_falls_back_to_the_file_name(self):
        assert server._title_words("", "some/path/Thicc_Luna_Snow.zip") == "Thicc Luna Snow"

    def test_a_name_of_pure_noise_yields_nothing_rather_than_junk(self):
        assert server._title_words("11019_1_2026-07-17T20-04Z") == ""


@pytest.fixture()
def env(monkeypatch, tmp_path):
    from core.db.db import init_schema, run_migrations

    invalidate_connection_pool()
    db_path = tmp_path / "mods.db"
    conn = sqlite3.connect(str(db_path))
    init_schema(conn)
    run_migrations(conn)
    conn.execute(
        "INSERT INTO local_downloads(path, id, name, mod_id, contents, active_paks) "
        "VALUES('x.zip', 1, 'Body Reshape Jubilee Midnight Mutant', 11019, '[]', '[]')"
    )
    conn.execute(
        "INSERT INTO local_downloads(path, id, name, mod_id, contents, active_paks) "
        "VALUES('y.zip', 2, '11019_1_2026-07-17T20-04Z', NULL, '[]', '[]')"
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


class TestSuggestions:
    @staticmethod
    def _stub(monkeypatch, captured):
        def fake_search(**kwargs):
            captured.append(kwargs["query"])
            return (
                [
                    {
                        "modId": 11019,
                        "name": "Body Reshape Jubilee Midnight Mutant",
                        "author": "Someone",
                        "uploader": {"name": "Someone", "memberId": 1},
                        "pictureUrl": "https://static/p.png",
                        "thumbnailUrl": "https://static/t.png",
                        "adult": False,
                        "game": {"domainName": "marvelrivals"},
                    }
                ],
                1,
            )

        monkeypatch.setattr("core.nexus.graphql.search_mods", fake_search)
        monkeypatch.setattr("core.nexus.nexus_api.get_api_key", lambda *a, **k: "key")

    def test_it_searches_the_cleaned_title(self, env, monkeypatch):
        queries: list = []
        self._stub(monkeypatch, queries)
        result = server.suggest_mod_ids(1)
        assert queries[0] == "Body Reshape Jubilee Midnight Mutant"
        assert result["suggestions"][0]["modId"] == 11019

    def test_it_reports_the_id_already_assigned(self, env, monkeypatch):
        self._stub(monkeypatch, [])
        assert server.suggest_mod_ids(1)["currentModId"] == 11019

    def test_tags_are_used_when_the_name_is_useless(self, env, monkeypatch):
        """A download that is all timestamp has nothing else to go on."""
        conn = sqlite3.connect(str(env["db"]))
        conn.execute(
            "INSERT INTO mod_custom_tags (mod_id, tag, added_at) VALUES (-2, 'jubilee', '')"
        )
        conn.commit()
        conn.close()

        queries: list = []
        self._stub(monkeypatch, queries)
        server.suggest_mod_ids(2)
        assert "jubilee" in queries[0]

    def test_tags_of_a_linked_download_are_found_too(self, env, monkeypatch):
        """Tags sit under the real mod id once linked, not the negated one."""
        conn = sqlite3.connect(str(env["db"]))
        conn.execute(
            "INSERT INTO mod_custom_tags (mod_id, tag, added_at) VALUES (11019, 'jubilee', '')"
        )
        conn.commit()
        conn.close()

        queries: list = []
        self._stub(monkeypatch, queries)
        server.suggest_mod_ids(1)
        assert any("jubilee" in q for q in queries), queries

    def test_duplicates_across_attempts_appear_once(self, env, monkeypatch):
        self._stub(monkeypatch, [])
        result = server.suggest_mod_ids(1, count=8)
        ids = [s["modId"] for s in result["suggestions"]]
        assert len(ids) == len(set(ids))

    def test_an_unknown_download_is_a_404(self, env):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            server.suggest_mod_ids(9999)
        assert exc.value.status_code == 404


class TestAChosenImageIsNotOverwritten:
    """A metadata sync must not silently replace the artwork on screen.

    The card shows the Nexus picture unless a custom image is explicitly
    starred, so storing picture_url used to swap out whatever the user was
    looking at — on every sync, not just the first.
    """

    def test_an_existing_image_becomes_the_choice(self, env):
        from core.db.db import upsert_mod_info

        conn = sqlite3.connect(str(env["db"]))
        try:
            conn.execute(
                "INSERT INTO mods(mod_id, game, name) VALUES(500, 'marvelrivals', 'M')"
            )
            conn.execute(
                "INSERT INTO mod_custom_images (mod_id, image_data, filename, mime_type) "
                "VALUES (500, 'AAAA', 'mine.png', 'image/png')"
            )
            conn.commit()

            upsert_mod_info(
                conn, game="marvelrivals", mod_id=500, mod_info_status=200,
                mod_info={"name": "M", "picture_url": "https://static/new.png"},
            )
            starred = conn.execute(
                "SELECT is_preview FROM mod_custom_images WHERE mod_id = 500"
            ).fetchone()[0]
        finally:
            conn.close()
        assert starred == 1

    def test_an_explicit_choice_is_left_alone(self, env):
        from core.db.db import upsert_mod_info

        conn = sqlite3.connect(str(env["db"]))
        try:
            conn.execute(
                "INSERT INTO mods(mod_id, game, name) VALUES(501, 'marvelrivals', 'M')"
            )
            for name, preview in (("first.png", 0), ("chosen.png", 1)):
                conn.execute(
                    "INSERT INTO mod_custom_images (mod_id, image_data, filename, mime_type, is_preview) "
                    "VALUES (501, 'AAAA', ?, 'image/png', ?)",
                    (name, preview),
                )
            conn.commit()

            upsert_mod_info(
                conn, game="marvelrivals", mod_id=501, mod_info_status=200,
                mod_info={"name": "M", "picture_url": "https://static/new.png"},
            )
            rows = dict(
                conn.execute(
                    "SELECT filename, is_preview FROM mod_custom_images WHERE mod_id = 501"
                ).fetchall()
            )
        finally:
            conn.close()
        assert rows["chosen.png"] == 1
        assert rows["first.png"] == 0

    def test_a_mod_with_no_images_still_shows_the_nexus_picture(self, env):
        """Nothing to protect there — the picture is all it has."""
        from core.db.db import upsert_mod_info

        conn = sqlite3.connect(str(env["db"]))
        try:
            conn.execute(
                "INSERT INTO mods(mod_id, game, name) VALUES(502, 'marvelrivals', 'M')"
            )
            conn.commit()
            upsert_mod_info(
                conn, game="marvelrivals", mod_id=502, mod_info_status=200,
                mod_info={"name": "M", "picture_url": "https://static/new.png"},
            )
            n = conn.execute(
                "SELECT COUNT(*) FROM mod_custom_images WHERE mod_id = 502"
            ).fetchone()[0]
            url = conn.execute(
                "SELECT picture_url FROM mods WHERE mod_id = 502"
            ).fetchone()[0]
        finally:
            conn.close()
        assert n == 0
        assert url == "https://static/new.png"


def test_endpoint_is_registered():
    paths = {getattr(r, "path", None) for r in server.app.routes}
    assert "/api/local_downloads/{download_id}/mod-id-suggestions" in paths

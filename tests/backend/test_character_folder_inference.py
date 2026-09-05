"""A mod the user tagged by hand must still get filed into a folder.

Activation picks the ~mods subfolder from an inferred character tag. It read the
extracted pak tags and the filename and nothing else, so a non-official mod whose
character could not be detected automatically landed loose at the root of ~mods —
even after the user tagged it themselves. Their tag is the most deliberate signal
available and was being ignored.
"""
from __future__ import annotations

import sqlite3

import pytest

from core.api import server


@pytest.fixture()
def cur():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE mod_custom_tags (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "mod_id INTEGER NOT NULL, tag TEXT NOT NULL COLLATE NOCASE, "
        "added_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute("CREATE TABLE pak_tags_json (pak_name TEXT PRIMARY KEY, tags_json TEXT)")
    yield conn.cursor()
    conn.close()


def tag(cur, mod_id: int, value: str) -> None:
    cur.execute("INSERT INTO mod_custom_tags (mod_id, tag) VALUES (?, ?)", (mod_id, value))


class TestCustomTagsDecideTheFolder:
    def test_a_hand_added_character_tag_names_the_folder(self, cur):
        tag(cur, -45, "Magik")
        result = server._infer_character_tag(
            cur, name="totally_unrecognisable_file", pak_candidates=["x.pak"], mod_id=-45
        )
        assert result == "Magik"

    def test_local_mods_are_keyed_by_the_negative_download_id(self, cur):
        # A non-official mod has no Nexus id, so its tags live under -(download id).
        tag(cur, -1234, "Loki")
        assert server._infer_character_tag(
            cur, name="mod", pak_candidates=[], mod_id=-1234
        ) == "Loki"

    def test_a_category_tag_never_becomes_a_folder(self, cur):
        # "4K" or "NSFW" must not turn into a directory name.
        for category in sorted(server._KNOWN_CATEGORIES)[:3]:
            cur.execute("DELETE FROM mod_custom_tags")
            tag(cur, -7, category)
            assert server._infer_character_tag(
                cur, name="mod", pak_candidates=[], mod_id=-7
            ) != category

    def test_without_a_mod_id_behaviour_is_unchanged(self, cur):
        tag(cur, -45, "Magik")
        # Callers that pass no id must not accidentally pick up another mod's tag.
        assert server._infer_character_tag(
            cur, name="mod", pak_candidates=[], mod_id=None
        ) is None

    def test_another_mods_tag_is_not_used(self, cur):
        tag(cur, -45, "Magik")
        assert server._infer_character_tag(
            cur, name="mod", pak_candidates=[], mod_id=-99
        ) is None

    def test_missing_table_does_not_break_activation(self):
        """Inference is best-effort; a query failure must not stop a mod enabling."""
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE pak_tags_json (pak_name TEXT PRIMARY KEY, tags_json TEXT)")
        try:
            assert server._infer_character_tag(
                conn.cursor(), name="mod", pak_candidates=[], mod_id=-1
            ) is None
        finally:
            conn.close()

    def test_extracted_tags_still_work_when_there_is_no_custom_tag(self, cur):
        import json

        cur.execute(
            "INSERT INTO pak_tags_json (pak_name, tags_json) VALUES (?, ?)",
            ("thing.pak", json.dumps(["Magik"])),
        )
        assert server._infer_character_tag(
            cur, name="thing", pak_candidates=["thing.pak"], mod_id=-5
        ) == "Magik"


class TestSkinNamesResolveToCharacters:
    """Mod archives are named after the SKIN, not the hero.

    "LunaMirae2099", "FeliciaUrbanPredator", "ElsaYoungBlood" contain no
    canonical character name, so the name heuristic found nothing and those mods
    stayed loose at the root of ~mods. The skins table already maps every skin to
    its character, which answers this directly.
    """

    @pytest.fixture()
    def skinned(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE characters (character_id TEXT PRIMARY KEY, name TEXT)")
        conn.execute(
            "CREATE TABLE skins (skin_id TEXT PRIMARY KEY, character_id TEXT, "
            "variant TEXT, name TEXT)"
        )
        conn.execute("CREATE TABLE mod_custom_tags (id INTEGER PRIMARY KEY, mod_id INTEGER, tag TEXT, added_at TEXT)")
        conn.execute("CREATE TABLE pak_tags_json (pak_name TEXT PRIMARY KEY, tags_json TEXT)")
        rows = [
            ("1049", "Luna Snow", "1049500", "mirae 2099"),
            ("1050", "BLACK CAT", "1050500", "urban predator"),
            ("1051", "ELSA BLOODSTONE", "1051500", "young blood"),
            ("1052", "Someone Else", "1052001", "default"),
        ]
        for char_id, char_name, skin_id, skin_name in rows:
            conn.execute("INSERT OR IGNORE INTO characters VALUES (?,?)", (char_id, char_name))
            conn.execute("INSERT INTO skins VALUES (?,?,?,?)", (skin_id, char_id, "500", skin_name))
        conn.commit()
        server._SKIN_INDEX = None  # the index is cached per process
        yield conn.cursor()
        server._SKIN_INDEX = None
        conn.close()

    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("BodyReshape LunaMirae2099 Alt Free", "Luna Snow"),
            ("BodyReshape_FeliciaUrbanPredator_Alt18", "BLACK CAT"),
            ("BodyReshape ElsaYoungBlood Addons1B", "ELSA BLOODSTONE"),
        ],
    )
    def test_the_real_filenames_from_the_users_mods_folder(self, skinned, filename, expected):
        assert server._character_from_skin_name(skinned, filename) == expected

    def test_matching_ignores_spacing_and_case(self, skinned):
        assert server._character_from_skin_name(skinned, "luna_MIRAE 2099") == "Luna Snow"

    def test_generic_skin_names_never_identify_anyone(self, skinned):
        # "default" exists for all 82 characters; matching it would file a mod
        # under whichever row came back first.
        assert server._character_from_skin_name(skinned, "some default mod") is None

    def test_an_unrelated_name_resolves_to_nothing(self, skinned):
        assert server._character_from_skin_name(skinned, "random_texture_pack") is None

    def test_empty_input_is_safe(self, skinned):
        assert server._character_from_skin_name(skinned, "") is None

    def test_inference_uses_it_as_a_fallback(self, skinned):
        assert server._infer_character_tag(
            skinned, name="BodyReshape LunaMirae2099 Alt", pak_candidates=[], mod_id=None
        ) == "Luna Snow"

    def test_a_custom_tag_still_wins_over_the_skin_guess(self, skinned):
        skinned.execute(
            "INSERT INTO mod_custom_tags (mod_id, tag) VALUES (?, ?)", (-5, "Magik")
        )
        # The user's own tag is the most deliberate signal and must not be
        # overridden by a filename guess.
        assert server._infer_character_tag(
            skinned, name="BodyReshape LunaMirae2099", pak_candidates=[], mod_id=-5
        ) == "Magik"

    def test_missing_character_tables_do_not_break_activation(self):
        conn = sqlite3.connect(":memory:")
        server._SKIN_INDEX = None
        try:
            assert server._character_from_skin_name(conn.cursor(), "LunaMirae2099") is None
        finally:
            server._SKIN_INDEX = None
            conn.close()


class TestPaksNestedInsideTheirArchive:
    """A pak stored in a subfolder of its archive must still find its tags.

    local_downloads.active_paks keeps the path a pak has *inside the archive*,
    as in the NESTED constant below, and set_active_paks passes those straight
    to _infer_character_tag. pak_tags_json is keyed by the bare filename, so
    every one of those lookups missed: 73 of 115 active downloads in the library
    where this was found. No tags meant no character, so inference fell back to
    matching hero names against the download name -- which cannot help when the
    mod is not named after its hero. The mod was filed at the root of ~mods and
    nothing moved it afterwards.

    A hand-written tag was the only thing that worked, because custom tags are
    read before this lookup -- which is exactly what was reported: "until you
    delete the tag and add it again, sorting does not work".
    """

    NESTED = "LunaSnow_AbyssalGlow_Symbiote/LunaSnow_AbyssalGlow_Symbiote_9999999_P.pak"

    def test_an_archive_relative_path_finds_the_tags(self, cur):
        cur.execute(
            "INSERT INTO pak_tags_json (pak_name, tags_json) VALUES (?, ?)",
            ("LunaSnow_AbyssalGlow_Symbiote_9999999_P.pak", '["Luna Snow", "abyssal glow,material"]'),
        )
        assert server._infer_character_tag(
            cur, name="makeup file", pak_candidates=[self.NESTED], mod_id=5399
        ) == "Luna Snow"

    def test_a_backslash_separated_path_works_too(self, cur):
        cur.execute(
            "INSERT INTO pak_tags_json (pak_name, tags_json) VALUES (?, ?)",
            ("LunaSnow_AbyssalGlow_Symbiote_9999999_P.pak", '["Luna Snow"]'),
        )
        windows_style = "LunaSnow_AbyssalGlow_Symbiote\\LunaSnow_AbyssalGlow_Symbiote_9999999_P.pak"
        assert server._infer_character_tag(
            cur, name="makeup file", pak_candidates=[windows_style], mod_id=5399
        ) == "Luna Snow"

    def test_a_bare_filename_is_unaffected(self, cur):
        """The 42 downloads whose archives keep paks at the top must not regress."""
        cur.execute(
            "INSERT INTO pak_tags_json (pak_name, tags_json) VALUES (?, ?)",
            ("MakeUp_NolaehaneunManyeo_LunaSnow_9999999_P.pak", '["Luna Snow"]'),
        )
        assert server._infer_character_tag(
            cur, name="makeup-mod", pak_candidates=["MakeUp_NolaehaneunManyeo_LunaSnow_9999999_P.pak"], mod_id=99
        ) == "Luna Snow"

    def test_the_utoc_fallback_also_uses_the_bare_name(self, cur):
        """Only the .utoc row exists; the nested .pak path must still reach it."""
        cur.execute(
            "INSERT INTO pak_tags_json (pak_name, tags_json) VALUES (?, ?)",
            ("LunaSnow_AbyssalGlow_Symbiote_9999999_P.utoc", '["Luna Snow"]'),
        )
        assert server._infer_character_tag(
            cur, name="makeup file", pak_candidates=[self.NESTED], mod_id=5399
        ) == "Luna Snow"

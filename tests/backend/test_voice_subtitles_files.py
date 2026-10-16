"""Subtitle mods and the combined file the game reads."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from pylocres import LocresFile

from core.voice_subtitles import subtitles as subs
from core.voice_subtitles.discover import COMBINED_NAME, is_generated
from voice_subtitles_fakes import AES, NS, FakeGame, key


@pytest.mark.parametrize("heard,game,left", [
    ("Sorry, Peni. Had to make you cum.", "", True),
    ("Nice shot.", "Peni! Great work.", False),            # not sexual: translated
    ("Wanna fuck after this?", "Peni Parker power!", True),  # answers a line about Peni
    ("Blimey! These goats are hung!", "", True),
    ("Enemies! They are hung as a horse!", "", False),       # a simile
    ("I'll fuck you like an animal.", "", False),
    ("These tentacles fuck me so good!", "", False),         # Namor's monsters, not animals
    ("Sorry, Squirrel Girl. Only I can ride that huge cock.", "", False),
    ("Let's take that horse dildo!", "", False),
    ("Rocket's dick just came and died!", "", False),        # a grown, talking hero
    ("Jeff... I'm sorry, luv.", "", False),
    ("Ooh, your cock is much bigger than my little Jeff.", "", True),
])
def test_what_keeps_the_games_subtitle(heard, game, left):
    assert subs.leave_as_is(heard, game) is left


def make_work(tmp_path: Path) -> Path:
    work = tmp_path / "voice-mods" / "1031001-abc"
    work.mkdir(parents=True)
    rows = [
        {"namespace": NS, "key": key("1"), "line": "1", "en": "Hello!", "heard": "Hi there, darling.", "status": "changed"},
        {"namespace": NS, "key": key("2"), "line": "2", "en": "Bye!", "heard": "", "status": "silent"},
        {"namespace": NS, "key": key("3"), "line": "3", "en": "Go!", "heard": "Go!", "status": "same"},
        {"namespace": NS, "key": key("4"), "line": "4", "en": "Hm.", "heard": "Sorry, Peni. Had to make you cum.",
         "status": "changed"},
        {"namespace": NS, "key": key("5"), "line": "5", "en": "Yes.", "heard": "Not translated yet.", "status": "changed"},
    ]
    (work / "transcript.json").write_text(json.dumps(rows), encoding="utf-8")
    (work / "map.json").write_text(json.dumps({"hero": "1031", "lines": []}), encoding="utf-8")
    (work / "translation.ru.json").write_text(json.dumps({key("1"): "Привет, милый."}), encoding="utf-8")
    return work


def test_lines_of_a_language(tmp_path):
    work = make_work(tmp_path)
    lines, counts = subs.subtitle_lines(work, "ru")
    assert lines == {NS: {key("1"): "Привет, милый.", key("2"): ""}}
    assert counts == {"subtitled": 1, "silenced": 1, "kept": 1, "missing": 1}


def test_english_subtitles_are_the_words_heard(tmp_path):
    work = make_work(tmp_path)
    lines, counts = subs.subtitle_lines(work, "en")
    assert lines[NS][key("1")] == "Hi there, darling."
    assert lines[NS][key("5")] == "Not translated yet."
    assert counts["missing"] == 0 and counts["kept"] == 1


def test_a_hand_edit_wins(tmp_path):
    work = make_work(tmp_path)
    (work / "edits.ru.json").write_text(json.dumps({key("1"): "Привет!", key("5"): "Ещё нет."}), encoding="utf-8")
    lines, _ = subs.subtitle_lines(work, "ru")
    assert lines[NS][key("1")] == "Привет!" and lines[NS][key("5")] == "Ещё нет."


def test_names():
    archive, pak = subs.subtitle_mod_names("Luna Snow", "LunaVoiceS9Fix_9999999_P.pak", "ru")
    assert archive == "RU Subtitles - Luna Snow - LunaVoiceS9Fix.zip"
    assert pak == "RU_Subtitles_LunaSnow_LunaVoiceS9Fix_9999999_P.pak"
    assert subs.subtitle_mod_names("Storm", "Voice: S9 Fix_9999999_P.pak", "pt-BR")[0] == \
        "PT Subtitles - Storm - Voice  S9 Fix.zip"
    assert is_generated(archive) and is_generated(pak) and is_generated(COMBINED_NAME)
    assert not is_generated("LunaVoiceS9Fix_9999999_P.pak")
    assert not is_generated("FX_Subtitles_Overhaul_P.pak")  # not a language this app writes


def test_every_language_has_its_own_name():
    from core.voice_subtitles.game import LANGUAGES

    archives = {subs.subtitle_mod_names("Storm", "Voice_9999999_P.pak", code)[0] for code in LANGUAGES}
    paks = {subs.subtitle_mod_names("Storm", "Voice_9999999_P.pak", code)[1] for code in LANGUAGES}
    assert len(archives) == len(paks) == len(LANGUAGES)
    assert all(is_generated(name) for name in archives | paks)
    assert subs.subtitle_mod_names("Storm", "Voice_9999999_P.pak", "es-419")[0].startswith("LAS Subtitles - ")
    assert subs.subtitle_mod_names("Storm", "Voice_9999999_P.pak", "es-ES")[0].startswith("ES Subtitles - ")


def test_the_library_knows_the_same_tags():
    # The library's mod cards recognise subtitle mods by these tags too.
    import re

    from core.voice_subtitles.game import LANGUAGE_TAGS

    source = (Path(__file__).resolve().parents[2] / "src" / "lib" / "subtitleMods.ts").read_text(encoding="utf-8")
    tags = re.search(r"const TAGS = \[([^\]]*)\]", source).group(1)
    assert set(re.findall(r'"([A-Z]+)"', tags)) == set(LANGUAGE_TAGS.values())


@pytest.mark.parametrize("culture,language", [
    ("ru", "ru"), ("en-US", "en"), ("zh-CN", "zh-Hans"), ("zh-TW", "zh-Hant"), ("es-MX", "es-419"),
    ("es", "es-ES"), ("pt-PT", "pt-BR"), ("PT-br", "pt-BR"), ("xx", None), ("", None),
])
def test_the_games_culture_names_a_language(culture, language):
    from core.voice_subtitles.game import known_language

    assert known_language(culture) == language


def test_a_subtitle_mod_is_written_and_read_back(tmp_path):
    work = make_work(tmp_path)
    downloads, mods = tmp_path / "downloads", tmp_path / "mods"
    mods.mkdir()
    result = subs.write_subtitle_mod(work, "ru", "Luna Snow", "Voice_9999999_P.pak", downloads, mods, AES)

    assert result["changed"] and result["archive"].exists()
    with zipfile.ZipFile(result["archive"]) as z:
        assert z.namelist() == [result["pak"]]
        (tmp_path / result["pak"]).write_bytes(z.read(result["pak"]))
    data = subs.read_subtitle_mod(tmp_path / result["pak"], AES)
    assert data["language"] == "ru" and data["lines"] == {NS: {key("1"): "Привет, милый.", key("2"): ""}}

    again = subs.write_subtitle_mod(work, "ru", "Luna Snow", "Voice_9999999_P.pak", downloads, mods, AES)
    assert again["changed"] is False


def test_a_copy_switched_on_is_kept_current(tmp_path):
    work = make_work(tmp_path)
    downloads, mods = tmp_path / "downloads", tmp_path / "mods"
    first = subs.write_subtitle_mod(work, "ru", "Luna Snow", "Voice_9999999_P.pak", downloads, tmp_path / "none", AES)
    (mods / "luna_snow").mkdir(parents=True)
    with zipfile.ZipFile(first["archive"]) as z:
        (mods / "luna_snow" / first["pak"]).write_bytes(z.read(first["pak"]))

    (work / "edits.ru.json").write_text(json.dumps({key("1"): "Новый текст."}), encoding="utf-8")
    result = subs.write_subtitle_mod(work, "ru", "Luna Snow", "Voice_9999999_P.pak", downloads, mods, AES)

    assert result["active"] == [mods / "luna_snow" / first["pak"]]
    assert subs.read_subtitle_mod(mods / "luna_snow" / first["pak"], AES)["lines"][NS][key("1")] == "Новый текст."


def test_a_pak_that_is_not_a_subtitle_mod_is_ignored(tmp_path):
    import rivalnxt_pak

    other = tmp_path / "Other_P.pak"
    rivalnxt_pak.write_pak(str(other), [("Marvel/Content/x.uasset", b"x")], aes_key=AES)
    assert subs.read_subtitle_mod(other, AES) is None
    assert subs.read_subtitle_mod(tmp_path / "missing.pak", AES) is None


def fragment(mods: Path, folder: str, name: str, lines: dict, language: str = "ru") -> None:
    import rivalnxt_pak

    (mods / folder).mkdir(parents=True, exist_ok=True)
    payload = {"format": 1, "language": language, "lines": {NS: lines}}
    rivalnxt_pak.write_pak(str(mods / folder / name), [(f"{subs.FRAGMENT_DIR}/{language}/w.json",
                                                        json.dumps(payload).encode())], aes_key=AES)


def combined_text(mods: Path, language: str = "ru") -> dict:
    import rivalnxt_pak

    raw = rivalnxt_pak.read_pak_file(str(mods / COMBINED_NAME), f"Marvel/Content/Localization/Game/{language}/Game.locres",
                                     aes_key=AES)
    path = mods.parent / "check.locres"
    path.write_bytes(bytes(raw))
    lf = LocresFile()
    lf.read(str(path))
    return {k: e.translation for k, e in lf.namespaces[NS].entrys.items()}


def test_the_combined_file_has_every_subtitle_mod_switched_on(tmp_path):
    game = FakeGame(en={}, local={"ru": {key("1"): "Привет!", key("2"): "Пока!", key("3"): "Вперёд!"}})
    mods = tmp_path / "mods"
    fragment(mods, "luna_snow", "RU_Subtitles_A_9999999_P.pak", {key("1"): "Первый"})
    fragment(mods, "storm", "RU_Subtitles_B_9999999_P.pak", {key("1"): "Второй", key("2"): ""})

    totals = subs.build_combined(game, "ru", mods, AES)

    assert totals["mods"] == 2 and totals["subtitled"] == 1 and totals["silenced"] == 1
    # Later names win, as with the game's own mod files.
    assert combined_text(mods) == {key("1"): "Второй", key("2"): "", key("3"): "Вперёд!"}
    # The game's own text, parsed once and cached, is left as the game has it.
    assert game.locres("ru").namespaces[NS].entrys[key("1")].translation == "Привет!"


def test_subtitles_in_another_language_show_too(tmp_path):
    # English subtitles in a game set to Russian: what the voice mod says, untranslated.
    game = FakeGame(en={}, local={"ru": {key("1"): "Привет!", key("2"): "Пока!", key("3"): "Вперёд!"}})
    mods = tmp_path / "mods"
    fragment(mods, "storm", "EN_Subtitles_B_9999999_P.pak", {key("1"): "Hi there", key("3"): "Go go"}, language="en")
    fragment(mods, "luna_snow", "AR_Subtitles_A_9999999_P.pak", {key("2"): "", key("3"): "x"}, language="ar")
    fragment(mods, "storm", "RU_Subtitles_A_9999999_P.pak", {key("1"): "Здравствуй"})

    totals = subs.build_combined(game, "ru", mods, AES)

    assert totals["mods"] == 3 and totals["languages"] == ["ar", "en", "ru"]
    # The game's language wins over the others; among those, the later name.
    assert combined_text(mods) == {key("1"): "Здравствуй", key("2"): "", key("3"): "Go go"}


def test_with_nothing_switched_on_the_combined_file_goes(tmp_path):
    game = FakeGame(en={}, local={"ru": {key("1"): "Привет!"}})
    mods = tmp_path / "mods"
    mods.mkdir()
    (mods / COMBINED_NAME).write_bytes(b"old")
    assert subs.build_combined(game, "ru", mods, AES)["mods"] == 0
    assert not (mods / COMBINED_NAME).exists()


def test_while_the_game_has_it_open(tmp_path, monkeypatch):
    game = FakeGame(en={}, local={"ru": {key("1"): "Привет!"}})
    mods = tmp_path / "mods"
    fragment(mods, "luna_snow", "RU_Subtitles_A_9999999_P.pak", {key("1"): "Первый"})

    def locked(*_a, **_k):
        raise PermissionError("in use")

    monkeypatch.setattr(subs.os, "replace", locked)
    with pytest.raises(subs.GameHasItOpen):
        subs.build_combined(game, "ru", mods, AES)
    assert not list(mods.glob("*.rivalnxt-new"))

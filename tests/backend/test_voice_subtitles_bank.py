"""Which of the game's subtitle lines play which sounds of a voice mod's bank."""
from __future__ import annotations

import json

import pytest

from core.voice_subtitles.bank import Bank, bank_in, fnv1, line_events, map_voice_mod
from voice_subtitles_fakes import HERO, NS, FakeGame, bank, key


def test_fnv1_is_wwise_hash_of_the_lower_cased_name():
    assert fnv1("Play") == fnv1("play")
    assert fnv1("") == 2166136261


def test_an_event_leads_to_its_sounds():
    b = Bank(bank({1: b"one", 2: b"two"}, {"vo_10310001_hello_play": [1, 2], "vo_10310002_bye_play": [2]}))
    assert b.event_sounds("vo_10310001_hello_play") == {1, 2}
    assert b.event_sounds("vo_10310002_bye_play") == {2}
    assert b.event_sounds("vo_99999999_nothing_play") == set()


def test_sounds_inside_a_container_are_found():
    b = Bank(bank({7: b"x"}, {"vo_10310001_hello_play": [7]}, via_container=True))
    assert b.event_sounds("vo_10310001_hello_play") == {7}


def test_a_file_that_is_not_a_bank_is_refused():
    with pytest.raises(ValueError):
        Bank(b"RIFF....")


def test_events_are_taken_for_the_hero_only():
    paths = [
        "Marvel/Content/WwiseAudio/Events/Characters/1031/Default/vocal/vo_10310001_hello_play.uasset",
        "Marvel/Content/WwiseAudio/Events/Characters/1016/Default/vocal/vo_10160001_hi_play.uasset",
        "Marvel/Content/WwiseAudio/Events/Characters/1031/Default/vocal/not_a_line.uasset",
    ]
    assert line_events(paths, "1031") == {"10310001": ["vo_10310001_hello_play"]}


def test_the_bank_file_is_found_among_a_paks_files():
    assert bank_in(["patched_files", "Marvel/Content/WwiseAudio/English(US)/bnk_vo_1031001.bnk"]).endswith(".bnk")
    assert bank_in(["Marvel/Content/Marvel/Characters/1031/x.uasset"]) is None


def test_mapping_writes_each_lines_sounds(tmp_path):
    game = FakeGame(
        en={key("10310001"): "Hello!", key("10310002"): "Bye!", key("10310003"): "Not in the mod."},
        events=[f"Marvel/Content/WwiseAudio/Events/Characters/{HERO}/Default/vocal/vo_10310001_hello_play.uasset",
                f"Marvel/Content/WwiseAudio/Events/Characters/{HERO}/Default/vocal/vo_10310002_bye_play.uasset"],
    )
    data = bank({11: b"hello-sound", 22: b"bye-sound"},
                {"vo_10310001_hello_play": [11], "vo_10310002_bye_play": [22]})

    result = map_voice_mod(f"{HERO}001", data, game, tmp_path, "Voice_9999999_P.pak")

    lines = {line["key"]: line for line in result["lines"]}
    assert lines[key("10310001")]["media"] == [11]
    assert lines[key("10310002")]["media"] == [22]
    assert lines[key("10310003")]["media"] == []
    assert (tmp_path / "wem" / "11.wem").read_bytes() == b"hello-sound"
    assert json.loads((tmp_path / "map.json").read_text(encoding="utf-8"))["namespaces"] == [NS]

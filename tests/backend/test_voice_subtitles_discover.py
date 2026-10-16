"""Finding voice mods in ~mods and in the library's archives."""
from __future__ import annotations

import zipfile

from core.voice_subtitles import discover
from voice_subtitles_fakes import AES, bank, voice_pak


def test_voice_mods_switched_on_and_in_the_library(tmp_path, monkeypatch):
    mods = tmp_path / "mods"
    (mods / "luna_snow").mkdir(parents=True)
    pak = voice_pak(mods / "luna_snow" / "Voice_9999999_P.pak", bank({1: b"a"}, {"vo_10310001_a_play": [1]}))
    # An IoStore mod: its .pak is a stub, not looked into.
    (mods / "luna_snow" / "Skin_9999999_P.pak").write_bytes(b"stub")
    (mods / "luna_snow" / "Skin_9999999_P.utoc").write_bytes(b"toc")

    downloads = tmp_path / "downloads"
    downloads.mkdir()
    variant = voice_pak(tmp_path / "Variant_9999999_P.pak", bank({2: b"b"}, {"vo_10310002_b_play": [2]}))
    archive = downloads / "voice-variants.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.write(pak, "Voice/Voice_9999999_P.pak")              # the same file as the one switched on
        z.write(variant, "Voice/Variant_9999999_P.pak")
        z.writestr("Skin/Body_P.pak", b"stub")
        z.writestr("Skin/Body_P.utoc", b"toc")
    library = [{"id": 7, "name": "Voice Variants", "path": str(archive)}]

    finder = discover.Finder(tmp_path / "voice", AES)
    found = finder.scan(mods, library)

    by_name = {m.name: m for m in found}
    assert set(by_name) == {"Voice_9999999_P.pak", "Variant_9999999_P.pak"}
    assert by_name["Voice_9999999_P.pak"].installed == ["luna_snow/Voice_9999999_P.pak"]
    assert by_name["Voice_9999999_P.pak"].library[0]["download_id"] == 7
    assert by_name["Variant_9999999_P.pak"].installed == []
    assert by_name["Variant_9999999_P.pak"].hero == "1031"
    assert finder.pak_path(by_name["Variant_9999999_P.pak"], mods).exists()  # kept from the archive

    # An archive is opened once: the second look is from the index.
    opened = []
    monkeypatch.setattr("core.utils.archive.extract_member", lambda *a, **k: opened.append(a))
    assert {m.key for m in finder.scan(mods, library)} == {m.key for m in found}
    assert opened == []


def test_generated_files_are_not_voice_mods(tmp_path):
    mods = tmp_path / "mods"
    mods.mkdir()
    voice_pak(mods / "RU_Subtitles_LunaSnow_Voice_9999999_P.pak", bank({1: b"a"}, {"vo_10310001_a_play": [1]}))
    assert discover.Finder(tmp_path / "voice", AES).scan(mods, []) == []

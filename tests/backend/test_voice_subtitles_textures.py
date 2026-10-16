"""Hero portraits out of the game's texture assets."""
from __future__ import annotations

import struct
import sys
import types
from pathlib import Path

from PIL import Image

from core.voice_subtitles.game import Game
from core.voice_subtitles.textures import decode_texture, texture_png

TAG = struct.pack("<I", 0x9E2A83C1)


def texture(fmt: str, width: int, height: int, pixels: bytes) -> bytes:
    """A cooked Texture2D as the game's are laid out: names, then size, format string, the mip, its size."""
    names = b"\x00" * 40 + fmt.encode() + b"\x00" + b"img_squarehead_10310010_avatar\x00"  # the name table
    header = struct.pack("<iii", width, height, 1) + struct.pack("<i", len(fmt) + 1) + fmt.encode() + b"\x00"
    return names + b"\x11" * 20 + header + struct.pack("<iii", 0, 1, 0) + pixels \
        + struct.pack("<iii", width, height, 1) + b"\x00" * 12 + TAG


def red_dxt1(width: int, height: int) -> bytes:
    blocks = ((width + 3) // 4) * ((height + 3) // 4)
    return struct.pack("<HHI", 0xF800, 0x0000, 0) * blocks  # every texel: the first colour, pure red


class TestDecoding:
    def test_block_compressed(self):
        image = decode_texture(texture("PF_DXT1", 6, 5, red_dxt1(6, 5)))
        assert image.size == (6, 5)
        assert image.getpixel((5, 4))[:3] == (255, 0, 0)

    def test_uncompressed(self):
        image = decode_texture(texture("PF_B8G8R8A8", 2, 2, bytes([0, 0, 255, 255]) * 4))
        assert image.size == (2, 2) and image.getpixel((1, 1)) == (255, 0, 0, 255)

    def test_what_it_cannot_read(self, tmp_path):
        assert decode_texture(texture("PF_ASTC_4x4", 4, 4, b"\x00" * 16)) is None
        assert decode_texture(b"no texture here") is None
        cut = texture("PF_DXT1", 8, 8, red_dxt1(8, 8))[:-40]  # the mip's own size is gone
        assert decode_texture(cut) is None
        assert texture_png(cut, tmp_path / "x.png") is False and not (tmp_path / "x.png").exists()


class FakeUnpacker:
    calls = 0

    def unpack_pak(self, pak, out, aes_key=None, force=False, quiet=True, include_patterns=None):
        FakeUnpacker.calls += 1
        folder = Path(out) / "Marvel/Content/Marvel/UI/Textures/HeroPortrait/SquareHeroHead"
        folder.mkdir(parents=True)
        (folder / "img_squarehead_10310010_avatar.uasset").write_bytes(texture("PF_DXT1", 8, 8, red_dxt1(8, 8)))
        (folder / "img_squarehead_10420010_avatar.uasset").write_bytes(b"broken")
        return []


def test_hero_icons_are_read_once_per_game_version(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "rust_ue_tools", types.SimpleNamespace(PyUnpacker=FakeUnpacker))
    paks = tmp_path / "Paks"
    paks.mkdir()
    (paks / "pakchunkHQ-Windows.utoc").write_bytes(b"x")
    game = Game(paks, tmp_path / "cache")

    icon = game.hero_icon("10310010")
    assert icon is not None and Image.open(icon).getpixel((0, 0))[:3] == (255, 0, 0)
    assert game.hero_icon("10420010") is None   # its texture could not be read
    assert game.hero_icon("../../secret") is None
    assert FakeUnpacker.calls == 1

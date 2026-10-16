"""Stand-ins for the game and for voice mods, shared by the voice-subtitle tests."""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Dict, List

from pylocres import Entry, LocresFile, Namespace

from core.voice_subtitles.bank import fnv1

AES = "0x0C263D8C22DCB085894899C3A3796383E9BF9DE0CBFB08C9BF2DEF2E84F29D74"
HERO = "1031"
NS = f"122_HeroVoice_{HERO}_ST"


def key(line: str) -> str:
    return f"{HERO}001_HeroVoice_{line}_Lines"


def locres(lines: Dict[str, str], namespace: str = NS) -> LocresFile:
    lf = LocresFile()
    ns = Namespace(namespace)
    for k, text in lines.items():
        ns.add(Entry(k, text, 0))
    lf.add(ns)
    return lf


class FakeGame:
    """The parts of core.voice_subtitles.game.Game the pipeline uses."""

    def __init__(self, en: Dict[str, str], local: Dict[str, Dict[str, str]] | None = None,
                 events: List[str] | None = None, female: bool = True):
        self._loc = {"en": locres(en)}
        for lang, lines in (local or {}).items():
            self._loc[lang] = locres(lines)
        self._events = events or []
        self.female = female

    def locres(self, language: str):
        if language not in self._loc:
            raise FileNotFoundError(language)
        return self._loc[language]

    def voice_events(self) -> List[str]:
        return self._events

    def hero_is_female(self, hero: str) -> bool:
        return self.female

    def speaker(self, hero: str, language: str):
        return "Luna Snow", self.female

    def english_hero_name(self, hero: str) -> str:
        return "Luna Snow"

    def hero_avatar(self, hero: str) -> str:
        return f"{hero}0010"

    def hero_icon(self, avatar: str):
        return None

    def names(self, language: str) -> Dict[str, str]:
        return {"Luna Snow": "Луна Сноу (a woman)"}


def bank(sounds: Dict[int, bytes], events: Dict[str, List[int]], via_container: bool = False) -> bytes:
    """A Wwise bank where each named event plays the given sounds (through a container if asked)."""
    data, didx = b"", b""
    for media, payload in sounds.items():
        didx += struct.pack("<III", media, len(data), len(payload))
        data += payload
    objects: List[bytes] = []
    next_id = [1000]

    def new_id() -> int:
        next_id[0] += 1
        return next_id[0]

    def obj(kind: int, body: bytes) -> None:
        objects.append(struct.pack("<BI", kind, len(body)) + body)

    for name, medias in events.items():
        sound_ids = []
        for media in medias:
            sid = new_id()
            obj(2, struct.pack("<I", sid) + b"\x00\x00\x00\x00" + b"\x00" + struct.pack("<I", media) + b"\x00" * 8)
            sound_ids.append(sid)
        if via_container:
            cid = new_id()
            obj(5, struct.pack("<I", cid) + b"\x00" * 6 + b"".join(struct.pack("<I", s) for s in sound_ids) + b"\x00" * 4)
            targets = [cid]
        else:
            targets = sound_ids
        action_ids = []
        for target in targets:
            aid = new_id()
            obj(3, struct.pack("<I", aid) + b"\x03\x04" + struct.pack("<I", target) + b"\x00" * 4)
            action_ids.append(aid)
        obj(4, struct.pack("<I", fnv1(name)) + bytes([len(action_ids)]) + b"".join(struct.pack("<I", a) for a in action_ids))
    hirc = struct.pack("<I", len(objects)) + b"".join(objects)

    def section(tag: str, body: bytes) -> bytes:
        return tag.encode("latin-1") + struct.pack("<I", len(body)) + body

    return section("BKHD", b"\x00" * 8) + section("DIDX", didx) + section("DATA", data) + section("HIRC", hirc)


def voice_pak(path: Path, bank_bytes: bytes, bank_id: str = f"{HERO}001") -> Path:
    import rivalnxt_pak

    rivalnxt_pak.write_pak(str(path), [(f"Marvel/Content/WwiseAudio/English(US)/bnk_vo_{bank_id}.bnk", bank_bytes)],
                           aes_key=AES)
    return path

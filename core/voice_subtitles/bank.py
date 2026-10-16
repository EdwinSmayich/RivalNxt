"""A voice mod's Wwise bank: which of the game's subtitle lines play which of its sounds.

A voice mod replaces a hero's sound bank (bnk_vo_<id>.bnk). The game names
each voice event after its subtitle line ("vo_10310078_damaged_01_play"), and
Wwise addresses an event by the FNV-1 hash of its name, so following an
event through the bank's hierarchy (event -> action -> sound or container ->
sound) gives the sounds that play for each subtitle line.
"""
from __future__ import annotations

import json
import re
import struct
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

BANK_NAME = re.compile(r"(?:^|/)bnk_vo_(\d+)\.bnk$", re.IGNORECASE)


def fnv1(name: str) -> int:
    """Wwise's id for a name: 32-bit FNV-1 of the lower-cased name."""
    h = 2166136261
    for byte in name.lower().encode("utf-8"):
        h = (h * 16777619) & 0xFFFFFFFF
        h ^= byte
    return h


def sections(data: bytes) -> Dict[str, bytes]:
    out, pos = {}, 0
    while pos + 8 <= len(data):
        tag = data[pos:pos + 4].decode("latin-1")
        size = struct.unpack_from("<I", data, pos + 4)[0]
        out[tag] = data[pos + 8:pos + 8 + size]
        pos += 8 + size
    return out


def hirc_objects(blob: bytes) -> Dict[int, Tuple[int, bytes]]:
    count = struct.unpack_from("<I", blob, 0)[0]
    pos, objs = 4, {}
    for _ in range(count):
        kind, size = struct.unpack_from("<BI", blob, pos)
        body = blob[pos + 5:pos + 5 + size]
        objs[struct.unpack_from("<I", body, 0)[0]] = (kind, body)
        pos += 5 + size
    return objs


class Bank:
    """A parsed voice bank: its embedded sounds and the events that play them."""

    def __init__(self, data: bytes):
        sec = sections(data)
        if "HIRC" not in sec or "DIDX" not in sec or "DATA" not in sec:
            raise ValueError("not a Wwise sound bank with embedded sounds")
        self.objects = hirc_objects(sec["HIRC"])
        self.sounds: Dict[int, bytes] = {}
        didx, blob = sec["DIDX"], sec["DATA"]
        for i in range(0, len(didx) - 11, 12):
            media, offset, size = struct.unpack_from("<III", didx, i)
            self.sounds[media] = blob[offset:offset + size]

    def _media_of(self, oid: int, depth: int = 0) -> Set[int]:
        if depth > 6 or oid not in self.objects:
            return set()
        kind, body = self.objects[oid]
        if kind == 2:  # Sound: the media id follows the plugin id and stream type
            return {struct.unpack_from("<I", body, 9)[0]}
        found: Set[int] = set()
        if kind in (5, 6, 7, 9):  # random/sequence, switch, blend, ... containers
            for off in range(4, len(body) - 3):
                child = struct.unpack_from("<I", body, off)[0]
                if child in self.objects and self.objects[child][0] == 2:
                    found |= self._media_of(child, depth + 1)
        return found

    def event_sounds(self, event_name: str) -> Set[int]:
        kind, body = self.objects.get(fnv1(event_name), (None, b""))
        if kind != 4 or len(body) < 5:
            return set()
        count = body[4]
        out: Set[int] = set()
        for action in struct.unpack_from(f"<{count}I", body, 5):
            akind, abody = self.objects.get(action, (None, b""))
            if akind == 3 and len(abody) >= 10:
                out |= self._media_of(struct.unpack_from("<I", abody, 6)[0])
        return out & set(self.sounds)


def line_events(event_paths: Iterable[str], hero: str) -> Dict[str, List[str]]:
    """Subtitle line id -> the names of the hero's voice events for it."""
    out: Dict[str, List[str]] = {}
    marker = f"/Characters/{hero}/"
    for path in event_paths:
        path = path.replace("\\", "/")
        if marker not in path:
            continue
        stem = Path(path).stem
        m = re.match(r"vo_(\d{8})_", stem)
        if m:
            out.setdefault(m.group(1), []).append(stem)
    return out


def map_voice_mod(bank_id: str, bank_data: bytes, game, out_dir: Path, source_name: str) -> dict:
    """Write out_dir/map.json and the sounds that subtitle lines play (out_dir/wem/).

    Each line: {namespace, key, line, events, media, en}. Lines whose sound
    is not in this bank ("media" empty) keep the game's subtitle.
    """
    hero = bank_id[:4]
    bank = Bank(bank_data)
    events = line_events(game.voice_events(), hero)
    en = game.locres("en")
    namespaces = [ns for ns in en.namespaces if re.fullmatch(rf"122_HeroVoice_{hero}\d*_ST", ns)]
    lines = []
    for ns in namespaces:
        for key, entry in en.namespaces[ns].entrys.items():
            m = re.fullmatch(r"(\d+)_HeroVoice_(\d+)_Lines", key)
            if not m:
                continue
            line = m.group(2)
            media: Set[int] = set()
            for name in events.get(line, []):
                media |= bank.event_sounds(name)
            lines.append({
                "namespace": ns,
                "key": key,
                "line": line,
                "events": events.get(line, []),
                "media": sorted(media),
                "en": entry.translation,
            })
    (out_dir / "wem").mkdir(parents=True, exist_ok=True)
    for media in sorted({m for line in lines for m in line["media"]}):
        (out_dir / "wem" / f"{media}.wem").write_bytes(bank.sounds[media])
    result = {"mod": source_name, "bank": bank_id, "hero": hero, "namespaces": namespaces, "lines": lines}
    (out_dir / "map.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def bank_in(names: Iterable[str]) -> Optional[str]:
    """The voice bank file among a pak's file names, if there is one."""
    for name in names:
        if BANK_NAME.search(name.replace("\\", "/")):
            return name
    return None

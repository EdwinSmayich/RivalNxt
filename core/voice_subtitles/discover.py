"""Finding voice mods: the ones switched on in ~mods, and the ones in the library.

A voice mod is a legacy .pak (no .utoc beside it) that carries a Wwise voice
bank. Mods in the library are looked for inside their archives, so that a
voice variant has its subtitles ready before it is switched on. What each
file held is remembered by its size and date in index.json: an archive is
opened once. Voice paks found inside archives are kept as voice-paks/<key>.pak.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from .bank import bank_in
from .game import LANGUAGE_TAGS

COMBINED_NAME = "zzz_RivalNxt_Subtitles_9999999_P.pak"
_TAGS = "|".join(sorted(LANGUAGE_TAGS.values(), key=len, reverse=True))
SUBTITLE_PAK = re.compile(rf"^({_TAGS})_subtitles_", re.IGNORECASE)
_SUBTITLE_ARCHIVE = re.compile(rf"^({_TAGS}) subtitles - ", re.IGNORECASE)
_ARCHIVES = (".zip", ".rar", ".7z")


def is_generated(name: str) -> bool:
    """A file this feature writes: the combined file, a subtitle mod or its archive."""
    base = Path(name).name
    return base.lower() == COMBINED_NAME.lower() or bool(SUBTITLE_PAK.match(base)) or bool(_SUBTITLE_ARCHIVE.match(base))


def content_key(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:12]


def _stamp(path: Path) -> str:
    st = path.stat()
    return f"{st.st_size}:{int(st.st_mtime)}"


@dataclass
class VoiceMod:
    key: str
    name: str
    bank: str
    installed: List[str] = field(default_factory=list)   # paths under ~mods
    library: List[dict] = field(default_factory=list)    # {"download_id", "download", "member"}

    @property
    def bank_id(self) -> str:
        return re.search(r"bnk_vo_(\d+)", self.bank).group(1)

    @property
    def hero(self) -> str:
        return self.bank_id[:4]

    def as_dict(self) -> dict:
        return {"key": self.key, "name": self.name, "bank": self.bank, "bank_id": self.bank_id, "hero": self.hero,
                "installed": self.installed, "library": self.library}


class Finder:
    def __init__(self, folder: Path, aes_key: str):
        self.folder = Path(folder)
        self.aes = aes_key
        self.kept = self.folder / "voice-paks"
        self.index_file = self.folder / "index.json"
        self._lock = threading.Lock()

    # ------------------------------------------------------------ index
    def _load(self) -> dict:
        try:
            return json.loads(self.index_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, index: dict) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        staged = self.index_file.with_name(self.index_file.name + ".new")
        staged.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
        staged.replace(self.index_file)

    def _bank(self, pak: Path) -> Optional[str]:
        import rivalnxt_pak

        try:
            return bank_in(rivalnxt_pak.list_pak_files(str(pak), aes_key=self.aes))
        except Exception:
            return None

    def pak_path(self, mod: VoiceMod, mods_dir: Optional[Path]) -> Optional[Path]:
        """A copy of the voice mod's .pak to read: the one in ~mods, or the one kept from an archive."""
        for rel in mod.installed:
            if mods_dir and (mods_dir / rel).is_file():
                return mods_dir / rel
        kept = self.kept / f"{mod.key}.pak"
        return kept if kept.is_file() else None

    # ------------------------------------------------------------ scanning
    def scan(self, mods_dir: Optional[Path], library: Iterable[dict],
             progress: Optional[Callable[[str], None]] = None) -> List[VoiceMod]:
        """Every voice mod, each content once. library rows: {"id", "name", "path"} with an absolute path."""
        with self._lock:
            old = self._load()
            index: Dict[str, dict] = {}
            found: Dict[str, VoiceMod] = {}

            def add(key: str, name: str, bank: str) -> VoiceMod:
                mod = found.get(key)
                if mod is None:
                    mod = found[key] = VoiceMod(key=key, name=name, bank=bank)
                return mod

            if mods_dir and mods_dir.is_dir():
                for pak in sorted(mods_dir.rglob("*.pak")):
                    if is_generated(pak.name) or pak.with_suffix(".utoc").exists():
                        continue
                    rel = pak.relative_to(mods_dir).as_posix()
                    entry_id = f"mods:{rel}"
                    stamp = _stamp(pak)
                    entry = old.get(entry_id)
                    if not entry or entry.get("stamp") != stamp:
                        bank = self._bank(pak)
                        entry = {"stamp": stamp, "voice": [{"key": content_key(pak), "bank": bank, "name": pak.name}] if bank else []}
                    index[entry_id] = entry
                    for v in entry["voice"]:
                        add(v["key"], v["name"], v["bank"]).installed.append(rel)

            for row in library:
                path = Path(str(row.get("path") or ""))
                if not path.name or is_generated(path.name) or not path.exists():
                    continue
                entry_id = f"library:{path}"
                try:
                    stamp = _stamp(path) if path.is_file() else f"dir:{int(path.stat().st_mtime)}"
                except OSError:
                    continue
                entry = old.get(entry_id)
                if (not entry or entry.get("stamp") != stamp
                        or any(not (self.kept / f"{v['key']}.pak").exists() for v in entry["voice"] if v.get("member"))):
                    if progress:
                        progress(f"Looking into {path.name}")
                    entry = {"stamp": stamp, "voice": self._voice_in(path)}
                index[entry_id] = entry
                for v in entry["voice"]:
                    add(v["key"], v["name"], v["bank"]).library.append(
                        {"download_id": row.get("id"), "download": row.get("name") or path.name, "member": v.get("member")})

            self._save(index)
            # Voice paks kept from archives that no longer hold them.
            wanted = {f"{k}.pak" for k in found}
            if self.kept.is_dir():
                for stale in self.kept.iterdir():
                    if stale.name not in wanted:
                        stale.unlink(missing_ok=True)
            return sorted(found.values(), key=lambda m: (m.hero, m.name.lower()))

    def _voice_in(self, path: Path) -> List[dict]:
        """Voice paks inside a library download (archive, folder or loose .pak)."""
        out: List[dict] = []
        if path.is_dir() or path.suffix.lower() == ".pak":
            paks = [path] if path.is_file() else sorted(path.rglob("*.pak"))
            for pak in paks:
                if is_generated(pak.name) or pak.with_suffix(".utoc").exists():
                    continue
                bank = self._bank(pak)
                if bank:
                    key = content_key(pak)
                    self._keep(pak, key, copy=True)
                    out.append({"key": key, "bank": bank, "name": pak.name,
                                "member": pak.relative_to(path).as_posix() if path.is_dir() else pak.name})
            return out
        if path.suffix.lower() not in _ARCHIVES:
            return out
        from core.utils.archive import extract_member, list_entries

        try:
            members = list_entries(str(path))
        except Exception:
            return out
        lower = {m.replace("\\", "/").lower() for m in members}
        for member in members:
            norm = member.replace("\\", "/")
            if not norm.lower().endswith(".pak") or is_generated(norm):
                continue
            if norm[:-4].lower() + ".utoc" in lower:
                continue  # an IoStore mod; its .pak is a stub
            tmp = Path(tempfile.mkdtemp(prefix="rivalnxt_voice_"))
            try:
                pak = tmp / Path(norm).name
                extract_member(str(path), member, str(pak))
                bank = self._bank(pak)
                if bank:
                    key = content_key(pak)
                    self._keep(pak, key, copy=False)
                    out.append({"key": key, "bank": bank, "name": Path(norm).name, "member": member})
            except Exception:
                continue
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        return out

    def _keep(self, pak: Path, key: str, copy: bool) -> None:
        self.kept.mkdir(parents=True, exist_ok=True)
        target = self.kept / f"{key}.pak"
        if target.exists():
            return
        if copy:
            shutil.copyfile(pak, target)
        else:
            shutil.move(str(pak), target)

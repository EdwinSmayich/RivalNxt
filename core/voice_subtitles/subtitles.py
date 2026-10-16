"""Subtitle mods, and the one file the game reads.

A subtitle mod is made for one voice mod and one language. It is an ordinary
mod archive in the downloads folder ("RU Subtitles - <hero> - <voice mod>.zip")
so that the library files it under its hero and the user switches it on and
off with its voice mod. Its .pak holds only that voice mod's lines, as JSON at
a path the game does not read.

The game reads one text file per language, so two subtitle mods that each
carried a whole copy would hide each other. Instead the lines of every
subtitle mod switched on are written into one copy of the game's own file,
zzz_RivalNxt_Subtitles, at the root of ~mods. With none switched on, that
file is removed. A subtitle mod shows whatever language the game is set to:
English subtitles in a game set to Russian are what the voice mod says.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .discover import COMBINED_NAME, SUBTITLE_PAK
from .game import LANGUAGE_TAGS

FRAGMENT_DIR = "Marvel/Content/RivalNxt/Subtitles"
FORMAT = 1

# Sexual content involving a child or an animal is not something this app
# writes. A sexual line keeps the game's own subtitle when
#  - it is about Peni Parker, a teenager, or Jeff the Land Shark, an animal:
#    it names one, or answers a game line that does;
#  - it names an animal. A simile ("hung like a horse", "fuck like animals"),
#    a toy, Squirrel Girl, and the tentacles of Namor's sea monsters are not.
# Voice mods for those two heroes are not given subtitles at all.
LEAVE_NAMED = re.compile(r"\bPen(?:i|ny)\b|\bJeff\b")
ANIMALS = re.compile(r"\b(goats?|dogs?|horses?|pon(?:y|ies)|octop\w*|squids?|squirrels?|animals?)\b", re.IGNORECASE)
NOT_ANIMALS = re.compile(r"\b(?:as|like)\s+(?:an?\s+)?(?:horses?|animals?)\b|\bhorse[\s-]dildos?\b|\bSquirrel Girl\b"
                         r"|\boctopussy\b", re.IGNORECASE)
SEXUAL = re.compile(
    r"\b(cum\w*|cock\w*|dick\w*|puss(?:y|ies)|cunt\w*|fuck\w*|sex\w*|tits?|titties|boobs?|breasts?|nipples?|ass(?:es|hole)?"
    r"|naked|nude|strip\w*|horny|wet|slut\w*|whores?|suck\w*|lick\w*|rid(?:e|ing)|bred|breed\w*|orgy|orgies"
    r"|gangbang\w*|threesome|pegg?ed|hung|balls|holes?|insides?|grop\w*|dildos?|handy|handjob|blowjob|porn\w*"
    r"|climax\w*|orgasm\w*|erotic|kink\w*|bang\w*|screw\w*|jizz|semen|load|panties|womb|vibrator|toys?|deeper|bigger"
    r"|inside me)\b",
    re.IGNORECASE,
)
SKIPPED_HEROES = {"1042": "Peni Parker", "1047": "Jeff the Land Shark"}


def leave_as_is(heard: Optional[str], game_en: Optional[str]) -> bool:
    heard, game_en = heard or "", game_en or ""
    if not SEXUAL.search(heard):
        return False
    if LEAVE_NAMED.search(heard) or LEAVE_NAMED.search(game_en):
        return True
    return bool(ANIMALS.search(NOT_ANIMALS.sub(" ", heard)))


def lang_tag(language: str) -> str:
    return LANGUAGE_TAGS.get(language) or language.replace("-", "").upper()


def fragment_prefix(language: str) -> str:
    return f"{lang_tag(language)}_Subtitles_"


# ---------------------------------------------------------------- one voice mod's lines
def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def translation_files(work: Path, language: str) -> Tuple[Path, Path, Path]:
    """(translations, what each was made from, the user's own edits) for a language."""
    return (work / f"translation.{language}.json", work / f"translation.{language}.made.json",
            work / f"edits.{language}.json")


def subtitle_lines(work: Path, language: str) -> Tuple[Dict[str, Dict[str, str]], Dict[str, int]]:
    """{namespace: {key: text}} this voice mod changes in a language, and how many of each kind.

    A line the mod silences gets an empty subtitle; a line it changes gets the
    user's edit, else the translation (the words heard, for English); a line
    left alone, or still without text, keeps the game's.
    """
    rows = _read(work / "transcript.json", [])
    tr_file, _made, edits_file = translation_files(work, language)
    translations = _read(tr_file, {})
    edits = _read(edits_file, {})
    lines: Dict[str, Dict[str, str]] = {}
    counts = {"subtitled": 0, "silenced": 0, "kept": 0, "missing": 0}
    for row in rows:
        key = row["key"]
        if key in edits and edits[key] is not None:
            text = edits[key]
        elif row["status"] == "silent":
            text = ""
        elif row["status"] == "changed":
            if leave_as_is(row.get("heard"), row.get("en")):
                counts["kept"] += 1
                continue
            text = row.get("heard") if language == "en" else translations.get(key)
            if not text:
                counts["missing"] += 1
                continue
        else:
            continue
        lines.setdefault(row["namespace"], {})[key] = text
        counts["silenced" if text == "" else "subtitled"] += 1
    return lines, counts


def variant_name(source_pak: str) -> str:
    """"LunaVoiceS9Fix_9999999_P.pak" -> "LunaVoiceS9Fix"."""
    stem = Path(source_pak).stem
    return re.sub(r"_\d+_P$", "", stem, flags=re.IGNORECASE).strip() or stem


def subtitle_mod_names(hero_name: str, source_pak: str, language: str) -> Tuple[str, str]:
    """(archive name in the downloads folder, .pak name inside it)."""
    variant = variant_name(source_pak)
    safe = re.sub(r'[<>:"/\\|?*]+', " ", variant).strip()
    compact = lambda s: re.sub(r"[^A-Za-z0-9]+", "", s)  # noqa: E731
    return (f"{lang_tag(language)} Subtitles - {hero_name} - {safe}.zip",
            f"{fragment_prefix(language)}{compact(hero_name)}_{compact(variant)}_9999999_P.pak")


def write_subtitle_mod(work: Path, language: str, hero_name: str, source_pak: str,
                       downloads: Path, mods_dir: Optional[Path], aes_key: str) -> dict:
    """Put the subtitle mod in the downloads folder; refresh any copy switched on in ~mods.

    Returns {"archive", "pak", "counts", "changed", "active": [copies in ~mods]}.
    """
    import rivalnxt_pak

    lines, counts = subtitle_lines(work, language)
    mapping = _read(work / "map.json", {})
    payload = {"format": FORMAT, "language": language, "hero": mapping.get("hero"), "voice": source_pak,
               "work": work.name, "lines": lines}
    text = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True)
    archive_name, pak_name = subtitle_mod_names(hero_name, source_pak, language)
    archive = Path(downloads) / archive_name
    active = sorted(mods_dir.rglob(pak_name)) if mods_dir and mods_dir.is_dir() else []
    stamp = work / f"subtitle-mod.{language}.json"
    result = {"archive": archive, "pak": pak_name, "counts": counts, "changed": False, "active": active}
    if stamp.exists() and stamp.read_text(encoding="utf-8") == text and archive.exists():
        return result
    with tempfile.TemporaryDirectory(prefix="rivalnxt_subs_") as tmp:
        built = Path(tmp) / pak_name
        rivalnxt_pak.write_pak(str(built), [(f"{FRAGMENT_DIR}/{language}/{work.name}.json", text.encode("utf-8"))],
                               aes_key=aes_key)
        archive.parent.mkdir(parents=True, exist_ok=True)
        staged = archive.with_name(archive.name + ".new")
        with zipfile.ZipFile(staged, "w", zipfile.ZIP_STORED) as z:
            z.write(built, pak_name)
        os.replace(staged, archive)
        for copy in active:
            try:
                shutil.copyfile(built, copy)
            except PermissionError:
                pass  # the game has it open; the combined file is rebuilt once it is closed
    stamp.write_text(text, encoding="utf-8")
    result["changed"] = True
    return result


def read_subtitle_mod(pak: Path, aes_key: str) -> Optional[dict]:
    """The lines a subtitle mod carries, or None for a file that is not one."""
    import rivalnxt_pak

    try:
        names = rivalnxt_pak.list_pak_files(str(pak), aes_key=aes_key)
        inner = next((n for n in names if n.startswith(FRAGMENT_DIR + "/") and n.endswith(".json")), None)
        if inner is None:
            return None
        data = json.loads(bytes(rivalnxt_pak.read_pak_file(str(pak), inner, aes_key=aes_key)).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("lines"), dict):
        return None
    return data


# ---------------------------------------------------------------- the combined file
class GameHasItOpen(Exception):
    """The game keeps every mod file open while it runs."""


def enabled_subtitle_mods(mods_dir: Path) -> List[Path]:
    """The subtitle mods switched on, in every language, in file-name order."""
    if not mods_dir.is_dir():
        return []
    return sorted((p for p in mods_dir.rglob("*.pak") if SUBTITLE_PAK.match(p.name)), key=lambda p: p.name.lower())


def build_combined(game, language: str, mods_dir: Path, aes_key: str) -> dict:
    """Write the switched-on subtitle mods' lines into one copy of the game's text file.

    Where two subtitle mods change the same line, one in the game's language
    wins over one in another, then the later file name, as with the game's own
    mod files. Raises GameHasItOpen when the old file cannot be replaced.
    """
    import rivalnxt_pak

    out = mods_dir / COMBINED_NAME
    parts = [data for pak in enabled_subtitle_mods(mods_dir) if (data := read_subtitle_mod(pak, aes_key))]
    parts.sort(key=lambda data: data.get("language") == language)  # stable: names keep their order
    totals = {"mods": len(parts), "subtitled": 0, "silenced": 0, "language": language,
              "languages": sorted({str(data.get("language")) for data in parts})}
    if not parts:
        if out.exists():
            try:
                out.unlink()
            except PermissionError as exc:
                raise GameHasItOpen(out.name) from exc
        return totals
    wanted: Dict[Tuple[str, str], str] = {}
    for data in parts:
        for namespace, entries in data["lines"].items():
            if isinstance(entries, dict):
                wanted.update(((namespace, key), text) for key, text in entries.items() if isinstance(text, str))
    lf = game.locres(language)
    changed: List[Tuple[object, str]] = []  # (entry, original text), to put back afterwards
    try:
        for (namespace, key), text in wanted.items():
            ns = lf.namespaces.get(namespace)
            entry = ns.entrys.get(key) if ns is not None else None
            if entry is None:
                continue
            changed.append((entry, entry.translation))
            entry.translation = text
            totals["silenced" if text == "" else "subtitled"] += 1
        with tempfile.TemporaryDirectory(prefix="rivalnxt_subs_") as tmp:
            edited = Path(tmp) / "Game.locres"
            lf.write(str(edited))
            built = Path(tmp) / COMBINED_NAME
            rivalnxt_pak.write_pak(str(built), [(f"Marvel/Content/Localization/Game/{language}/Game.locres",
                                                 edited.read_bytes())], aes_key=aes_key)
            _install(built, out)
    finally:
        # The parsed file is shared and cached: leave it as the game has it.
        for entry, original in reversed(changed):
            entry.translation = original
    return totals


def _install(built: Path, out: Path) -> None:
    staged = out.with_name(out.name + ".rivalnxt-new")
    try:
        shutil.copyfile(built, staged)
        os.replace(staged, out)
    except PermissionError as exc:
        try:
            staged.unlink()
        except OSError:
            pass
        raise GameHasItOpen(out.name) from exc

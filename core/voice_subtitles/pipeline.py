"""Making the subtitles of one voice mod, step by step.

Every step keeps its result in the voice mod's folder (voice-mods/<bank>-<key>/)
and is skipped when that result is already there, so a run stopped halfway --
cancelled, the game started, the app closed -- picks up where it stopped.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import recognize
from .bank import map_voice_mod
from .subtitles import SKIPPED_HEROES, leave_as_is, translation_files
from .translate import Memory

CHUNK = 24


class Stopped(Exception):
    """Cancelled, or the game was started: the step's work so far is kept."""


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, data) -> None:
    staged = path.with_name(path.name + ".new")
    staged.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    staged.replace(path)


def work_dir(root: Path, bank_id: str, key: str) -> Path:
    return Path(root) / "voice-mods" / f"{bank_id}-{key}"


def ensure_map(work: Path, pak: Path, bank_file: str, bank_id: str, game, aes_key: str, source_name: str,
               need_sounds: bool) -> dict:
    """map.json, and the sounds (wem/) when they are still to be heard."""
    mapping = _read(work / "map.json", None)
    if mapping is not None and (not need_sounds or (work / "wem").is_dir()):
        return mapping
    work.mkdir(parents=True, exist_ok=True)
    return map_voice_mod(bank_id, read_bank(pak, bank_file, aes_key), game, work, source_name)


def read_bank(pak: Path, bank_file: str, aes_key: str) -> bytes:
    """The voice bank out of a mod's .pak (mods compress it with Oodle, which rust_ue_tools reads)."""
    import rust_ue_tools

    from .game import _quiet

    tmp = Path(tempfile.mkdtemp(prefix="rivalnxt_bank_"))
    try:
        _quiet(rust_ue_tools.PyUnpacker().unpack_pak, str(pak), str(tmp), aes_key=aes_key, force=True, quiet=True)
        name = Path(bank_file).name.lower()
        found = next((p for p in tmp.rglob("*") if p.name.lower() == name), None)
        if found is None:
            raise RuntimeError(f"{Path(bank_file).name} could not be read out of {pak.name}")
        return found.read_bytes()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def heard_complete(work: Path) -> bool:
    mapping = _read(work / "map.json", {"lines": []})
    heard = _read(work / "heard.json", {})
    return all(str(m) in heard for line in mapping["lines"] for m in line["media"])


def recognise(work: Path, vgmstream: Path, server_factory, progress, cancelled) -> Dict[str, int]:
    """Decode and hear every sound, then compare each line with the game's."""
    if not heard_complete(work):
        progress("Decoding sounds", 0, 0)
        recognize.decode(work, vgmstream, cancelled, progress=lambda d, t: progress("Decoding sounds", d, t))
        if cancelled():
            raise Stopped()
        recognize.hear_sounds(work, server_factory, progress=lambda d, t: progress("Recognising speech", d, t),
                              cancelled=cancelled)
        if not heard_complete(work):
            raise Stopped()
    counts = recognize.classify(work)
    recognize.drop_sounds(work)
    return counts


def lines_to_translate(work: Path, language: str, model: str) -> List[dict]:
    """Changed lines whose translation is missing, or was made from other words or by another model."""
    rows = _read(work / "transcript.json", [])
    tr_file, made_file, _edits = translation_files(work, language)
    translations, made = _read(tr_file, {}), _read(made_file, {})
    todo = []
    for row in rows:
        if row["status"] != "changed" or leave_as_is(row.get("heard"), row.get("en")):
            continue
        if translations.get(row["key"]) and made.get(row["key"]) == {"heard": row["heard"], "model": model}:
            continue
        todo.append(row)
    return todo


def done_elsewhere(root: Path, work: Path, hero: str, language: str, model: str) -> Dict[str, str]:
    """This model's translations of the same words for the same hero in another voice mod.

    Variants of one voice mod share most of their lines; each is translated once.
    """
    out: Dict[str, str] = {}
    for other in (Path(root) / "voice-mods").glob(f"{hero}*-*"):
        if other == work:
            continue
        tr_file, made_file, _edits = translation_files(other, language)
        texts, made = _read(tr_file, {}), _read(made_file, {})
        for key, info in made.items():
            if info.get("model") == model and texts.get(key):
                out.setdefault(info.get("heard"), texts[key])
    return out


def user_memory(root: Path, language: str) -> Memory:
    """Every line the user corrected by hand, in any voice mod: examples for the rest."""
    pairs = []
    for work in (Path(root) / "voice-mods").glob("*-*"):
        _tr, _made, edits_file = translation_files(work, language)
        edits = _read(edits_file, {})
        if not edits:
            continue
        rows = {r["key"]: r for r in _read(work / "transcript.json", [])}
        pairs += [(rows[k]["heard"], text) for k, text in edits.items() if text and rows.get(k, {}).get("heard")]
    return Memory(pairs)


def translate(work: Path, root: Path, language: str, language_name: str, model: str, game, server_factory,
              progress, cancelled, game_running: Callable[[], bool]) -> int:
    """Translate what is still to be translated; returns how many lines were done now."""
    todo = lines_to_translate(work, language, model)
    if not todo:
        return 0
    mapping = _read(work / "map.json", {})
    hero = mapping.get("hero", "")
    tr_file, made_file, _edits = translation_files(work, language)
    translations, made = _read(tr_file, {}), _read(made_file, {})

    def save(rows: List[dict], texts: List[Optional[str]]) -> None:
        for row, text in zip(rows, texts):
            if text:
                translations[row["key"]] = text
                made[row["key"]] = {"heard": row["heard"], "model": model}
        _write(tr_file, translations)
        _write(made_file, made)

    known = done_elsewhere(root, work, hero, language, model)
    reused = [row for row in todo if row["heard"] in known]
    if reused:
        save(reused, [known[row["heard"]] for row in reused])
    todo = [row for row in todo if row["heard"] not in known]
    if not todo:
        return len(reused)
    try:
        local = game.locres(language)
    except FileNotFoundError:
        local = None

    def official(row: dict) -> str:
        ns = local.namespaces.get(row["namespace"]) if local else None
        entry = ns.entrys.get(row["key"]) if ns else None
        return entry.translation if entry is not None else ""

    speaker, feminine = game.speaker(hero, language)
    names = game.names(language)
    memory = user_memory(root, language)
    total, done = len(todo), 0
    progress("Loading the translation model", 0, total)
    with server_factory() as server:
        for start in range(0, total, CHUNK):
            if cancelled() or game_running():
                raise Stopped()
            chunk = todo[start:start + CHUNK]
            items = [{"heard": r["heard"], "game_en": r.get("en") or "", "game_local": official(r)} for r in chunk]
            texts = server.translate(items, language=language, language_name=language_name, speaker=speaker,
                                     feminine=feminine, names=names, memory=memory,
                                     progress=lambda d, t: progress("Translating", done + d, total),
                                     cancelled=lambda: cancelled() or game_running())
            save(chunk, texts)
            done += len(chunk)
            if any(t is None for t in texts):
                raise Stopped()
    return len(reused) + total


def skipped(hero: str) -> Optional[str]:
    return SKIPPED_HEROES.get(hero)

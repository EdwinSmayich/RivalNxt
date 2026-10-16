"""Voice subtitles in the app: settings, voice mods, background work, the combined file.

Three kinds of background work, each on its own thread so that one never
waits for another:
  * making subtitles (recognition and translation; one voice mod at a time --
    they share the graphics card),
  * installing components (downloads, one at a time),
  * the combined subtitle file, rebuilt a few seconds after mods change.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import components as comps
from . import pipeline
from .discover import Finder, VoiceMod, is_generated
from .game import DEFAULT_AES, LANGUAGES, Game, game_language
from .hardware import Hardware, detect
from .recognize import WhisperServer
from .subtitles import GameHasItOpen, build_combined, leave_as_is, subtitle_lines, \
    subtitle_mod_names, translation_files, variant_name, write_subtitle_mod
from .translate import LlamaServer

CONFIG_NAME = "voice-subtitles.json"
GAME_PROCESS = "marvel.exe"
REBUILD_DELAY = 4.0
GAME_POLL = 30.0
SPARE_BYTES = 1_000_000_000  # left free on the drive after a download


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_folder(data_dir: Path) -> Path:
    """Models are gigabytes: under Local, not the roaming profile the app's data lives in."""
    local = os.environ.get("LOCALAPPDATA")
    return Path(local) / "RivalNxt" / "Voice Subtitles" if local else Path(data_dir) / "voice-subtitles"


def game_is_running() -> bool:
    try:
        import psutil

        return any((p.info.get("name") or "").lower() == GAME_PROCESS for p in psutil.process_iter(["name"]))
    except Exception:
        return False


@dataclass
class Job:
    kind: str                     # "make" or "install"
    title: str
    target: str                   # a voice mod's key, or component ids joined by ","
    language: Optional[str] = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    state: str = "queued"         # queued, running, waiting, done, failed, cancelled
    stage: str = ""
    done: int = 0
    total: int = 0
    error: Optional[str] = None
    created_at: str = field(default_factory=_now)
    finished_at: Optional[str] = None
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    # Where the current stage started (time, done), for the time left.
    stage_start: tuple = field(default=(0.0, 0), repr=False)

    def progress(self, stage: str, done: int, total: int) -> None:
        if stage != self.stage or done < self.done:
            self.stage_start = (time.monotonic(), done)
        self.stage, self.done, self.total = stage, done, total

    def seconds_left(self) -> Optional[int]:
        """From the pace of the current stage, once it has run a little."""
        started, done0 = self.stage_start
        elapsed, done = time.monotonic() - started, self.done - done0
        if self.state != "running" or not started or elapsed < 8 or done <= 0 or self.total <= self.done:
            return None
        return int((self.total - self.done) * elapsed / done)

    def public(self) -> dict:
        # Not asdict(): that deep-copies the cancel event, and its lock cannot be copied.
        out = {f.name: getattr(self, f.name) for f in fields(self) if f.name not in ("cancel", "stage_start")}
        out["seconds_left"] = self.seconds_left()
        return out


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


class VoiceSubtitles:
    def __init__(
        self,
        data_dir: Callable[[], Path],
        settings: Callable[[], Any],
        library: Callable[[], List[dict]],
        on_new_downloads: Callable[[], List[str]] = lambda: [],
        log: Callable[[str, str, Optional[str]], None] = lambda kind, title, detail=None: None,
        game_running: Callable[[], bool] = game_is_running,
        hardware: Callable[[], Hardware] = detect,
        rebuild_delay: float = REBUILD_DELAY,
        game_poll: float = GAME_POLL,
    ):
        self._data_dir = data_dir
        self._settings = settings
        self._library = library
        self._on_new_downloads = on_new_downloads
        self._log = log
        self._game_running = game_running
        self._hardware = hardware
        self._rebuild_delay = rebuild_delay
        self._game_poll = game_poll
        self._lock = threading.RLock()
        self._jobs: List[Job] = []
        self._make_wake = threading.Event()
        self._install_wake = threading.Event()
        self._threads: Dict[str, threading.Thread] = {}
        self._voice_mods: Optional[List[VoiceMod]] = None
        self._scanning = False
        self._scan_note = ""
        self._game: Optional[Game] = None
        self._rebuild_due: Optional[float] = None
        self._combined: Dict[str, Any] = {}
        self._counts: Dict[tuple, tuple] = {}   # (work, language) -> (files' dates, summary)
        self._running: tuple = (0.0, False)     # (when looked, the game is running)

    # ------------------------------------------------------------ settings
    def _config_file(self) -> Path:
        return Path(self._data_dir()) / CONFIG_NAME

    def config(self) -> dict:
        data = _read(self._config_file(), {})
        if not isinstance(data, dict):
            data = {}
        folder = data.get("folder") or str(default_folder(Path(self._data_dir())))
        return {"folder": folder, "model": data.get("model"), "language": data.get("language"),
                "gpu_recognition": bool(data.get("gpu_recognition", False))}

    def set_config(self, **changes) -> dict:
        with self._lock:
            data = _read(self._config_file(), {})
            data = data if isinstance(data, dict) else {}
            if "folder" in changes and changes["folder"] is not None:
                new = Path(str(changes["folder"])).expanduser()
                if self._busy():
                    raise ValueError("Wait for the current work to finish before moving the folder")
                old = self.folder()
                if new.resolve() != old.resolve():
                    new.mkdir(parents=True, exist_ok=True)
                    _move_contents(old, new)
                data["folder"] = str(new)
                self._game = None
                self._voice_mods = None
            for key in ("model", "language", "gpu_recognition"):
                if key in changes:
                    data[key] = changes[key]
            if data.get("model") and data["model"] not in comps.MODELS:
                raise ValueError(f"unknown model {data['model']!r}")
            if data.get("language") and data["language"] not in LANGUAGES:
                raise ValueError(f"unknown language {data['language']!r}")
            path = self._config_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            staged = path.with_name(path.name + ".new")
            staged.write_text(json.dumps(data, indent=1), encoding="utf-8")
            staged.replace(path)
        return self.config()

    def folder(self) -> Path:
        return Path(self.config()["folder"])

    def _aes(self) -> str:
        return getattr(self._settings(), "aes_key_hex", None) or DEFAULT_AES

    def mods_dir(self) -> Optional[Path]:
        root = getattr(self._settings(), "marvel_rivals_root", None)
        if not root:
            return None
        from core.config.settings import get_mods_dir

        return get_mods_dir(root)

    def downloads_dir(self) -> Optional[Path]:
        root = getattr(self._settings(), "marvel_rivals_local_downloads_root", None)
        return Path(root) if root else None

    def game(self) -> Optional[Game]:
        root = getattr(self._settings(), "marvel_rivals_root", None)
        if not root:
            return None
        paks = Path(root) / "MarvelGame" / "Marvel" / "Content" / "Paks"
        if not (paks / "pakchunkLocres-Windows.pak").exists():
            return None
        with self._lock:
            if self._game is None or self._game.paks != paks:
                self._game = Game(paks, self.folder() / "game", self._aes())
            return self._game

    def game_language(self) -> str:
        return game_language()

    def target_language(self) -> str:
        return self.config()["language"] or self.game_language()

    # ------------------------------------------------------------ voice mods
    def voice_mods(self) -> List[VoiceMod]:
        with self._lock:
            mods = self._voice_mods
        if mods is None:
            self.rescan()
            return []
        return mods

    def rescan(self) -> None:
        """Look for voice mods again, in the background."""
        with self._lock:
            if self._scanning:
                self._rescan_again = True
                return
            self._scanning = True
            self._rescan_again = False
        threading.Thread(target=self._scan, name="voice-subtitles-scan", daemon=True).start()

    def _scan(self) -> None:
        try:
            while True:
                finder = Finder(self.folder(), self._aes())
                mods = finder.scan(self.mods_dir(), self._library(), progress=self._set_scan_note)
                with self._lock:
                    self._voice_mods = mods
                    again = getattr(self, "_rescan_again", False)
                    self._rescan_again = False
                if not again:
                    break
        except Exception as exc:
            self._scan_note = f"Could not look for voice mods: {exc}"
        finally:
            with self._lock:
                self._scanning = False
                if self._scan_note.startswith("Looking"):
                    self._scan_note = ""

    def _set_scan_note(self, note: str) -> None:
        self._scan_note = note

    def _find(self, key: str) -> VoiceMod:
        for mod in self.voice_mods():
            if mod.key == key:
                return mod
        raise KeyError(key)

    # ------------------------------------------------------------ components
    def _installed(self) -> Dict[str, dict]:
        return comps.installed(self.folder())

    def recognition_ready(self) -> bool:
        installed = self._installed()
        return all(c in installed for c in comps.RECOGNITION)

    def translation_ready(self, hw: Optional[Hardware] = None) -> bool:
        model = self.config()["model"]
        hw = hw or self._hardware()
        installed = self._installed()
        return bool(model) and model in installed and comps.engine_for(hw) in installed

    def install(self, what: str) -> Job:
        """what: "recognition", "gpu-recognition" or a model id (with the llama.cpp build it needs)."""
        hw = self._hardware()
        if what == "recognition":
            ids, title = list(comps.RECOGNITION), "Speech recognition"
        elif what == "gpu-recognition":
            ids, title = ["whisper-cuda"], "Speech recognition on the graphics card"
        elif what in comps.MODELS:
            # The model in use changes once this one is downloaded: until then the old one keeps working.
            ids, title = [comps.engine_for(hw), what], f"Translation: {comps.MODELS[what].title}"
        else:
            raise ValueError(f"unknown component {what!r}")
        installed = self._installed()
        ids = [i for i in ids if i not in installed]
        job = Job(kind="install", title=title, target=",".join(ids))
        job.total = sum(comps.COMPONENTS[i].size for i in ids)
        free = _free_bytes(self.folder())
        if ids and free is not None and free < job.total + SPARE_BYTES:
            raise ValueError(f"Not enough free space on the drive: {job.total / 1e9:.1f} GB needed, "
                             f"{free / 1e9:.1f} GB free. Choose another folder for voice subtitles.")
        if not ids:
            job.state, job.finished_at = "done", _now()
            self._installed_now(what)
            return job
        with self._lock:
            self._jobs.append(job)
        self._start("install", self._install_loop, self._install_wake)
        return job

    def _installed_now(self, what: str) -> None:
        if what == "gpu-recognition":
            self.set_config(gpu_recognition=True)
        elif what in comps.MODELS:
            self.set_config(model=what)

    def remove(self, what: str) -> None:
        if self._busy():
            raise ValueError("Wait for the current work to finish")
        if what == "recognition":
            ids = list(comps.RECOGNITION) + ["whisper-cuda"]
        elif what == "gpu-recognition":
            ids = ["whisper-cuda"]
            self.set_config(gpu_recognition=False)
        elif what in comps.MODELS:
            ids = [what]
            if self.config()["model"] == what:
                self.set_config(model=None)
        elif what == "engines":
            ids = list(comps.ENGINES)
        else:
            raise ValueError(f"unknown component {what!r}")
        for cid in ids:
            comps.remove(cid, self.folder())
        # A llama.cpp build no installed model needs.
        if not any(m in self._installed() for m in comps.MODELS):
            for engine in comps.ENGINES:
                comps.remove(engine, self.folder())

    def _install_loop(self) -> None:
        while True:
            job = self._next("install")
            if job is None:
                return
            try:
                for cid in job.target.split(","):
                    comp = comps.COMPONENTS[cid]
                    base = job.done
                    job.progress(f"Downloading {comp.title}", base, job.total)
                    comps.install(cid, self.folder(),
                                  progress=lambda d, t, base=base: job.progress(job.stage, base + d, job.total),
                                  cancelled=job.cancel.is_set)
                    job.done = base + comp.size
                for cid in job.target.split(","):
                    self._installed_now("gpu-recognition" if cid == "whisper-cuda" else cid)
                self._finish(job, "done")
                self._log("subtitles", f"{job.title}: installed", None)
            except comps.Cancelled:
                self._finish(job, "cancelled")
            except Exception as exc:
                self._finish(job, "failed", str(exc))

    # ------------------------------------------------------------ making subtitles
    def make(self, key: str, language: Optional[str] = None) -> Job:
        language = language or self.target_language()
        if language not in LANGUAGES:
            raise ValueError(f"unknown language {language!r}")
        mod = self._find(key)
        if pipeline.skipped(mod.hero):
            raise ValueError("Subtitles are not made for this hero's voice mods")
        if not self.recognition_ready():
            raise ValueError("Install speech recognition first")
        if language != "en" and not self.translation_ready():
            raise ValueError("Install a translation model first")
        with self._lock:
            for job in self._jobs:
                if job.kind == "make" and job.target == key and job.language == language and job.state in (
                        "queued", "running", "waiting"):
                    return job
            job = Job(kind="make", title=f"{self._hero_name(mod.hero)} · {variant_name(mod.name)}", target=key,
                      language=language)
            self._jobs.append(job)
        self._start("make", self._make_loop, self._make_wake)
        return job

    def make_all(self, language: Optional[str] = None) -> List[Job]:
        """Every voice mod whose subtitles in a language are not made yet."""
        language = language or self.target_language()
        if language not in LANGUAGES:
            raise ValueError(f"unknown language {language!r}")
        if not self.recognition_ready():
            raise ValueError("Install speech recognition first")
        if language != "en" and not self.translation_ready():
            raise ValueError("Install a translation model first")
        downloads = self.downloads_dir()
        jobs = []
        for mod in self.voice_mods():
            if pipeline.skipped(mod.hero):
                continue
            archive, _pak = subtitle_mod_names(self._hero_name(mod.hero), mod.name, language)
            work = pipeline.work_dir(self.folder(), mod.bank_id, mod.key)
            summary = self._summary(work, language)
            if downloads and (downloads / archive).exists() and summary and summary["counts"]["missing"] == 0:
                continue
            jobs.append(self.make(mod.key, language))
        return jobs

    def _hero_name(self, hero: str) -> str:
        game = self.game()
        if game is not None:
            try:
                return game.english_hero_name(hero)
            except Exception:
                pass
        return hero

    def _make_loop(self) -> None:
        while True:
            job = self._next("make")
            if job is None:
                return
            try:
                self._make(job)
            except pipeline.Stopped:
                if job.cancel.is_set():
                    self._finish(job, "cancelled")
                else:
                    with self._lock:  # the game was started: again once it is closed
                        job.state, job.stage = "queued", "Waiting for the game to close"
                    self._make_wake.set()
            except Exception as exc:
                self._finish(job, "failed", str(exc))
                self._log("subtitles", "Could not make subtitles", f"{job.title}: {exc}")

    def _wait_for_game(self, job: Job) -> None:
        while self._game_running() and not job.cancel.is_set():
            job.state, job.stage = "waiting", "Waiting for the game to close"
            job.cancel.wait(self._game_poll)
        if job.cancel.is_set():
            raise pipeline.Stopped()
        job.state = "running"

    def _make(self, job: Job) -> None:
        mod = self._find(job.target)
        game = self.game()
        if game is None:
            raise RuntimeError("Set the Marvel Rivals folder in Settings first")
        folder, aes, mods_dir, downloads = self.folder(), self._aes(), self.mods_dir(), self.downloads_dir()
        if downloads is None:
            raise RuntimeError("Set the mod downloads folder in Settings first")
        finder = Finder(folder, aes)
        pak = finder.pak_path(mod, mods_dir)
        if pak is None:
            raise RuntimeError("The voice mod's file is gone; look for voice mods again")
        work = pipeline.work_dir(folder, mod.bank_id, mod.key)
        cancelled = job.cancel.is_set

        progress = job.progress
        self._wait_for_game(job)
        progress("Reading the voice mod", 0, 0)
        need_sounds = not pipeline.heard_complete(work) if (work / "map.json").exists() else True
        pipeline.ensure_map(work, pak, mod.bank, mod.bank_id, game, aes, mod.name, need_sounds)
        _write_source(work, mod)
        hw = self._hardware()
        cfg = self.config()
        whisper_id = "whisper-cuda" if cfg["gpu_recognition"] and "whisper-cuda" in self._installed() else "whisper-cpu"
        pipeline.recognise(
            work, comps.path_of("vgmstream", folder),
            lambda: WhisperServer(comps.path_of(whisper_id, folder), comps.path_of("whisper-model", folder),
                                  log=folder / "whisper-server.log"),
            progress, lambda: cancelled() or self._game_running())
        language = job.language or "en"
        if language != "en":
            model = cfg["model"]
            if not model or not self.translation_ready(hw):
                raise RuntimeError("Install a translation model first")
            rt = comps.runtime(model, folder, hw)
            self._wait_for_game(job)
            pipeline.translate(
                work, folder, language, LANGUAGES[language], model, game,
                lambda: LlamaServer(comps.path_of(rt.engine, folder), rt.args, rt.parallel, rt.thinking,
                                    log=folder / "llama-server.log"),
                progress, cancelled, self._game_running)
        progress("Writing the subtitle mod", 0, 0)
        result = self._write_mod(work, mod, language)
        self._finish(job, "done")
        counts = result["counts"]
        self._log("subtitles", f"Made {LANGUAGES[language]} subtitles",
                  f"{result['archive'].stem}: {counts['subtitled']} lines, {counts['silenced']} silenced")

    def _write_mod(self, work: Path, mod: VoiceMod, language: str) -> dict:
        result = write_subtitle_mod(work, language, self._hero_name(mod.hero), mod.name, self.downloads_dir(),
                                    self.mods_dir(), self._aes())
        try:
            added = self._on_new_downloads() or []
        except Exception:
            added = []
        if any(not is_generated(name) for name in added):
            self.rescan()  # other new downloads came with it; one may be a voice mod
        if result["changed"] and result["active"]:
            self.request_rebuild("subtitles changed")
        return result

    # ------------------------------------------------------------ job queue
    def _start(self, name: str, target: Callable[[], None], wake: threading.Event) -> None:
        with self._lock:
            thread = self._threads.get(name)
            if thread is None or not thread.is_alive():
                thread = threading.Thread(target=target, name=f"voice-subtitles-{name}", daemon=True)
                self._threads[name] = thread
                thread.start()
        wake.set()

    def _next(self, kind: str) -> Optional[Job]:
        wake = self._make_wake if kind == "make" else self._install_wake
        while True:
            with self._lock:
                job = next((j for j in self._jobs if j.kind == kind and j.state == "queued"), None)
                if job is not None:
                    job.state = "running"
                    return job
                if not any(j.kind == kind and j.state in ("queued", "running", "waiting") for j in self._jobs):
                    self._threads.pop(kind, None)
                    return None
            wake.wait(5)
            wake.clear()

    def _finish(self, job: Job, state: str, error: Optional[str] = None) -> None:
        with self._lock:
            job.state, job.error, job.finished_at = state, error, _now()
            if state != "failed":
                job.stage = ""
            # Keep the last few finished jobs for the page to show.
            finished = [j for j in self._jobs if j.state in ("done", "failed", "cancelled")]
            for old in finished[:-8]:
                self._jobs.remove(old)

    def cancel(self, job_id: str) -> None:
        with self._lock:
            job = next((j for j in self._jobs if j.id == job_id), None)
            if job is None:
                raise KeyError(job_id)
            job.cancel.set()
            if job.state == "queued":
                self._finish(job, "cancelled")

    def _busy(self) -> bool:
        with self._lock:
            return any(j.state in ("queued", "running", "waiting") for j in self._jobs)

    def jobs(self) -> List[dict]:
        with self._lock:
            return [j.public() for j in self._jobs]

    # ------------------------------------------------------------ the combined file
    def request_rebuild(self, reason: str = "") -> None:
        """Rebuild the combined file a few seconds from now (switching a collection on is many changes)."""
        with self._lock:
            self._rebuild_due = time.monotonic() + self._rebuild_delay
            self._combined["reason"] = reason
        self._start("rebuild", self._rebuild_loop, threading.Event())

    def mods_changed(self, reason: str) -> None:
        """The combined file follows the subtitle mods that are on; the list of
        voice mods is looked at again only once the feature has been used."""
        self.request_rebuild(reason)
        if self._voice_mods is not None or self._config_file().exists():
            self.rescan()

    def _rebuild_loop(self) -> None:
        while True:
            with self._lock:
                due = self._rebuild_due
                if due is None:
                    self._threads.pop("rebuild", None)
                    return
            wait = due - time.monotonic()
            if wait > 0:
                time.sleep(min(wait, 1.0))
                continue
            with self._lock:
                self._rebuild_due = None
            self.rebuild_now()

    def rebuild_now(self) -> dict:
        game, mods_dir = self.game(), self.mods_dir()
        if game is None or mods_dir is None:
            return {}
        language = self.game_language()
        try:
            totals = build_combined(game, language, mods_dir, self._aes())
            self._combined.update(totals, error=None, updated_at=_now(), waiting=False)
        except GameHasItOpen:
            # Again once the game is closed.
            self._combined.update(waiting=True)
            with self._lock:
                self._rebuild_due = time.monotonic() + self._game_poll
            return self._combined
        except Exception as exc:
            self._combined.update(error=str(exc), updated_at=_now())
            self._log("subtitles", "Could not update the subtitle file", str(exc))
        return dict(self._combined)

    # ------------------------------------------------------------ lines
    def lines(self, key: str, language: str) -> List[dict]:
        if language not in LANGUAGES:
            raise ValueError(f"unknown language {language!r}")
        mod = self._find(key)
        work = pipeline.work_dir(self.folder(), mod.bank_id, mod.key)
        rows = _read(work / "transcript.json", [])
        tr_file, _made, edits_file = translation_files(work, language)
        translations, edits = _read(tr_file, {}), _read(edits_file, {})
        game = self.game()
        local = None
        if game is not None:
            try:
                local = game.locres(language)
            except FileNotFoundError:
                local = None
        out = []
        for row in rows:
            if row["status"] not in ("changed", "silent"):
                continue
            ns = local.namespaces.get(row["namespace"]) if local else None
            entry = ns.entrys.get(row["key"]) if ns else None
            left = row["status"] == "changed" and leave_as_is(row.get("heard"), row.get("en"))
            made = row.get("heard") if language == "en" else translations.get(row["key"])
            out.append({
                "key": row["key"], "status": row["status"], "game": entry.translation if entry is not None else row.get("en"),
                "game_en": row.get("en"), "heard": row.get("heard"),
                "subtitle": edits.get(row["key"], "" if row["status"] == "silent" else made),
                "edited": row["key"] in edits, "left_as_in_game": left,
            })
        return out

    def edit(self, key: str, language: str, line_key: str, text: Optional[str]) -> dict:
        """Set a line's subtitle by hand (None takes the edit back); the subtitle mod is rewritten."""
        if language not in LANGUAGES:
            raise ValueError(f"unknown language {language!r}")
        mod = self._find(key)
        work = pipeline.work_dir(self.folder(), mod.bank_id, mod.key)
        rows = {r["key"]: r for r in _read(work / "transcript.json", [])}
        if line_key not in rows:
            raise KeyError(line_key)
        if text is not None and rows[line_key]["status"] == "changed" and leave_as_is(
                rows[line_key].get("heard"), rows[line_key].get("en")):
            raise ValueError("This line keeps the game's own subtitle")
        _tr, _made, edits_file = translation_files(work, language)
        edits = _read(edits_file, {})
        if text is None:
            edits.pop(line_key, None)
        else:
            edits[line_key] = " ".join(text.split())
        edits_file.write_text(json.dumps(edits, ensure_ascii=False, indent=1), encoding="utf-8")
        result = self._write_mod(work, mod, language)
        return {"counts": result["counts"]}

    # ------------------------------------------------------------ status
    def status(self) -> dict:
        cfg = self.config()
        folder = Path(cfg["folder"])
        hw = self._hardware()
        installed = self._installed()
        language = cfg["language"] or self.game_language()
        recommended = comps.recommend(hw)
        library = {}
        try:
            for row in self._library():
                library[Path(str(row.get("path") or "")).name.lower()] = row
        except Exception:
            library = {}
        mods_dir = self.mods_dir()
        present = {p.name.lower() for p in mods_dir.rglob("*.pak")} if mods_dir and mods_dir.is_dir() else set()
        game = self.game()
        voice = []
        for mod in self.voice_mods():
            work = pipeline.work_dir(folder, mod.bank_id, mod.key)
            hero_name = self._hero_name(mod.hero)
            subs = {}
            for lang in sorted({language, "en"} | _languages_made(work)):
                subs[lang] = self._subtitle_state(work, mod, lang, hero_name, library, present)
            voice.append({**mod.as_dict(), "hero_name": hero_name, "skipped": pipeline.skipped(mod.hero),
                          "subtitles": subs})
        return {
            "folder": str(folder), "free_bytes": _free_bytes(folder),
            "game_found": game is not None, "game_running": self._game_is_running(),
            "downloads_folder": str(self.downloads_dir() or ""), "mods_folder": str(mods_dir or ""),
            "game_language": self.game_language(), "language": language, "language_set": bool(cfg["language"]),
            "languages": [{"code": c, "name": n} for c, n in LANGUAGES.items()],
            "hardware": hw.as_dict(),
            "recognition": {
                "installed": self.recognition_ready(),
                "size": sum(comps.COMPONENTS[c].size for c in comps.RECOGNITION if c not in installed),
                "gpu": {"available": hw.nvidia is not None, "installed": "whisper-cuda" in installed,
                        "on": cfg["gpu_recognition"], "size": comps.COMPONENTS["whisper-cuda"].size},
            },
            "translation": {
                "model": cfg["model"], "ready": self.translation_ready(hw), "engine": comps.engine_for(hw),
                "recommended": recommended,
                "models": [{
                    "id": m.id, "title": m.title, "quality": m.quality, "blurb": m.blurb,
                    "size": comps.COMPONENTS[m.id].size
                    + (0 if comps.engine_for(hw) in installed else comps.COMPONENTS[comps.engine_for(hw)].size),
                    "fit": comps.model_fit(m, hw), "installed": m.id in installed, "recommended": m.id == recommended,
                } for m in comps.MODELS.values()],
            },
            "voice_mods": voice, "scanning": self._scanning, "scan_note": self._scan_note,
            "jobs": self.jobs(), "combined": dict(self._combined),
        }

    def _subtitle_state(self, work: Path, mod: VoiceMod, language: str, hero_name: str,
                        library: Dict[str, dict], present: set) -> dict:
        archive_name, pak_name = subtitle_mod_names(hero_name, mod.name, language)
        downloads = self.downloads_dir()
        made = bool(downloads and (downloads / archive_name).exists())
        summary = self._summary(work, language)
        counts = summary["counts"] if summary else None
        row = library.get(archive_name.lower())
        active = pak_name.lower() in present
        state = "none"
        if made and counts is not None:
            state = "ready" if counts["missing"] == 0 else "partial"
        return {"state": state, "counts": counts, "models": summary["models"] if summary else [],
                "archive": archive_name, "pak": pak_name, "active": active,
                "download_id": row.get("id") if row else None}

    def _summary(self, work: Path, language: str) -> Optional[dict]:
        """How many lines of each kind, and the models that translated them; None before recognition.

        Kept until one of the files it is read from changes: the page asks every second or two.
        """
        tr_file, made_file, edits_file = translation_files(work, language)
        files = (work / "transcript.json", tr_file, made_file, edits_file)
        stamp = tuple(p.stat().st_mtime_ns if p.exists() else 0 for p in files)
        cache_key = (str(work), language)
        cached = self._counts.get(cache_key)
        if cached and cached[0] == stamp:
            return cached[1]
        summary = None
        if stamp[0] and (language == "en" or stamp[1]):
            _lines, counts = subtitle_lines(work, language)
            made = _read(made_file, {}) if language != "en" else {}
            models = sorted({str(m.get("model")) for m in made.values() if isinstance(m, dict) and m.get("model")})
            summary = {"counts": counts, "models": models}
        self._counts[cache_key] = (stamp, summary)
        return summary

    def _game_is_running(self) -> bool:
        looked, running = self._running
        if not looked or time.monotonic() - looked > 5:
            running = bool(self._game_running())
            self._running = (time.monotonic(), running)
        return running


def _languages_made(work: Path) -> set:
    return {p.name.split(".")[1] for p in work.glob("translation.*.json") if p.name.count(".") == 2}


def _free_bytes(folder: Path) -> Optional[int]:
    """Free space on the folder's drive (the folder itself may not exist yet)."""
    path = Path(folder)
    while not path.exists() and path != path.parent:
        path = path.parent
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def _write_source(work: Path, mod: VoiceMod) -> None:
    path = work / "source.json"
    data = _read(path, {})
    if not data.get("pak"):
        data.update({"pak": mod.name, "bank": mod.bank_id})
        path.write_text(json.dumps(data, indent=1), encoding="utf-8")


def _move_contents(old: Path, new: Path) -> None:
    """Move what the old folder holds into the new one (models are gigabytes: moved, not copied, on one drive)."""
    if not old.is_dir():
        return
    for item in old.iterdir():
        target = new / item.name
        if target.exists():
            continue
        shutil.move(str(item), str(target))
    try:
        old.rmdir()
    except OSError:
        pass

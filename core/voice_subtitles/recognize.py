"""What a voice mod says: its sounds decoded and heard by Whisper (whisper.cpp).

heard.json: the words of each sound. transcript.json: every subtitle line
with a status --
  changed     the mod says something else: needs new text
  same        the mod says the game's own words: keep the game's subtitle
  silent      the mod plays a blip of silence instead: the subtitle goes
  not in mod  the line plays a sound this mod does not have
"""
from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.request
import uuid
import wave
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import processes

NO_WINDOW = processes.NO_WINDOW
# A sound this short has no words in it. Mods "switch off" lines by replacing
# them with a blip of silence (every one measured was under 0.23 s), and a
# recogniser fed one invents "Thank you."
SILENT_SECONDS = 0.3
# Interjections a recogniser adds or drops at will.
FILLERS = {"oh", "ah", "aw", "aww", "um", "uh", "hmm", "mm", "mmm", "wow", "ooh", "yeah", "okay", "ok", "hey", "huh"}
# Words a recogniser gets wrong without a hint: names from the game and the
# mods' slang ("Zildos" for "dildos", "Magic" for "Magik").
HINTS = ("Marvel Rivals. Khonshu, Shou-Lao, Knull, Budokan, Hydra, Wakanda, Klyntar, Yggsgard, Psylocke, Magik, "
         "Namor, Jubilee, Gambit, Remy, Ororo, Elsa Bloodstone, Spector, H.E.R.B.I.E. Cum, dildos, futa, bred, MILF.")
VERSION = "whisper.cpp-1"


def normalise(text: str) -> str:
    text = (text or "").lower().replace("’", "'").replace("…", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]+", " ", text)).strip()


def words(text: str) -> List[str]:
    return [w for w in normalise(text).split() if w not in FILLERS]


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalise(a), normalise(b)).ratio()


def same_words(heard: str, game: str) -> bool:
    """The mod's line says what the game's does, give or take an "oh" or a comma."""
    a, b = words(heard), words(game)
    if not a or not b:
        return not a and not b
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= 0.9


def clean(text: str) -> str:
    """Drop the recogniser's stage directions: "*Sigh*", "[laughs]", "(gasps)"."""
    text = re.sub(r"\*[^*]{1,40}\*|\[[^\]]{1,40}\]|\((?:[a-z ]{1,30})\)", " ", text or "", flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def latin(text: str) -> bool:
    return not re.search(r"[^\x00-ɏ‐-…]", text or "")


def wav_seconds(path: Path) -> float:
    with wave.open(str(path)) as f:
        return f.getnframes() / float(f.getframerate())


def decode(work: Path, vgmstream: Path, cancelled: Callable[[], bool] = lambda: False,
           progress: Callable[[int, int], None] = lambda done, total: None) -> int:
    """wem/<id>.wem -> wav/<id>.wav with vgmstream. A sound it cannot read gets no .wav."""
    (work / "wav").mkdir(exist_ok=True)
    wems = sorted((work / "wem").glob("*.wem"))
    done = 0
    for n, wem in enumerate(wems, 1):
        if cancelled():
            break
        wav = work / "wav" / f"{wem.stem}.wav"
        if not wav.exists():
            part = wav.with_name(f"{wem.stem}.part.wav")  # a run stopped halfway leaves no broken .wav
            try:
                # Paths relative to the work folder: vgmstream, too, reads ANSI arguments.
                subprocess.run([str(vgmstream), "-o", f"wav/{part.name}", f"wem/{wem.name}"], cwd=str(work),
                               capture_output=True, check=True, creationflags=NO_WINDOW, timeout=120)
                part.replace(wav)
                done += 1
            except (OSError, subprocess.SubprocessError):
                part.unlink(missing_ok=True)
        progress(n, len(wems))
    return done


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class WhisperServer:
    """whisper.cpp's server with the model loaded once for all of a mod's sounds."""

    def __init__(self, exe: Path, model: Path, threads: Optional[int] = None, log: Optional[Path] = None):
        self.exe, self.model = Path(exe), Path(model)
        self.threads = threads or max(1, min(16, (os.cpu_count() or 4)))
        self.log = log
        self.port = 0
        self.proc: Optional[subprocess.Popen] = None
        self._out = None

    def __enter__(self) -> "WhisperServer":
        self.port = _free_port()
        out = self._out = open(self.log, "w", encoding="utf-8") if self.log else None
        # whisper.cpp reads its arguments in the ANSI code page, so a model under a
        # user folder named in Cyrillic would not open: it is named from its own folder.
        self.proc = processes.start(
            [str(self.exe), "-m", self.model.name, "--host", "127.0.0.1", "--port", str(self.port),
             "-t", str(self.threads), "-bs", "5", "-l", "en"],
            stdout=out or subprocess.DEVNULL, stderr=subprocess.STDOUT, cwd=str(self.model.parent))
        deadline = time.time() + 180
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("the speech recogniser stopped while starting")
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=2)
                return self
            except Exception:
                time.sleep(0.5)
        self.__exit__()
        raise RuntimeError("the speech recogniser did not start")

    def __exit__(self, *exc) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self._out is not None:
            self._out.close()
            self._out = None

    def hear(self, wav: Path, prompt: Optional[str]) -> str:
        boundary = uuid.uuid4().hex
        fields = {"response_format": "json", "temperature": "0", "language": "en"}
        if prompt:
            fields["prompt"] = prompt
        body = b"".join(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
                        for k, v in fields.items())
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"sound.wav\"\r\n"
                 "Content-Type: audio/wav\r\n\r\n").encode() + wav.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/inference", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=600) as r:
            return clean(json.loads(r.read()).get("text", ""))


def _choose(server: WhisperServer, wav: Path, seconds: float, game_line: Optional[str]) -> str:
    """Hear a sound with the game's own line as a hint, and check the answer.

    The game's line fixes most names (Erik, Cyke, Arakko, ankh) since the mod
    usually rewrites around it, but now and then the recogniser then skips the
    first sentence or answers in another language; the sound is heard again
    with the general hint only, and the fuller answer kept.
    """
    guided = server.hear(wav, f"{HINTS} {game_line}".strip() if game_line else HINTS)
    suspicious = not guided or not latin(guided) or (seconds >= 2.5 and len(words(guided)) < seconds * 0.9)
    if not suspicious:
        return guided
    plain = server.hear(wav, HINTS)
    if not latin(plain):
        plain = server.hear(wav, None)
    if not latin(guided) or len(words(plain)) > len(words(guided)):
        return plain if latin(plain) else ""
    return guided


def hear_sounds(work: Path, server_factory: Callable[[], WhisperServer],
                progress: Callable[[int, int], None] = lambda done, total: None,
                cancelled: Callable[[], bool] = lambda: False) -> int:
    """Fill heard.json for every sound the subtitle lines play; returns how many were heard now."""
    mapping = json.loads((work / "map.json").read_text(encoding="utf-8"))
    heard_file = work / "heard.json"
    heard: Dict[str, dict] = json.loads(heard_file.read_text(encoding="utf-8")) if heard_file.exists() else {}
    game_line = {str(m): line["en"] for line in mapping["lines"] for m in line["media"]}
    todo = [m for m in sorted({m for line in mapping["lines"] for m in line["media"]}) if str(m) not in heard]
    spoken = []
    for media in todo:
        wav = work / "wav" / f"{media}.wav"
        try:
            seconds = wav_seconds(wav)
        except (OSError, EOFError, wave.Error):
            heard[str(media)] = {"text": "", "seconds": 0.0, "unreadable": True}
            continue
        if seconds < SILENT_SECONDS:
            heard[str(media)] = {"text": "", "seconds": round(seconds, 2)}
        else:
            spoken.append((media, wav, seconds))
    _save(heard_file, heard)
    if not spoken:
        return 0
    with server_factory() as server:
        for n, (media, wav, seconds) in enumerate(spoken, 1):
            if cancelled():
                break
            text = _choose(server, wav, seconds, game_line.get(str(media)))
            heard[str(media)] = {"text": text, "seconds": round(seconds, 2), "asr": VERSION}
            if n % 10 == 0 or n == len(spoken):
                _save(heard_file, heard)
            progress(n, len(spoken))
    _save(heard_file, heard)
    return len(spoken)


def _save(path: Path, data) -> None:
    staged = path.with_name(path.name + ".new")
    staged.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    staged.replace(path)


def classify(work: Path) -> Dict[str, int]:
    mapping = json.loads((work / "map.json").read_text(encoding="utf-8"))
    heard = json.loads((work / "heard.json").read_text(encoding="utf-8"))
    rows = []
    for line in mapping["lines"]:
        takes = [heard[str(m)] for m in line["media"] if str(m) in heard and not heard[str(m)].get("unreadable")]
        base = {k: line[k] for k in ("namespace", "key", "line", "en")}
        if not line["media"]:
            rows.append({**base, "heard": None, "status": "not in mod"})
            continue
        if not takes:  # none of its sounds could be read: not silence, so the game's subtitle stays
            rows.append({**base, "heard": None, "status": "unreadable"})
            continue
        spoken = [t for t in takes if t["seconds"] >= SILENT_SECONDS]
        if not spoken:
            rows.append({**base, "heard": "", "status": "silent"})
            continue
        best = max((t["text"] for t in spoken), key=lambda t: similarity(t, line["en"] or ""))
        rows.append({**base, "heard": best, "status": "same" if same_words(best, line["en"] or "") else "changed"})
    _save(work / "transcript.json", rows)
    return {s: sum(1 for r in rows if r["status"] == s) for s in ("changed", "same", "silent", "not in mod", "unreadable")}


def drop_sounds(work: Path) -> None:
    """The decoded sounds take ~200 MB a mod and are not needed once heard."""
    for name in ("wav", "wem"):
        shutil.rmtree(work / name, ignore_errors=True)

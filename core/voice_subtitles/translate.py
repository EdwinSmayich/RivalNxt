"""Translating what a voice mod says, with a local model run by llama.cpp's server.

One line per request -- batches of lines in one request came back with the
right count but now and then one line dropped and another doubled, so every
translation after it sat on the wrong subtitle -- with several requests in
flight at once: the model's weights are read once per step however many
lines the step carries.
"""
from __future__ import annotations

import json
import re
import socket
import subprocess
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import processes


SYSTEM = """You translate voice-line subtitles for a fan-made audio mod of the video game Marvel Rivals, from English into {language}.
The mod was made by its author for adult players and some lines are crude or sexual. Translate faithfully: keep profanity and sexual language as it is, do not soften, censor, explain or comment.
The speaker is {speaker}. {gender}
Each line comes with the game's official English line and its official {language} translation. They are for reference only -- names of heroes, places and game terms, and to recognise puns on the original line. The mod's line almost always says something different: translate the mod's line, never copy the official translation.
The mod's line was taken down by speech recognition and now and then a word is misheard ("Zildos" for "dildos", "come" for "cum"): translate what the speaker most likely said.

Rules:
- Translate the meaning, as a native speaker would say it out loud, not word for word. Keep it short.
- Write only in {language}. Never leave English words, except names and titles (K-pop, Final Fantasy).
- Never add anything that is not in the English line: no violence, no force, no extra content.
- Units: convert inches to centimetres (1 inch = 2.54 cm).
- The person spoken to is a man unless the line itself makes clear it is a woman{listener_example}.
- Names and game terms: when the official translation has the name or term, spell it exactly as there.
- The examples of similar lines show style and vocabulary only. Never answer with an example's translation: translate the line given.
{voice}
Answer with the translation only."""

FEMININE = "The speaker is a woman: use feminine grammatical forms whenever the speaker refers to herself{example}."
MASCULINE = "The speaker is a man: use masculine grammatical forms whenever the speaker refers to himself."

# Per-language help: words a model otherwise leaves in English or gets wrong,
# and a few lines in the voice wanted. Only the words a line has go into its
# prompt; the whole list made every prompt 500 tokens longer.
TERMS: Dict[str, List[Tuple[str, str]]] = {
    "ru": [
        ("gangbang", "групповуха"), ("run a train", "пустить по кругу"), ("orgy", "оргия"),
        ("threesome", "секс втроём"), ("fuck", "трахать(ся)"), ("fuck! (exclamation)", "бля! / чёрт!"),
        ("suck off", "отсосать"), ("blow", "отсосать"), ("blowjob", "минет"), ("blowbang", "групповой минет"),
        ("deep throat", "глубокая глотка"), ("cum (verb)", "кончать"), ("cum (noun)", "сперма"), ("load", "порция спермы"),
        ("pre-cum", "смазка"), ("money shot", "финальный выстрел"), ("cock", "член"), ("dick", "член"),
        ("pussy", "киска"), ("ass", "задница"), ("tits", "сиськи"), ("whore", "шлюха"), ("slut", "шлюшка"),
        ("stud", "жеребец"), ("hung", "хорошо оснащённый"), ("horny", "возбуждённая"), ("wet (aroused)", "мокрая, теку"),
        ("spit-roast", "брать с двух сторон"), ("glory hole", "глори-хол"), ("lube", "смазка"),
        ("condom", "презерватив"), ("thong", "стринги"), ("twerk", "тверк"), ("bukkake", "буккаке"),
        ("dildo", "дилдо"), ("futa", "футанари"), ("breeding grounds", "место для размножения"),
        ("breed", "размножаться, обрюхатить"), ("encore", "на бис"), ("bang bus", "секс-автобус"),
        ("love train", "паровозик (групповой секс)"), ("pound (sex)", "трахать, долбить"),
        ("pound town", "как следует оттрахать"), ("let someone hit", "дать (переспать)"),
        ("clap cheeks", "шлёпать по попке"), ("doggy style", "по-собачьи, раком"), ("ankh", "анкх"),
        ("amplifier", "усилитель"), ("glow up", "похорошеть"),
    ],
}
VOICE: Dict[str, List[Tuple[str, str]]] = {
    "ru": [
        ("Fill me up, everyone!", "Наполните меня, все!"),
        ("You like me coming on your face?", "Нравится, когда я кончаю тебе на лицо?"),
        ("Let's celebrate with a blowbang!", "Отметим это групповым минетом!"),
        ("Time to get back in that orgy. I'm not done getting stuffed yet.",
         "Пора обратно в оргию. Меня ещё не до конца заполнили."),
        ("Thanks so much. This fat ass is all yours tonight.", "Спасибо огромное! Сегодня ночью эта толстая задница вся твоя."),
    ],
}
FEMININE_EXAMPLE = {"ru": ' (for example "я сделала", "я готова")'}
LISTENER_EXAMPLE = {"ru": ': "ты похорошел", "ты думал"'}

# Names that are also ordinary words: only a name inside a sentence counts.
COMMON_WORDS = {"Strange", "Storm", "Doom", "Venom", "Angela", "Jean", "Sue", "Victor"}
# Latin letters in a subtitle meant to be in another script, beyond titles the
# game itself writes in Latin.
LATIN_WORD = re.compile(r"[A-Za-z]{3,}")
ALLOWED_LATIN = re.compile(r"K-pop|Final Fantasy|4L1T|Insta|Party City", re.IGNORECASE)
# Letters of other Cyrillic alphabets that slip into Russian ("Нікогда").
FOREIGN_CYRILLIC = re.compile(r"[іїєґўІЇЄҐЎ]")
LATIN_SCRIPT = {"en", "de", "fr", "es-ES", "es-419", "it", "pl", "pt-BR", "tr", "id", "vi"}


def names_in(text: str, names: Optional[Dict[str, str]]) -> List[Tuple[str, str]]:
    """The game's own spelling of every name the line mentions."""
    found = []
    for english, local in (names or {}).items():
        for m in re.finditer(r"(?<![\w-])" + re.escape(english) + r"(?![\w-])", text or ""):
            before = (text[:m.start()].rstrip() or ".")[-1]
            if english in COMMON_WORDS and before in ".!?…":
                continue
            found.append((english, local))
            break
    # "Black Widow" and "Widow" both match: the longer name is enough.
    return [(e, local) for e, local in found if not any(e != o and e in o for o, _ in found)]


def terms_in(text: str, language: str) -> List[Tuple[str, str]]:
    low = (text or "").lower()
    found = []
    for en, local in TERMS.get(language, []):
        word = re.sub(r"\s*\(.*\)", "", en).rstrip("!")
        if re.search(r"\b" + re.escape(word) + r"(?:s|es|ed|ing|er|ers|y)?\b", low):
            found.append((en, local))
    return found


def needs_retry(text: str, language: str) -> bool:
    if not text:
        return True
    if language not in LATIN_SCRIPT and LATIN_WORD.search(ALLOWED_LATIN.sub("", text)):
        return True
    return language == "ru" and bool(FOREIGN_CYRILLIC.search(text))


def copied_example(text: str, item: dict) -> bool:
    """The model answered with one of the examples instead of the line."""
    return any(text == local and en.strip().lower() != item["heard"].strip().lower()
               for en, local in item.get("examples") or [])


def system_prompt(language: str, language_name: str, speaker: str, feminine: bool) -> str:
    voice = VOICE.get(language)
    return SYSTEM.format(
        language=language_name, speaker=speaker,
        gender=FEMININE.format(example=FEMININE_EXAMPLE.get(language, "")) if feminine else MASCULINE,
        listener_example=LISTENER_EXAMPLE.get(language, ""),
        voice=("\nExamples of the voice wanted:\n" + "".join(f"\"{en}\" -> \"{local}\"\n" for en, local in voice))
        if voice else "",
    )


def user_prompt(item: dict) -> str:
    examples = item.get("examples") or []
    shown = "".join(f"- \"{en}\" -> \"{local}\"\n" for en, local in examples)
    names = "; ".join(f"{en} = {local}" for en, local in item.get("names") or [])
    terms = "; ".join(f"{en} -> {local}" for en, local in item.get("terms") or [])
    return (
        (f"Similar lines already translated, for style and vocabulary:\n{shown}\n" if shown else "")
        + (f"Vocabulary to use: {terms}\n" if terms else "")
        + (f"Names in this line as the game spells them (decline as grammar needs): {names}\n" if names else "")
        + f"Official English line it replaces: {item.get('game_en') or ''}\n"
        f"Official translation of that line: {item.get('game_local') or ''}\n"
        f"Line to translate: {item['heard']}\n"
        "Answer with the translation only, on one line, without quotes."
    )


class Memory:
    """Lines the user corrected by hand, shown to the model as examples for similar lines."""

    STOP = {"the", "a", "an", "to", "of", "and", "i", "you", "me", "my", "your", "it", "is", "in", "on", "for", "this",
            "that", "be", "with", "at", "so", "we", "are", "i'm", "it's", "just", "all", "do", "get"}

    def __init__(self, pairs: Sequence[Tuple[str, str]] = ()):
        self.pairs = list(pairs)

    @staticmethod
    def _words(text: str) -> set:
        return {w for w in re.findall(r"[a-z0-9']+", (text or "").lower()) if w not in Memory.STOP}

    def closest(self, text: str, k: int = 6) -> List[Tuple[str, str]]:
        mine = self._words(text)
        if not mine:
            return []
        scored = []
        for en, local in self.pairs:
            theirs = self._words(en)
            if theirs and (overlap := len(mine & theirs) / len(mine | theirs)) > 0:
                scored.append((overlap, en, local))
        scored.sort(key=lambda t: -t[0])
        return [(en, local) for _o, en, local in scored[:k] if en.strip().lower() != (text or "").strip().lower()]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LlamaServer:
    """llama.cpp's server with a translation model loaded."""

    def __init__(self, exe: Path, args: List[str], parallel: int, thinking: bool,
                 sampling: Optional[dict] = None, log: Optional[Path] = None):
        self.exe = Path(exe)
        self.args = list(args)
        self.parallel = max(1, parallel)
        self.thinking = thinking
        self.sampling = sampling or {"temperature": 0.3, "top_p": 0.95, "top_k": 64}
        self.log = log
        self.port = 0
        self.proc: Optional[subprocess.Popen] = None
        self._out = None

    def __enter__(self) -> "LlamaServer":
        self.port = _free_port()
        out = self._out = open(self.log, "w", encoding="utf-8") if self.log else None
        self.proc = processes.start(
            [str(self.exe), *self.args, "--host", "127.0.0.1", "--port", str(self.port), "--jinja",
             "-np", str(self.parallel), "--no-webui"],
            stdout=out or subprocess.DEVNULL, stderr=subprocess.STDOUT, cwd=str(self.exe.parent))
        deadline = time.time() + 900
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("the translation model stopped while loading (see llama-server.log)")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=2) as r:
                    if json.loads(r.read()).get("status") == "ok":
                        return self
            except Exception:
                time.sleep(1)
        self.__exit__()
        raise RuntimeError("the translation model did not load in 15 minutes")

    def __exit__(self, *exc) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self._out is not None:
            self._out.close()
            self._out = None

    def chat(self, system: str, prompt: str, temperature: Optional[float] = None) -> str:
        body = {
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            **self.sampling,
            "max_tokens": 1100 if self.thinking else 256,
            "chat_template_kwargs": {"enable_thinking": self.thinking},
        }
        if temperature is not None:
            body["temperature"] = temperature
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/v1/chat/completions",
                                     data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=900) as r:
            answer = json.loads(r.read())
        text = answer["choices"][0]["message"].get("content") or ""
        if "</think>" in text:
            text = text.split("</think>", 1)[1]
        text = text.strip().splitlines()[0].strip() if text.strip() else ""
        return text.strip('"«»“” ')

    def translate(self, items: List[dict], *, language: str, language_name: str, speaker: str, feminine: bool,
                  names: Optional[Dict[str, str]] = None, memory: Optional[Memory] = None,
                  progress: Callable[[int, int], None] = lambda done, total: None,
                  cancelled: Callable[[], bool] = lambda: False) -> List[Optional[str]]:
        """items: {"heard", "game_en", "game_local"}. A line skipped on cancel comes back as None."""
        system = system_prompt(language, language_name, speaker, feminine)
        done, lock = [0], threading.Lock()

        def one(item: dict) -> Optional[str]:
            if cancelled():
                return None
            item = {**item, "examples": memory.closest(item["heard"]) if memory else [],
                    "names": names_in(item["heard"], names), "terms": terms_in(item["heard"], language)}
            text = self.chat(system, user_prompt(item))
            for attempt in range(2):
                if copied_example(text, item):
                    item = {**item, "examples": []}  # without them there is nothing to copy
                elif not needs_retry(text, language):
                    break
                # The same line with a little more freedom usually finds the word.
                text = self.chat(system, user_prompt(item), temperature=0.6 + 0.2 * attempt)
            with lock:
                done[0] += 1
                progress(done[0], len(items))
            return text

        with ThreadPoolExecutor(max_workers=self.parallel) as pool:
            return list(pool.map(one, items))

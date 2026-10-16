"""What the game itself says: its subtitle text, its voice events, its heroes.

Everything here is read from the game's own containers and cached under the
voice-subtitles folder, keyed by the container's date, so a game patch is
picked up on its own and nothing is read twice.
"""
from __future__ import annotations

import configparser
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Marvel Rivals' pak key, the same default the app keeps in its settings.
DEFAULT_AES = "0x0C263D8C22DCB085894899C3A3796383E9BF9DE0CBFB08C9BF2DEF2E84F29D74"
LOCRES_PAK = "pakchunkLocres-Windows.pak"
WWISE_UTOC = "pakchunkWwise-Windows.utoc"

# UE culture codes the game ships subtitles for, and their English names (the
# translator is told the language by name).
LANGUAGES: Dict[str, str] = {
    "en": "English", "ru": "Russian", "de": "German", "fr": "French", "es-ES": "Spanish",
    "es-419": "Latin American Spanish", "it": "Italian", "pl": "Polish", "pt-BR": "Brazilian Portuguese",
    "tr": "Turkish", "ja": "Japanese", "ko": "Korean", "zh-Hans": "Simplified Chinese",
    "zh-Hant": "Traditional Chinese", "th": "Thai", "ar": "Arabic", "id": "Indonesian", "vi": "Vietnamese",
}
# The tag a subtitle mod's name starts with ("RU Subtitles - ..."); one per language.
LANGUAGE_TAGS: Dict[str, str] = {
    code: {"es-ES": "ES", "es-419": "LAS", "pt-BR": "PT", "zh-Hans": "CHS", "zh-Hant": "CHT"}.get(code, code.upper())
    for code in LANGUAGES
}
_CULTURE_ALIASES = {"es": "es-ES", "es-mx": "es-419", "pt": "pt-BR", "zh": "zh-Hans", "zh-cn": "zh-Hans",
                    "zh-sg": "zh-Hans", "zh-tw": "zh-Hant", "zh-hk": "zh-Hant", "zh-mo": "zh-Hant"}


def known_language(culture: str) -> Optional[str]:
    """One of LANGUAGES for a UE culture code ("ru", "en-US", "zh-CN"), or None."""
    culture = (culture or "").strip().replace("_", "-")
    by_lower = {code.lower(): code for code in LANGUAGES}
    lower = culture.lower()
    if lower in by_lower:
        return by_lower[lower]
    if lower in _CULTURE_ALIASES:
        return _CULTURE_ALIASES[lower]
    base = lower.split("-")[0]
    return by_lower.get(base) or _CULTURE_ALIASES.get(base)


def user_settings_file() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Marvel" / "Saved" / "Config" / "Windows" / "GameUserSettings.ini"


def game_language(settings_file: Optional[Path] = None) -> str:
    """The language the game shows text in ("Culture" in its user settings), or "en"."""
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        parser.read(settings_file or user_settings_file(), encoding="utf-8")
        for section in parser.sections():
            culture = known_language(parser.get(section, "Culture", fallback=""))
            if culture:
                return culture
    except Exception:
        pass
    return "en"


def _quiet(fn, *args, **kwargs):
    """rust_ue_tools prints every path it touches to the process's stdout."""
    try:
        sink = open(os.devnull, "w")
        saved = os.dup(1)
    except OSError:
        return fn(*args, **kwargs)
    os.dup2(sink.fileno(), 1)
    try:
        return fn(*args, **kwargs)
    finally:
        os.dup2(saved, 1)
        os.close(saved)
        sink.close()


class Game:
    """One installation of the game, with a cache folder for what is read from it."""

    def __init__(self, paks_dir: Path, cache_dir: Path, aes_key: str = DEFAULT_AES):
        self.paks = Path(paks_dir)
        self.cache = Path(cache_dir)
        self.aes = aes_key or DEFAULT_AES
        self._locres: Dict[str, object] = {}

    # ------------------------------------------------------------ text
    def _locres_stamp(self) -> int:
        return int((self.paks / LOCRES_PAK).stat().st_mtime)

    def locres_file(self, language: str) -> Path:
        """The game's own Game.locres for a language, extracted once per game version."""
        stamp = self._locres_stamp()
        root = self.cache / f"locres-{stamp}"
        target = root / language / "Game.locres"
        if not target.exists():
            import rust_ue_tools

            tmp = Path(tempfile.mkdtemp(prefix="rivalnxt_loc_"))
            try:
                _quiet(rust_ue_tools.PyUnpacker().unpack_pak, str(self.paks / LOCRES_PAK), str(tmp),
                       aes_key=self.aes, force=True, quiet=True)
                for found in tmp.rglob("Game.locres"):
                    dest = root / found.parent.name / "Game.locres"
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(found, dest)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            # Older game versions' copies are no use any more.
            for old in self.cache.glob("locres-*"):
                if old != root:
                    shutil.rmtree(old, ignore_errors=True)
        if not target.exists():
            raise FileNotFoundError(f"the game has no subtitles in {language!r}")
        return target

    def languages(self) -> List[str]:
        self.locres_file("en")
        return sorted(p.parent.name for p in (self.cache / f"locres-{self._locres_stamp()}").glob("*/Game.locres"))

    def locres(self, language: str):
        """The game's text for a language, parsed (pylocres.LocresFile); cached while the game is unchanged."""
        from pylocres import LocresFile

        path = self.locres_file(language)
        key = f"{language}:{path.parent.parent.name}"
        if key not in self._locres:
            lf = LocresFile()
            lf.read(str(path))
            self._locres = {k: v for k, v in self._locres.items() if k.split(":")[1] == path.parent.parent.name}
            self._locres[key] = lf
        return self._locres[key]

    # ------------------------------------------------------------ voice events
    def voice_events(self) -> List[str]:
        """Paths of every Wwise event in the game's sound container."""
        utoc = self.paks / WWISE_UTOC
        cache = self.cache / f"wwise-events-{int(utoc.stat().st_mtime)}.json"
        if not cache.exists():
            import rust_ue_tools

            paths = _quiet(lambda: [a.path for a in rust_ue_tools.PyUnpacker().list_utoc(
                str(utoc), aes_key=self.aes, json_format=False)])
            for old in self.cache.glob("wwise-events-*.json"):
                old.unlink(missing_ok=True)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(paths), encoding="utf-8")
        return json.loads(cache.read_text(encoding="utf-8"))

    # ------------------------------------------------------------ heroes
    def hero_name(self, hero: str, language: str = "en") -> str:
        lf = self.locres(language)
        entries = lf.namespaces.get(f"601_HeroUIAsset_{hero}_ST")
        names = {key: (entry.translation or "").strip() for key, entry in (entries.entrys.items() if entries else [])}
        name = (next((v for k, v in names.items() if v and k.endswith(("HeroBasic_TName", "HeroInfo_TName"))), None)
                or next((v for k, v in names.items() if v and k.endswith(f"_{hero}0000_SkinInfo_SkinName")), None)
                or hero)
        return _title(name)

    def hero_is_female(self, hero: str) -> bool:
        """From the game's Russian biography of the hero -- pronouns and past tenses.

        The hero's own Russian lines are no guide: some are translated in the
        wrong gender (Phoenix speaks as a man in many of them). A hero with a
        skin whose own lines speak as a woman (Lady Loki) counts as female: a
        voice mod for that hero is that skin's voice.
        """
        try:
            ru = self.locres("ru")
        except FileNotFoundError:
            return False
        bio = ru.namespaces.get(f"601_HeroUIAsset_{hero}_ST")
        text = " ".join(entry.translation or "" for key, entry in (bio.entrys.items() if bio else [])
                        if re.search(r"HeroBasic_Desc|Biography|HeroSpciality", key))
        if len(_SHE.findall(text)) > len(_HE.findall(text)):
            return True
        for ns, voice in ru.namespaces.items():
            if re.fullmatch(rf"122_HeroVoice_{hero}\d{{3}}_ST", ns):
                lines = " ".join(entry.translation or "" for entry in voice.entrys.values())
                if len(_I_SHE.findall(lines)) > len(_I_HE.findall(lines)):
                    return True
        return False

    def speaker(self, hero: str, language: str) -> Tuple[str, bool]:
        """(the hero's name in the language, whether the voice is a woman's)."""
        try:
            name = self.hero_name(hero, language)
        except FileNotFoundError:
            name = self.hero_name(hero, "en")
        return name, self.hero_is_female(hero)

    def english_hero_name(self, hero: str) -> str:
        """As the library files mods under it; "Lady Loki" for her voice."""
        name = self.hero_name(hero, "en")
        if name == "Loki" and self.hero_is_female(hero):
            return "Lady Loki"
        return name

    def names(self, language: str) -> Dict[str, str]:
        """English name -> the game's own spelling in the language, with each hero's gender.

        A hero's gender travels with the name: "Феникс" alone left a model
        writing "ты такой сексуальный" to Phoenix.
        """
        en = self.locres("en")
        try:
            target = self.locres(language)
        except FileNotFoundError:
            return {}
        out: Dict[str, str] = {}
        for ns, entries in en.namespaces.items():
            if not re.fullmatch(r"601_HeroUIAsset_\d{4}_ST", ns) or ns not in target.namespaces:
                continue
            hero = ns.split("_")[2]
            gender = "a woman" if self.hero_is_female(hero) else "a man"
            theirs = target.namespaces[ns].entrys
            for key, entry in entries.entrys.items():
                if (re.search(r"(HeroBasic_TName|HeroInfo_TName|RealName|\d{4}0000_SkinInfo_SkinName)$", key)
                        and entry.translation and key in theirs and theirs[key].translation):
                    english = _title(entry.translation.strip())
                    if re.search(r"npc|bot|drone|^original$", english, re.IGNORECASE):
                        continue
                    local = theirs[key].translation.strip()
                    if local.isupper():
                        local = re.sub(r"\b(И|And)\b", lambda m: m.group(1).lower(), _title(local))
                    out[english] = local if "&" in english else f"{local} ({gender})"
        for english, local in EXTRA_NAMES.get(language, {}).items():
            out.setdefault(english, local)
        return out


def _title(name: str) -> str:
    return name.title() if name.isupper() else name


# Words that give away a woman or a man in the game's Russian biography of a
# hero: pronouns and past-tense verbs; and the same in a hero's own lines.
_SHE = re.compile(r"\b(?:она|её|ее|ей|ней|неё)\b|\b\w+(?:лась|ла)\b", re.IGNORECASE)
_HE = re.compile(r"\b(?:он|его|ему|него|нему)\b|\b\w+[аеиоуыя](?:лся|л)\b", re.IGNORECASE)
_FILL = r"(?:(?:не|уже|же|бы|тоже|ведь|всегда|только|просто|так|ещё|еще|и|вот|давно|никогда|точно|наконец)\s+){0,2}"
_I_SHE = re.compile(r"\bя\s+" + _FILL + r"(?:\w+(?:ла|лась)|готова|рада|должна|уверена|сама|одна)\b", re.IGNORECASE)
_I_HE = re.compile(r"\bя\s+" + _FILL + r"(?:\w+[аеиоуыя](?:л|лся)|готов|рад|должен|уверен|сам|один)\b", re.IGNORECASE)

# Names the game's hero list does not have, as its Russian lines spell them.
EXTRA_NAMES: Dict[str, Dict[str, str]] = {
    "ru": {
        "Knull": "Налл", "Khonshu": "Хонсу", "Shou-Lao": "Шоу-Лао", "Arakko": "Аракко", "Krakoa": "Кракоа",
        "Yggsgard": "Иггсгард", "Klyntar": "Клинтар", "Budokan": "Будокан", "Galacta": "Галакта",
        "H.E.R.B.I.E.": "Г.Е.Р.Б.И.", "Herbie": "Г.Е.Р.Б.И.", "Cyke": "Сайк", "Illyana": "Ильяна", "Ororo": "Ороро",
        "Erik": "Эрик", "Logan": "Логан", "Jean": "Джин", "Remy": "Реми", "Wade": "Уэйд", "Sue": "Сью",
        "Johnny": "Джонни", "Wanda": "Ванда", "Bucky": "Баки", "Hydra": "Гидра", "Apocalypse": "Апокалипсис",
        "Dracula": "Дракула", "Xavier": "Ксавьер", "Doom": "Дум", "Victor": "Виктор", "Spector": "Спектор",
        "Strange": "Стрэндж", "Stark": "Старк", "Cajun": "Каджун", "Fujikawa": "Фудзикава", "Tokyo 2099": "Токио 2099",
    },
}

"""Hearing a voice mod (recognition) and translating it, with stand-ins for the models."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from core.voice_subtitles import recognize as rec
from core.voice_subtitles import translate as tr
from voice_subtitles_fakes import NS, key


class TestRecognition:
    def test_stage_directions_are_dropped(self):
        assert rec.clean("*Sigh* Three guns down. [laughs]") == "Three guns down."
        assert rec.clean("Hmm (gasps) what?") == "Hmm what?"

    def test_latin(self):
        assert rec.latin("Can't fuck 'em all, Cajun! Soirées… — yes")
        assert not rec.latin("你好")

    def test_same_words_ignores_fillers_and_punctuation(self):
        assert rec.same_words("Oh, I'll tell you when I'm ready, yeah?", "I'll tell you when I'm ready.")
        assert not rec.same_words("I'll tell you when I'm dripping.", "I'll tell you when I'm ready.")

    class Server:
        def __init__(self, answers):
            self.answers, self.prompts = list(answers), []

        def hear(self, wav, prompt):
            self.prompts.append(prompt)
            return self.answers.pop(0)

    def test_the_guided_answer_is_kept_when_it_looks_right(self):
        server = self.Server(["Get up, Magik."])
        assert rec._choose(server, None, 1.5, "Get up, Magik!") == "Get up, Magik."
        assert "Get up, Magik!" in server.prompts[0]

    def test_an_answer_in_another_language_is_heard_again(self):
        server = self.Server(["你好", "Hello!"])
        assert rec._choose(server, None, 1.0, "Hi!") == "Hello!"

    def test_a_first_sentence_skipped_is_heard_again(self):
        server = self.Server(["Naked, with everyone watching.",
                              "Up to me to finish what Big Blue started. Naked, with everyone watching."])
        assert rec._choose(server, None, 6.0, "Up to me...").startswith("Up to me")

    def test_classify(self, tmp_path):
        mapping = {"lines": [
            {"namespace": NS, "key": key("1"), "line": "1", "en": "Hello!", "media": [1]},
            {"namespace": NS, "key": key("2"), "line": "2", "en": "Bye!", "media": [2]},
            {"namespace": NS, "key": key("3"), "line": "3", "en": "Go!", "media": [3]},
            {"namespace": NS, "key": key("4"), "line": "4", "en": "Run!", "media": []},
        ]}
        heard = {"1": {"text": "Hello there, darling!", "seconds": 1.2},
                 "2": {"text": "", "seconds": 0.05},
                 "3": {"text": "Oh, go!", "seconds": 0.8}}
        (tmp_path / "map.json").write_text(json.dumps(mapping))
        (tmp_path / "heard.json").write_text(json.dumps(heard))
        assert rec.classify(tmp_path) == {"changed": 1, "same": 1, "silent": 1, "not in mod": 1, "unreadable": 0}
        rows = {r["key"]: r for r in json.loads((tmp_path / "transcript.json").read_text())}
        assert rows[key("1")]["heard"] == "Hello there, darling!"

    def test_a_sound_that_cannot_be_read_is_not_silence(self, tmp_path):
        import subprocess
        import wave

        (tmp_path / "wem").mkdir()
        for media in (1, 2):
            (tmp_path / "wem" / f"{media}.wem").write_bytes(b"x")
        mapping = {"lines": [
            {"namespace": NS, "key": key("1"), "line": "1", "en": "Hello!", "media": [1]},
            {"namespace": NS, "key": key("2"), "line": "2", "en": "Bye!", "media": [2]},
        ]}
        (tmp_path / "map.json").write_text(json.dumps(mapping))

        def vgmstream(args, cwd, **_k):
            # Relative paths only: vgmstream reads its arguments in the ANSI code page.
            assert all(not Path(a).is_absolute() for a in args[1:])
            out, wem = Path(cwd) / args[2], args[3]
            if wem.endswith("2.wem"):
                raise subprocess.CalledProcessError(1, args)
            with wave.open(str(out), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(1000)
                w.writeframes(b"\0\0" * 50)  # 0.05 s: silence

        seen = []
        original = rec.subprocess.run
        rec.subprocess.run = vgmstream
        try:
            assert rec.decode(tmp_path, tmp_path / "vgmstream.exe", progress=lambda d, t: seen.append((d, t))) == 1
        finally:
            rec.subprocess.run = original
        assert seen[-1] == (2, 2) and not list((tmp_path / "wav").glob("*.part.wav"))

        rec.hear_sounds(tmp_path, server_factory=lambda: None)
        assert rec.classify(tmp_path)["unreadable"] == 1
        rows = {r["key"]: r for r in json.loads((tmp_path / "transcript.json").read_text())}
        assert rows[key("1")]["status"] == "silent" and rows[key("2")]["status"] == "unreadable"


class TestTranslationHelpers:
    NAMES = {"Rogue": "Шельма (a woman)", "Strange": "Стрэндж", "Black Widow": "Черная Вдова (a woman)",
             "Widow": "Вдова"}

    def test_names_in_a_line(self):
        assert tr.names_in("Survive, Rogue!", self.NAMES) == [("Rogue", "Шельма (a woman)")]
        assert tr.names_in("Strange little monsters.", self.NAMES) == []  # an ordinary word here
        assert tr.names_in("New Strange's glory holes!", self.NAMES) == [("Strange", "Стрэндж")]
        assert tr.names_in("Black Widow is here.", self.NAMES) == [("Black Widow", "Черная Вдова (a woman)")]

    def test_vocabulary_in_a_line(self):
        found = dict(tr.terms_in("Keep fucking! Five cocks and a gangbang.", "ru"))
        assert {"fuck", "cock", "gangbang"} <= set(found)
        assert tr.terms_in("Keep fucking!", "de") == []

    def test_what_needs_another_try(self):
        assert tr.needs_retry("", "ru")
        assert tr.needs_retry("Это fucking круто", "ru")
        assert tr.needs_retry("Нікогда", "ru")
        assert not tr.needs_retry("Обожаю K-pop!", "ru")
        assert not tr.needs_retry("Das ist super", "de")

    def test_the_prompt_speaks_of_the_speaker(self):
        ru = tr.system_prompt("ru", "Russian", "Луна Сноу", True)
        assert "Луна Сноу" in ru and "я сделала" in ru and "Examples of the voice wanted" in ru
        de = tr.system_prompt("de", "German", "Luna Snow", False)
        assert "German" in de and "masculine" in de and "Examples of the voice wanted" not in de

    def test_memory_offers_close_lines(self):
        memory = tr.Memory([("I love a complete gangbang!", "Обожаю групповуху!"), ("Hello there.", "Привет.")])
        assert memory.closest("Who wants a gangbang?")[0][0] == "I love a complete gangbang!"
        assert memory.closest("I love a complete gangbang!") == []  # the line itself is not an example


class TestTranslating:
    def server(self, answers):
        server = tr.LlamaServer("llama-server.exe", [], parallel=3, thinking=False)
        lock, calls = threading.Lock(), []

        def chat(system, prompt, temperature=None):
            line = prompt.rsplit("Line to translate: ", 1)[1].split("\n", 1)[0]
            with lock:
                calls.append((line, temperature))
                queue = answers[line]
                return queue.pop(0) if len(queue) > 1 else queue[0]

        server.chat = chat
        return server, calls

    def items(self, *lines):
        return [{"heard": line, "game_en": "x", "game_local": "x"} for line in lines]

    def test_each_line_comes_back_in_its_place(self):
        answers = {f"Line {i}": [f"Строка {i}"] for i in range(10)}
        server, _ = self.server(answers)
        out = server.translate(self.items(*answers), language="ru", language_name="Russian", speaker="Луна",
                               feminine=True)
        assert out == [f"Строка {i}" for i in range(10)]

    def test_english_left_in_is_tried_again(self):
        server, calls = self.server({"Fuck yeah!": ["Fuck да!", "Бля, да!"]})
        out = server.translate(self.items("Fuck yeah!"), language="ru", language_name="Russian", speaker="Луна",
                               feminine=True)
        assert out == ["Бля, да!"] and calls[1][1] == 0.6

    def test_an_answer_copied_from_the_examples_is_tried_again_without_them(self):
        memory = tr.Memory([("I love it so much.", "Я это обожаю.")])
        server, calls = self.server({"I love it.": ["Я это обожаю.", "Люблю это."]})
        out = server.translate(self.items("I love it."), language="ru", language_name="Russian", speaker="Луна",
                               feminine=True, memory=memory)
        assert out == ["Люблю это."] and len(calls) == 2

    def test_cancelling_leaves_lines_untranslated(self):
        server, _ = self.server({"A": ["А"], "B": ["Б"]})
        out = server.translate(self.items("A", "B"), language="ru", language_name="Russian", speaker="Луна",
                               feminine=True, cancelled=lambda: True)
        assert out == [None, None]

"""Voice subtitles in the app: settings, the work queue, the combined file, the routes."""
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.voice_subtitles import components as comps
from core.voice_subtitles import pipeline
from core.voice_subtitles import service as svc_mod
from core.voice_subtitles.hardware import Gpu, Hardware
from voice_subtitles_fakes import AES, NS, FakeGame, bank, key, voice_pak

HW = Hardware(gpus=[Gpu("GeForce", "nvidia", 16303, 13.0)], ram_mb=65536, threads=16)


def wait(predicate, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def env(tmp_path, monkeypatch):
    game_root = tmp_path / "game"
    mods = game_root / "MarvelGame" / "Marvel" / "Content" / "Paks" / "~mods"
    (mods / "luna_snow").mkdir(parents=True)
    voice_pak(mods / "luna_snow" / "Voice_9999999_P.pak", bank({1: b"a"}, {"vo_10310001_a_play": [1]}))
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    settings = SimpleNamespace(marvel_rivals_root=game_root, marvel_rivals_local_downloads_root=downloads,
                               aes_key_hex=AES, data_dir=data_dir)
    log, new_downloads = [], []
    running = {"game": False}
    game = FakeGame(en={key("1"): "Hello!"}, local={"ru": {key("1"): "Привет!"}})

    service = svc_mod.VoiceSubtitles(
        data_dir=lambda: data_dir, settings=lambda: settings, library=lambda: [],
        on_new_downloads=lambda: new_downloads.append(1) or [], log=lambda *a: log.append(a),
        game_running=lambda: running["game"], hardware=lambda: HW, rebuild_delay=0.05, game_poll=0.05)
    service.set_config(folder=str(tmp_path / "voice"))
    monkeypatch.setattr(service, "game", lambda: game)
    monkeypatch.setattr(service, "game_language", lambda: "ru")

    # The models: recognition and translation write what they would have.
    def recognise(work, vgmstream, server_factory, progress, cancelled):
        rows = [{"namespace": NS, "key": key("1"), "line": "1", "en": "Hello!", "heard": "Hi, darling.",
                 "status": "changed"}]
        (work / "transcript.json").write_text(json.dumps(rows), encoding="utf-8")
        return {"changed": 1}

    def translate(work, root, language, language_name, model, game, server_factory, progress, cancelled, game_running):
        if game_running():
            raise pipeline.Stopped()
        (work / f"translation.{language}.json").write_text(json.dumps({key("1"): "Привет, милый."}), encoding="utf-8")
        return 1

    monkeypatch.setattr(pipeline, "recognise", recognise)
    monkeypatch.setattr(pipeline, "translate", translate)
    monkeypatch.setattr(pipeline, "ensure_map", lambda work, *a, **k: (work.mkdir(parents=True, exist_ok=True),
                                                                      (work / "map.json").write_text('{"hero": "1031", "lines": []}'))[1])
    return SimpleNamespace(service=service, mods=mods, downloads=downloads, data_dir=data_dir, log=log,
                           new_downloads=new_downloads, running=running, tmp=tmp_path)


def pretend_installed(folder: Path, *ids):
    data = {}
    for cid in ids:
        comp = comps.COMPONENTS[cid]
        main = folder / comp.folder / comp.main
        main.parent.mkdir(parents=True, exist_ok=True)
        main.write_bytes(b"x")
        data[cid] = {}
    (folder / "components.json").write_text(json.dumps(data))


def scanned(service):
    service.rescan()
    assert wait(lambda: service._voice_mods is not None and not service._scanning)
    return service.voice_mods()


class TestSettings:
    def test_the_default_folder_is_under_local_app_data(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
        assert svc_mod.default_folder(tmp_path) == tmp_path / "local" / "RivalNxt" / "Voice Subtitles"

    def test_moving_the_folder_moves_what_is_in_it(self, env):
        old = env.service.folder()
        (old / "models").mkdir(parents=True)
        (old / "models" / "m.gguf").write_bytes(b"model")
        env.service.set_config(folder=str(env.tmp / "elsewhere"))
        assert (env.tmp / "elsewhere" / "models" / "m.gguf").read_bytes() == b"model"
        assert not old.exists()

    def test_unknown_values_are_refused(self, env):
        with pytest.raises(ValueError):
            env.service.set_config(model="gpt-9")
        with pytest.raises(ValueError):
            env.service.set_config(language="xx")


class TestMaking:
    def test_without_speech_recognition_nothing_starts(self, env):
        mod = scanned(env.service)[0]
        with pytest.raises(ValueError, match="speech recognition"):
            env.service.make(mod.key, "en")

    def test_translation_needs_a_model(self, env):
        pretend_installed(env.service.folder(), *comps.RECOGNITION)
        mod = scanned(env.service)[0]
        with pytest.raises(ValueError, match="translation model"):
            env.service.make(mod.key, "ru")

    def test_a_voice_mod_gets_its_subtitle_mod(self, env):
        pretend_installed(env.service.folder(), *comps.RECOGNITION, "llama-cuda13", "gemma-4-31b")
        env.service.set_config(model="gemma-4-31b")
        mod = scanned(env.service)[0]

        job = env.service.make(mod.key, "ru")
        assert wait(lambda: job.state in ("done", "failed")), job
        assert job.state == "done", job.error

        archive = env.downloads / "RU Subtitles - Luna Snow - Voice.zip"
        assert archive.exists()
        assert env.new_downloads, "the library is told about the new archive"
        assert env.log[-1][1] == "Made Russian subtitles"
        state = env.service.status()["voice_mods"][0]["subtitles"]["ru"]
        assert state["state"] == "ready" and state["counts"]["subtitled"] == 1 and state["active"] is False

    def test_the_same_request_twice_is_one_job(self, env, monkeypatch):
        pretend_installed(env.service.folder(), *comps.RECOGNITION)
        mod = scanned(env.service)[0]
        monkeypatch.setattr(env.service, "_start", lambda *a, **k: None)  # keep it queued
        assert env.service.make(mod.key, "en") is env.service.make(mod.key, "en")

    def test_while_the_game_runs_the_work_waits(self, env):
        pretend_installed(env.service.folder(), *comps.RECOGNITION, "llama-cuda13", "gemma-4-31b")
        env.service.set_config(model="gemma-4-31b")
        mod = scanned(env.service)[0]
        env.running["game"] = True
        job = env.service.make(mod.key, "ru")
        assert wait(lambda: job.state == "waiting")
        env.running["game"] = False
        assert wait(lambda: job.state == "done"), (job.state, job.error)

    def test_cancelling_a_waiting_job(self, env):
        pretend_installed(env.service.folder(), *comps.RECOGNITION)
        mod = scanned(env.service)[0]
        env.running["game"] = True
        job = env.service.make(mod.key, "en")
        assert wait(lambda: job.state == "waiting")
        env.service.cancel(job.id)
        assert wait(lambda: job.state == "cancelled")

    def test_peni_parkers_voice_mods_get_none(self, env, monkeypatch):
        pretend_installed(env.service.folder(), *comps.RECOGNITION)
        mod = scanned(env.service)[0]
        monkeypatch.setattr(type(mod), "hero", property(lambda self: "1042"))
        with pytest.raises(ValueError, match="not made"):
            env.service.make(mod.key, "en")

    def test_make_all_skips_what_is_made(self, env):
        pretend_installed(env.service.folder(), *comps.RECOGNITION, "llama-cuda13", "gemma-4-31b")
        env.service.set_config(model="gemma-4-31b")
        scanned(env.service)
        jobs = env.service.make_all("ru")
        assert [j.title for j in jobs] == ["Luna Snow · Voice"]
        assert wait(lambda: jobs[0].state == "done"), jobs[0].error
        assert env.service.make_all("ru") == []
        state = env.service.status()["voice_mods"][0]["subtitles"]["ru"]
        assert state["models"] == []  # the stand-in translator records no model

    def test_the_time_left_comes_from_the_pace(self, monkeypatch):
        clock = {"now": 100.0}
        monkeypatch.setattr(svc_mod.time, "monotonic", lambda: clock["now"])
        job = svc_mod.Job(kind="make", title="t", target="k", state="running")
        job.progress("Translating", 0, 100)
        clock["now"] += 5
        job.progress("Translating", 10, 100)
        assert job.seconds_left() is None  # too early to tell
        clock["now"] += 15
        job.progress("Translating", 40, 100)
        assert job.seconds_left() == 30 and job.public()["seconds_left"] == 30
        job.progress("Writing the subtitle mod", 0, 0)
        assert job.seconds_left() is None


class TestInstalling:
    def test_a_download_that_does_not_fit_is_refused(self, env, monkeypatch):
        monkeypatch.setattr(svc_mod, "_free_bytes", lambda folder: 2_000_000_000)
        with pytest.raises(ValueError, match="Not enough free space"):
            env.service.install("gemma-4-31b")
        assert env.service.jobs() == []


class TestEditing:
    def test_a_hand_edit_rewrites_the_subtitle_mod(self, env):
        pretend_installed(env.service.folder(), *comps.RECOGNITION, "llama-cuda13", "gemma-4-31b")
        env.service.set_config(model="gemma-4-31b")
        mod = scanned(env.service)[0]
        job = env.service.make(mod.key, "ru")
        assert wait(lambda: job.state == "done")

        lines = env.service.lines(mod.key, "ru")
        assert lines[0]["subtitle"] == "Привет, милый." and lines[0]["game"] == "Привет!"
        env.service.edit(mod.key, "ru", key("1"), "Привет, дорогой.")
        assert env.service.lines(mod.key, "ru")[0] == {**lines[0], "subtitle": "Привет, дорогой.", "edited": True}
        env.service.edit(mod.key, "ru", key("1"), None)
        assert env.service.lines(mod.key, "ru")[0]["subtitle"] == "Привет, милый."
        env.service.edit(mod.key, "ru", key("1"), "  Привет,\n  милый!  ")
        assert env.service.lines(mod.key, "ru")[0]["subtitle"] == "Привет, милый!"
        with pytest.raises(ValueError):
            env.service.lines(mod.key, "")
        with pytest.raises(ValueError):
            env.service.edit(mod.key, "../x", key("1"), "x")


class TestCombined:
    def test_changes_close_together_rebuild_once(self, env, monkeypatch):
        calls = []
        monkeypatch.setattr(svc_mod, "build_combined", lambda *a, **k: calls.append(a) or {"mods": 0})
        for _ in range(5):
            env.service.request_rebuild("mods switched on or off")
        assert wait(lambda: calls)
        time.sleep(0.2)
        assert len(calls) == 1

    def test_while_the_game_has_the_file_open_it_is_tried_again(self, env, monkeypatch):
        outcomes = [svc_mod.GameHasItOpen("x"), {"mods": 1}]

        def build(*a, **k):
            out = outcomes.pop(0)
            if isinstance(out, Exception):
                raise out
            return out

        monkeypatch.setattr(svc_mod, "build_combined", build)
        env.service.request_rebuild("x")
        assert wait(lambda: not outcomes)
        assert wait(lambda: env.service.status()["combined"].get("mods") == 1)


class TestRoutes:
    @pytest.fixture
    def client(self, env):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from core.api import voice_subtitles_routes as routes

        app = FastAPI()
        app.include_router(routes.router)
        routes.attach(env.service)
        return TestClient(app)

    def test_status(self, client, env):
        scanned(env.service)
        body = client.get("/api/voice-subtitles").json()
        assert body["language"] == "ru" and body["recognition"]["installed"] is False
        assert body["translation"]["recommended"] == "gemma-4-31b"
        assert body["voice_mods"][0]["hero_name"] == "Luna Snow"

    def test_settings_and_errors(self, client, env):
        assert client.put("/api/voice-subtitles/settings", json={"language": "en"}).json()["language"] == "en"
        assert client.put("/api/voice-subtitles/settings", json={"model": "nope"}).status_code == 400
        assert client.post("/api/voice-subtitles/make", json={"key": "missing"}).status_code == 404
        assert client.post("/api/voice-subtitles/install", json={"what": "nope"}).status_code == 400
        assert client.post("/api/voice-subtitles/jobs/none/cancel").status_code == 404
        assert client.post("/api/voice-subtitles/make-all", json={"language": "xx"}).status_code == 400
        assert client.post("/api/voice-subtitles/make-all", json={}).status_code == 400  # no recognition yet
        assert client.get("/api/voice-subtitles/voice-mods/x/lines", params={"language": ""}).status_code == 400

"""Downloading the programs and models, and choosing what suits a computer."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile

import pytest

from core.voice_subtitles import components as comps
from core.voice_subtitles.hardware import Gpu, Hardware, cuda_version


def nvidia(vram_mb: int, cuda: float = 13.0, ram_mb: int = 32000) -> Hardware:
    return Hardware(gpus=[Gpu("GeForce", "nvidia", vram_mb, cuda)], ram_mb=ram_mb, threads=16)


class TestChoosing:
    @pytest.mark.parametrize("hw,model", [
        (nvidia(24576), "gemma-4-31b-q4"),
        (nvidia(16303), "gemma-4-31b"),
        (nvidia(12288), "gemma-4-26b"),
        (nvidia(8192, ram_mb=16000), "gemma-4-12b"),
        (Hardware(gpus=[Gpu("Radeon RX 7900", "amd", 20480)], ram_mb=32000), "gemma-4-26b"),
        (Hardware(gpus=[], ram_mb=65536, threads=16), "gemma-4-26b"),
        (Hardware(gpus=[], ram_mb=16000, threads=8), "gemma-4-12b"),
    ])
    def test_recommendation(self, hw, model):
        assert comps.recommend(hw) == model

    def test_the_dense_31b_is_never_offered_split(self):
        # Split between card and processor it was 15 times slower.
        assert comps.model_fit(comps.MODELS["gemma-4-31b"], nvidia(12288)) == "no"
        assert comps.model_fit(comps.MODELS["gemma-4-31b"], Hardware(gpus=[Gpu("Radeon", "amd", 24000)])) == "no"

    @pytest.mark.parametrize("hw,engine", [
        (nvidia(16303, cuda=13.0), "llama-cuda13"),
        (nvidia(16303, cuda=12.8), "llama-cuda12"),
        (Hardware(gpus=[Gpu("Arc A770", "intel", 16384)]), "llama-vulkan"),
        (Hardware(gpus=[Gpu("Radeon(TM) Graphics", "amd", 512)]), "llama-cpu"),  # integrated
        (Hardware(), "llama-cpu"),
    ])
    def test_engine(self, hw, engine):
        assert comps.engine_for(hw) == engine

    def test_runtime_on_a_16_gb_card_is_all_on_the_card(self, tmp_path):
        rt = comps.runtime("gemma-4-31b", tmp_path, nvidia(16303))
        assert rt.engine == "llama-cuda13" and rt.parallel == 3 and rt.thinking
        assert rt.args[rt.args.index("-ngl") + 1] == "99"
        assert rt.args[rt.args.index("-m") + 1].endswith("gemma-4-31B-it-Q3_K_S.gguf")
        assert rt.args[rt.args.index("-md") + 1].endswith("mtp-gemma-4-31B-it-Q4_0.gguf")

    def test_runtime_split_lets_the_server_fit_it(self, tmp_path):
        rt = comps.runtime("gemma-4-26b", tmp_path, nvidia(8192))
        assert "-ngl" not in rt.args and "-fitt" in rt.args and rt.thinking

    def test_runtime_on_the_processor_does_not_think(self, tmp_path):
        rt = comps.runtime("gemma-4-12b", tmp_path, Hardware(ram_mb=32000, threads=12))
        assert rt.engine == "llama-cpu" and not rt.thinking
        assert rt.args[rt.args.index("-t") + 1] == "6"


def zip_bytes(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


class FakeResponse:
    def __init__(self, data: bytes, status: int = 200):
        self.data, self.status_code = data, status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def iter_content(self, chunk_size):
        for i in range(0, len(self.data), 7):
            yield self.data[i:i + 7]


class FakeSession:
    def __init__(self, files: dict):
        self.files, self.ranges = files, []

    def get(self, url, headers=None, **_k):
        data = self.files[url]
        start = int(headers["Range"][6:-1]) if headers and "Range" in headers else 0
        self.ranges.append(start)
        return FakeResponse(data[start:], 206 if start else 200)


@pytest.fixture
def catalog(monkeypatch):
    archive = zip_bytes({"Release/tool.exe": b"exe", "Release/lib.dll": b"dll"})
    model = b"m" * 100
    files = {"https://x/tool.zip": archive, "https://x/model.bin": model}
    monkeypatch.setitem(comps.COMPONENTS, "tool", comps.Component(
        "tool", "A tool", "tools/tool",
        (comps.File("https://x/tool.zip", "tool.zip", len(archive), hashlib.sha256(archive).hexdigest(), True),),
        "tool.exe"))
    monkeypatch.setitem(comps.COMPONENTS, "model", comps.Component(
        "model", "A model", "models",
        (comps.File("https://x/model.bin", "model.bin", len(model), hashlib.sha256(model).hexdigest()),),
        "model.bin"))
    return FakeSession(files)


class TestInstalling:
    def test_install_unpacks_and_records(self, tmp_path, catalog):
        seen = []
        comps.install("tool", tmp_path, progress=lambda d, t: seen.append((d, t)), session=catalog)
        assert (tmp_path / "tools/tool/tool.exe").read_bytes() == b"exe"  # "Release/" dropped
        assert "tool" in comps.installed(tmp_path)
        assert seen[-1][0] == seen[-1][1]
        assert not (tmp_path / "downloads/tool.zip").exists()

    def test_a_download_resumes(self, tmp_path, catalog):
        part = tmp_path / "models" / "model.bin.part"
        part.parent.mkdir(parents=True)
        part.write_bytes(b"m" * 40)
        comps.install("model", tmp_path, session=catalog)
        assert catalog.ranges == [40]
        assert (tmp_path / "models/model.bin").read_bytes() == b"m" * 100

    def test_a_damaged_download_is_refused(self, tmp_path, catalog):
        catalog.files["https://x/model.bin"] = b"x" * 100
        with pytest.raises(RuntimeError, match="checksum"):
            comps.install("model", tmp_path, session=catalog)
        assert not (tmp_path / "models/model.bin").exists()
        assert not (tmp_path / "models/model.bin.part").exists()

    def test_cancelling_keeps_what_was_downloaded(self, tmp_path, catalog):
        calls = {"n": 0}

        def cancelled():
            calls["n"] += 1
            return calls["n"] > 3

        with pytest.raises(comps.Cancelled):
            comps.install("model", tmp_path, cancelled=cancelled, session=catalog)
        assert (tmp_path / "models/model.bin.part").stat().st_size > 0
        assert "model" not in comps.installed(tmp_path)

    def test_removing_a_model_keeps_a_draft_head_another_one_uses(self, tmp_path):
        models = tmp_path / "models"
        models.mkdir()
        for name in ("gemma-4-31B-it-Q3_K_S.gguf", "gemma-4-31B-it-Q4_K_M.gguf", "mtp-gemma-4-31B-it-Q4_0.gguf"):
            (models / name).write_bytes(b"x")
        (tmp_path / "components.json").write_text(json.dumps({"gemma-4-31b": {}, "gemma-4-31b-q4": {}}))
        comps.remove("gemma-4-31b", tmp_path)
        assert not (models / "gemma-4-31B-it-Q3_K_S.gguf").exists()
        assert (models / "mtp-gemma-4-31B-it-Q4_0.gguf").exists()
        assert set(comps.installed(tmp_path)) == {"gemma-4-31b-q4"}

    def test_an_archive_cannot_write_outside_its_folder(self, tmp_path):
        archive = tmp_path / "evil.zip"
        archive.write_bytes(zip_bytes({"ok.txt": b"1", "../escaped.txt": b"2"}))
        (tmp_path / "into").mkdir()
        comps._unzip(archive, tmp_path / "into")
        assert (tmp_path / "into/ok.txt").exists() and not (tmp_path / "escaped.txt").exists()


def test_every_component_is_pinned():
    for comp in comps.COMPONENTS.values():
        for f in comp.files:
            assert len(f.sha256) == 64 and f.size > 0
            assert "/latest/" not in f.url and "/resolve/main/" not in f.url


@pytest.mark.parametrize("header,driver,cuda", [
    ("| NVIDIA-SMI 616.92   KMD Version: 616.92   CUDA UMD Version: 13.4 |", "616.92", 13.4),
    ("| NVIDIA-SMI 572.16   Driver Version: 572.16   CUDA Version: 12.8 |", "572.16", 12.8),
    ("", "581.08", 13.0),   # nvidia-smi's summary could not be read
    ("", "537.13", 12.0),
    ("", "", None),
])
def test_cuda_version(header, driver, cuda):
    assert cuda_version(header, driver) == cuda

"""What is downloaded on request: the programs and models that make subtitles.

Nothing here is part of the app. Speech recognition (whisper.cpp, a Whisper
model and vgmstream to decode the game's sounds) is about 0.9 GB and runs on
any computer; translation (llama.cpp and a Gemma model) is 7-19 GB and is
only needed for subtitles in a language other than English. Each file is
pinned to an exact release and checked against its SHA-256 after download.

Which build of llama.cpp and which model suit a computer is decided here
too, from its graphics card and memory.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .hardware import Hardware

LLAMA = "https://github.com/ggml-org/llama.cpp/releases/download/b11669/"
WHISPER = "https://github.com/ggml-org/whisper.cpp/releases/download/b5454/"


@dataclass(frozen=True)
class File:
    url: str
    name: str
    size: int
    sha256: str
    unzip: bool = False


@dataclass(frozen=True)
class Component:
    id: str
    title: str
    folder: str            # under the voice-subtitles folder
    files: Tuple[File, ...]
    main: str              # the file whose presence means "installed", relative to folder

    @property
    def size(self) -> int:
        return sum(f.size for f in self.files)


def _hf(repo: str, commit: str, path: str, size: int, sha256: str) -> File:
    return File(f"https://huggingface.co/{repo}/resolve/{commit}/{path}", Path(path).name, size, sha256)


COMPONENTS: Dict[str, Component] = {c.id: c for c in [
    Component("vgmstream", "vgmstream (decodes the game's sounds)", "tools/vgmstream", (
        File("https://github.com/vgmstream/vgmstream/releases/download/r2117/vgmstream-win64.zip",
             "vgmstream-win64.zip", 4468180, "6c4a8a3813864fefed081bbd337dbc0ad93bf88e0b92f5db98d7ab258b22dc6c", True),
    ), "vgmstream-cli.exe"),
    Component("whisper-cpu", "whisper.cpp (speech recognition)", "tools/whisper-cpu", (
        File(WHISPER + "whisper-blas-bin-x64.zip", "whisper-blas-bin-x64.zip", 21715607,
             "b1158bd10edf92c9799149a6fc5d3e58da3f495241d6fb3423088130e88ffbf3", True),
    ), "whisper-server.exe"),
    Component("whisper-cuda", "whisper.cpp for NVIDIA cards (faster speech recognition)", "tools/whisper-cuda", (
        File(WHISPER + "whisper-bin-win-cuda-12.4.0-x64.zip", "whisper-bin-win-cuda-12.4.0-x64.zip", 684913404,
             "afef0b881c500958921c3f5523b50e59ee2ec9b6f5cbd25b324c51ed308a957a", True),
    ), "whisper-server.exe"),
    Component("whisper-model", "Whisper large-v3-turbo", "models", (
        _hf("ggerganov/whisper.cpp", "5359861c739e955e79d9a303bcbc70fb988958b1", "ggml-large-v3-turbo-q8_0.bin",
            874188075, "317eb69c11673c9de1e1f0d459b253999804ec71ac4c23c17ecf5fbe24e259a1"),
    ), "ggml-large-v3-turbo-q8_0.bin"),
    Component("llama-cuda13", "llama.cpp for NVIDIA cards (CUDA 13)", "tools/llama-cuda13", (
        File(LLAMA + "llama-b11669-bin-win-cuda-13.4-x64.zip", "llama-b11669-bin-win-cuda-13.4-x64.zip", 154582227,
             "3b92d5c064f5032e603e531d3ec8961f3bd6613e5dfad047399a92dec8e95dbc", True),
        File(LLAMA + "cudart-llama-bin-win-cuda-13.4-x64.zip", "cudart-llama-bin-win-cuda-13.4-x64.zip", 423535356,
             "738f8c251ac22b70c3ae6f83a10cf222725df0395246a2cf58f32bdb85fbe668", True),
    ), "llama-server.exe"),
    Component("llama-cuda12", "llama.cpp for NVIDIA cards (CUDA 12)", "tools/llama-cuda12", (
        File(LLAMA + "llama-b11669-bin-win-cuda-12.4-x64.zip", "llama-b11669-bin-win-cuda-12.4-x64.zip", 266582698,
             "c2da1f73ed176ae093ac5aceb978a7b167a16113f6d74c6789eeaee2135cb8dc", True),
        File(LLAMA + "cudart-llama-bin-win-cuda-12.4-x64.zip", "cudart-llama-bin-win-cuda-12.4-x64.zip", 391443627,
             "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6", True),
    ), "llama-server.exe"),
    Component("llama-vulkan", "llama.cpp for AMD and Intel cards (Vulkan)", "tools/llama-vulkan", (
        File(LLAMA + "llama-b11669-bin-win-vulkan-x64.zip", "llama-b11669-bin-win-vulkan-x64.zip", 32182350,
             "2c07574e7bde71321cb785282b20cc821e951132149eeceeea32ddebdbf0598e", True),
    ), "llama-server.exe"),
    Component("llama-cpu", "llama.cpp for the processor", "tools/llama-cpu", (
        File(LLAMA + "llama-b11669-bin-win-cpu-x64.zip", "llama-b11669-bin-win-cpu-x64.zip", 19537886,
             "37b3efcf962847ca869745fd4ccf7f5e7e8dacfeff9fa3523b4ca8cdc66d632b", True),
    ), "llama-server.exe"),
    Component("gemma-4-31b-q4", "Gemma 4 31B (4-bit)", "models", (
        _hf("unsloth/gemma-4-31B-it-GGUF", "c1ac76e99d5513b141e8adde7288b85c3f9c32ec", "gemma-4-31B-it-Q4_K_M.gguf",
            18323733440, "38bd64c852c4b460434cc7162fa9bdcf242faf86502581a754cb72956bb17f84"),
        _hf("unsloth/gemma-4-31B-it-qat-GGUF", "43cc1aeb31adf47ec06a854507ce552cd9862e6f",
            "MTP/mtp-gemma-4-31B-it-Q4_0.gguf", 279955968,
            "3a5e99fd8d0b23afb1fccd1ee0c9ebd1f571d00399c2dae2292d217feeec0f6b"),
    ), "gemma-4-31B-it-Q4_K_M.gguf"),
    Component("gemma-4-31b", "Gemma 4 31B (3-bit)", "models", (
        _hf("unsloth/gemma-4-31B-it-GGUF", "c1ac76e99d5513b141e8adde7288b85c3f9c32ec", "gemma-4-31B-it-Q3_K_S.gguf",
            13210856384, "02cdd36af753d2a61832c3e71b621e6d6be65906bbee4adfcde9f62b42154d97"),
        _hf("unsloth/gemma-4-31B-it-qat-GGUF", "43cc1aeb31adf47ec06a854507ce552cd9862e6f",
            "MTP/mtp-gemma-4-31B-it-Q4_0.gguf", 279955968,
            "3a5e99fd8d0b23afb1fccd1ee0c9ebd1f571d00399c2dae2292d217feeec0f6b"),
    ), "gemma-4-31B-it-Q3_K_S.gguf"),
    Component("gemma-4-26b", "Gemma 4 26B-A4B", "models", (
        _hf("unsloth/gemma-4-26B-A4B-it-GGUF", "c099eb48e663fd284577b04978a94ffccb261841",
            "gemma-4-26B-A4B-it-UD-IQ4_XS.gguf", 13597177568,
            "babd1e389d386352f71600765d37390f7dc993fbfad6725caccf996ffe34aecf"),
        _hf("unsloth/gemma-4-26B-A4B-it-GGUF", "c099eb48e663fd284577b04978a94ffccb261841",
            "mtp-gemma-4-26B-A4B-it.gguf", 461766816,
            "6326fb9f5e487aa8dcdd313a091e3c67724cb2a666ec3b7d2895b5b26d93ed1b"),
    ), "gemma-4-26B-A4B-it-UD-IQ4_XS.gguf"),
    Component("gemma-4-12b", "Gemma 4 12B", "models", (
        _hf("unsloth/gemma-4-12b-it-GGUF", "fc034cfff751157913579611efad8462ac1be606", "gemma-4-12b-it-Q4_K_M.gguf",
            7121861440, "0a270ec9fe6b34f4a0d33992b6135117b484ebc4766ab76b51d4ae8c457e4c42"),
        _hf("unsloth/gemma-4-12b-it-GGUF", "fc034cfff751157913579611efad8462ac1be606", "mtp-gemma-4-12b-it.gguf",
            465109248, "145db9094bc0f85f1701e255a2ed216dcc9800fc8bc8631ad00905b456bd451b"),
    ), "gemma-4-12b-it-Q4_K_M.gguf"),
]}

RECOGNITION = ("vgmstream", "whisper-cpu", "whisper-model")
ENGINES = ("llama-cuda13", "llama-cuda12", "llama-vulkan", "llama-cpu")


# ---------------------------------------------------------------- translation models
@dataclass(frozen=True)
class Model:
    id: str
    title: str
    quality: str
    blurb: str
    needs_vram_mb: int      # to run entirely on the graphics card
    min_vram_mb: int        # to run at all with part of it in system memory (0: the processor can)
    min_ram_mb: int


MODELS: Dict[str, Model] = {m.id: m for m in [
    Model("gemma-4-31b-q4", "Gemma 4 31B", "Best",
          "The most careful translation. For NVIDIA cards with 24 GB.", 22000, 22000, 16000),
    Model("gemma-4-31b", "Gemma 4 31B, compact", "Best",
          "Almost the same translations as the 4-bit model, on a 16 GB NVIDIA card.", 15000, 15000, 16000),
    Model("gemma-4-26b", "Gemma 4 26B-A4B", "Very good",
          "Quick even when part of it runs on the processor. For 8-12 GB cards, or a processor with 32 GB of memory.",
          15000, 0, 24000),
    Model("gemma-4-12b", "Gemma 4 12B", "Good",
          "Smallest. For 8 GB cards and computers with 16 GB of memory.", 9000, 0, 14000),
]}


def engine_for(hw: Hardware) -> str:
    nvidia = hw.nvidia
    if nvidia and nvidia.vram_mb >= 4000:
        return "llama-cuda13" if (nvidia.cuda or 0) >= 13.0 else "llama-cuda12"
    gpu = hw.gpu
    if gpu and gpu.vendor in ("amd", "intel") and gpu.vram_mb >= 4000:
        return "llama-vulkan"
    return "llama-cpu"


def _vram(hw: Hardware, engine: str) -> int:
    if engine == "llama-cpu":
        return 0
    gpu = hw.nvidia if engine.startswith("llama-cuda") else hw.gpu
    return gpu.vram_mb if gpu else 0


def model_fit(model: Model, hw: Hardware) -> str:
    """"gpu" all on the card, "split" part on the processor, "slow" processor only, "no" will not run."""
    engine = engine_for(hw)
    vram = _vram(hw, engine)
    if model.id.startswith("gemma-4-31b"):
        # Dense: split between card and processor it was 15 times slower.
        return "gpu" if engine.startswith("llama-cuda") and vram >= model.needs_vram_mb else "no"
    if vram >= model.needs_vram_mb:
        return "gpu"
    if vram >= 6000 and hw.ram_mb >= model.min_ram_mb:
        return "split"
    if hw.ram_mb >= model.min_ram_mb:
        return "slow"
    return "no"


def recommend(hw: Hardware) -> str:
    for model_id in ("gemma-4-31b-q4", "gemma-4-31b", "gemma-4-26b"):
        if model_fit(MODELS[model_id], hw) == "gpu":
            return model_id
    # On a 10-12 GB card the 26B-A4B with some experts in system memory beats
    # the 12B that fits whole: only 4B parameters are read per token either way.
    if _vram(hw, engine_for(hw)) >= 10000 and model_fit(MODELS["gemma-4-26b"], hw) == "split":
        return "gemma-4-26b"
    if model_fit(MODELS["gemma-4-12b"], hw) == "gpu":
        return "gemma-4-12b"
    for model_id in ("gemma-4-26b", "gemma-4-12b"):
        if model_fit(MODELS[model_id], hw) == "split":
            return model_id
    if hw.ram_mb >= 32000:
        return "gemma-4-26b"
    return "gemma-4-12b"


@dataclass
class Runtime:
    engine: str
    args: List[str]
    parallel: int
    thinking: bool


def runtime(model_id: str, folder: Path, hw: Hardware) -> Runtime:
    """How to start llama-server for a model on this computer."""
    engine = engine_for(hw)
    models = Path(folder) / "models"
    comp = COMPONENTS[model_id]
    main = str(models / comp.files[0].name)
    draft = str(models / comp.files[1].name)
    fit = model_fit(MODELS[model_id], hw)
    common = ["-m", main, "-fa", "on", "--spec-type", "draft-mtp", "-md", draft]
    if model_id == "gemma-4-31b-q4":
        return Runtime(engine, common + ["-ngl", "99", "-c", str(2048 * 4), "-ctk", "q8_0", "-ctv", "q8_0",
                                         "--reasoning-budget", "900"], 4, True)
    if model_id == "gemma-4-31b":
        # 13.2 GB of weights and the cache of three lines in flight at 4 bits
        # fit beside the ~1 GB Windows keeps on a 16 GB card.
        return Runtime(engine, common + ["-ngl", "99", "-c", str(2048 * 3), "-ctk", "q4_0", "-ctv", "q4_0",
                                         "--reasoning-budget", "900"], 3, True)
    if fit == "gpu":
        return Runtime(engine, common + ["-ngl", "99", "-c", str(2048 * 3), "-ctk", "q8_0", "-ctv", "q8_0",
                                         "--reasoning-budget", "900"], 3, True)
    if fit == "split":
        # The server decides how much of the model stays on the card; the
        # draft head is not counted in that, hence the margin.
        return Runtime(engine, common + ["-c", str(2048 * 2), "-ctk", "q8_0", "-ctv", "q8_0", "-fitt", "1536",
                                         "--reasoning-budget", "900"], 2, True)
    # The processor alone: thinking each line over would take minutes a line.
    threads = max(1, (hw.threads or 2) // 2)
    return Runtime(engine, common + ["-c", str(1024 * 2), "-t", str(threads)], 2, False)


# ---------------------------------------------------------------- installing
class Cancelled(Exception):
    pass


def _manifest(folder: Path) -> Path:
    return Path(folder) / "components.json"


def installed(folder: Path) -> Dict[str, dict]:
    try:
        data = json.loads(_manifest(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {cid: info for cid, info in data.items()
            if cid in COMPONENTS and (Path(folder) / COMPONENTS[cid].folder / COMPONENTS[cid].main).exists()}


def _record(folder: Path, cid: str, info: Optional[dict]) -> None:
    path = _manifest(folder)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if info is None:
        data.pop(cid, None)
    else:
        data[cid] = info
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(path.name + ".new")
    staged.write_text(json.dumps(data, indent=1), encoding="utf-8")
    staged.replace(path)


def _download(f: File, dest: Path, progress: Callable[[int], None], cancelled: Callable[[], bool],
              session=None) -> None:
    """Download with resume to dest, checking size and SHA-256."""
    import requests

    part = dest.with_name(dest.name + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    have = part.stat().st_size if part.exists() else 0
    if have > f.size:
        part.unlink()
        have = 0
    http = session or requests
    for attempt in range(6):
        if have >= f.size:
            break
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with http.get(f.url, headers=headers, stream=True, timeout=60, allow_redirects=True) as r:
                if r.status_code == 416:
                    break
                r.raise_for_status()
                if have and r.status_code != 206:
                    have = 0  # the server would not resume: start over
                with open(part, "ab" if have else "wb") as out:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        if cancelled():
                            raise Cancelled()
                        if chunk:
                            out.write(chunk)
                            have += len(chunk)
                            progress(len(chunk))
        except Cancelled:
            raise
        except Exception:
            if attempt == 5:
                raise
            time.sleep(2 + attempt * 3)
            have = part.stat().st_size if part.exists() else 0
    if part.stat().st_size != f.size:
        raise RuntimeError(f"{f.name}: downloaded {part.stat().st_size} bytes, expected {f.size}")
    digest = hashlib.sha256()
    with open(part, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            if cancelled():
                raise Cancelled()
            digest.update(chunk)
    if digest.hexdigest() != f.sha256:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"{f.name} is damaged (checksum mismatch); it will be downloaded again")
    os.replace(part, dest)


def _unzip(archive: Path, into: Path) -> None:
    """Extract, dropping a single top folder ("Release/") that holds everything."""
    with zipfile.ZipFile(archive) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        tops = {n.split("/", 1)[0] for n in names}
        strip = len(tops) == 1 and all("/" in n for n in names)
        for n in names:
            rel = n.split("/", 1)[1] if strip else n
            target = (into / rel).resolve()
            if not str(target).startswith(str(into.resolve())):
                continue  # a path that would escape the folder
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


def install(cid: str, folder: Path, progress: Callable[[int, int], None] = lambda done, total: None,
            cancelled: Callable[[], bool] = lambda: False, session=None) -> None:
    comp = COMPONENTS[cid]
    folder = Path(folder)
    target = folder / comp.folder
    downloads = folder / "downloads"
    done = [0]

    def step(n: int) -> None:
        done[0] += n
        progress(done[0], comp.size)

    for f in comp.files:
        dest = downloads / f.name if f.unzip else target / f.name
        if dest.exists() and not f.unzip:
            step(f.size)
            continue
        part = dest.with_name(dest.name + ".part")
        if part.exists():
            step(min(part.stat().st_size, f.size))
        _download(f, dest, step, cancelled, session)
        if f.unzip:
            target.mkdir(parents=True, exist_ok=True)
            _unzip(dest, target)
            dest.unlink(missing_ok=True)
    if not (target / comp.main).exists():
        raise RuntimeError(f"{comp.title}: {comp.main} is missing after installation")
    _record(folder, cid, {"installed_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "size": comp.size})


def remove(cid: str, folder: Path) -> None:
    comp = COMPONENTS[cid]
    folder = Path(folder)
    if comp.folder == "models":
        others = {f.name for oid, info in installed(folder).items() if oid != cid
                  for f in COMPONENTS[oid].files if COMPONENTS[oid].folder == "models"}
        for f in comp.files:
            if f.name not in others:  # two models share a draft head
                (folder / "models" / f.name).unlink(missing_ok=True)
    else:
        shutil.rmtree(folder / comp.folder, ignore_errors=True)
    _record(folder, cid, None)


def path_of(cid: str, folder: Path, name: Optional[str] = None) -> Path:
    comp = COMPONENTS[cid]
    return Path(folder) / comp.folder / (name or comp.main)

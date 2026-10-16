"""What the computer can run: graphics cards and their memory, system memory, threads."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from typing import List, Optional

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class Gpu:
    name: str
    vendor: str            # "nvidia", "amd", "intel" or "other"
    vram_mb: int
    cuda: Optional[float] = None  # the newest CUDA the NVIDIA driver supports


@dataclass
class Hardware:
    gpus: List[Gpu] = field(default_factory=list)
    ram_mb: int = 0
    threads: int = 1

    @property
    def gpu(self) -> Optional[Gpu]:
        """The card with the most memory."""
        return max(self.gpus, key=lambda g: g.vram_mb, default=None)

    @property
    def nvidia(self) -> Optional[Gpu]:
        return max((g for g in self.gpus if g.vendor == "nvidia"), key=lambda g: g.vram_mb, default=None)

    def as_dict(self) -> dict:
        return {"gpus": [asdict(g) for g in self.gpus], "ram_mb": self.ram_mb, "threads": self.threads}


def _run(args: List[str], timeout: int = 20) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, errors="replace",
                              creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def cuda_version(header: str, driver: str) -> Optional[float]:
    """The newest CUDA the driver runs: from nvidia-smi's summary ("CUDA Version: 12.8",
    or "CUDA UMD Version: 13.4" on newer drivers), else from the driver's number."""
    m = re.search(r"CUDA(?:\s+\w+)?\s+Version:\s*(\d+\.\d+)", header)
    if m:
        return float(m.group(1))
    m = re.match(r"\s*(\d+)", driver or "")
    if not m:
        return None
    major = int(m.group(1))
    return 13.0 if major >= 580 else 12.0 if major >= 525 else 11.0


def _nvidia() -> List[Gpu]:
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"])
    header = _run(["nvidia-smi"])
    gpus = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3 and parts[1].isdigit():
            gpus.append(Gpu(name=parts[0], vendor="nvidia", vram_mb=int(parts[1]), cuda=cuda_version(header, parts[2])))
    return gpus


def _others() -> List[Gpu]:
    """Other cards, from the display adapters' registry entries (WMI caps memory at 4 GB)."""
    script = (
        "Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class\\"
        "{4d36e968-e325-11ce-bfc1-08002be10318}\\0*' -ErrorAction SilentlyContinue | "
        "Select-Object DriverDesc, @{n='mem';e={$_.'HardwareInformation.qwMemorySize'}}, "
        "@{n='mem32';e={$_.'HardwareInformation.MemorySize'}} | ConvertTo-Json -Compress"
    )
    out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=30)
    try:
        rows = json.loads(out) if out.strip() else []
    except ValueError:
        return []
    if isinstance(rows, dict):
        rows = [rows]
    gpus = []
    for row in rows:
        name = str(row.get("DriverDesc") or "").strip()
        if not name or re.search(r"nvidia|microsoft basic|remote|virtual|parsec|displaylink", name, re.IGNORECASE):
            continue
        mem = row.get("mem") or row.get("mem32") or 0
        if isinstance(mem, list):  # a binary value comes back as bytes
            mem = int.from_bytes(bytes(mem[:8]), "little")
        try:
            vram = int(mem) // (1024 * 1024)
        except (TypeError, ValueError):
            vram = 0
        vendor = "amd" if re.search(r"amd|radeon", name, re.IGNORECASE) else (
            "intel" if re.search(r"intel|arc", name, re.IGNORECASE) else "other")
        gpus.append(Gpu(name=name, vendor=vendor, vram_mb=vram))
    return gpus


def _ram_mb() -> int:
    try:
        import psutil

        return int(psutil.virtual_memory().total // (1024 * 1024))
    except Exception:
        return 0


_CACHE: Optional[tuple] = None


def detect(max_age: float = 300.0) -> Hardware:
    global _CACHE
    if _CACHE and time.time() - _CACHE[0] < max_age:
        return _CACHE[1]
    hw = Hardware(gpus=_nvidia() + _others(), ram_mb=_ram_mb(), threads=os.cpu_count() or 1)
    _CACHE = (time.time(), hw)
    return hw

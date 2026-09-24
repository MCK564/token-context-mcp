"""Hardware probing utilities for inference capability detection."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class HardwareProfile:
    has_cuda: bool
    vram_gb: float
    ram_gb: float
    has_ollama: bool
    recommended_backend: str


def probe_hardware() -> HardwareProfile:
    """Probe system resources to select optimal inference backend."""
    has_cuda = False
    vram_gb = 0.0
    ram_gb = 16.0  # safe default

    # Check CUDA via nvidia-smi if available
    try:
        if shutil.which("nvidia-smi"):
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=memory.total,memory.free", "--format=csv,noheader,nounits"],
                timeout=2,
                text=True,
            )
            lines = out.strip().splitlines()
            if lines:
                total, free = [float(x.strip()) for x in lines[0].split(",")]
                has_cuda = True
                vram_gb = round(total / 1024, 2)
    except Exception:
        pass

    # Check Apple Silicon Unified Memory
    if platform.system() == "Darwin" and platform.processor() == "arm":
        try:
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], timeout=2, text=True)
            vram_gb = round(float(out.strip()) / (1024**3), 2)
            has_cuda = True
        except Exception:
            pass

    # Check system RAM on Windows / Linux
    try:
        if platform.system() == "Windows":
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_PhysicalMemory | Measure-Object -Property Capacity -Sum).Sum / 1GB"],
                timeout=3,
                text=True,
            )
            ram_gb = round(float(out.strip()), 1)
        elif hasattr(os, "sysconf"):
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            ram_gb = round((pages * page_size) / (1024**3), 1)
    except Exception:
        pass

    # Check if Ollama binary is on PATH
    has_ollama = shutil.which("ollama") is not None

    if (has_cuda and vram_gb >= 8.0) or (has_ollama and ram_gb >= 16.0):
        backend = "local_ollama"
    else:
        backend = "heuristic_fallback"

    return HardwareProfile(
        has_cuda=has_cuda,
        vram_gb=vram_gb,
        ram_gb=ram_gb,
        has_ollama=has_ollama,
        recommended_backend=backend,
    )

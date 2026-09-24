"""Hardware probing utilities for inference capability detection and adaptive execution."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from urllib import error as urllib_error, request as urllib_request


@dataclass(frozen=True)
class HardwareProfile:
    has_cuda: bool
    vram_gb: float
    ram_gb: float
    has_ollama: bool
    recommended_backend: str  # "local_ollama" or "heuristic_fallback" for backward compatibility
    backend_mode: str = "heuristic_fallback"  # "ollama_gpu", "ollama_cpu", or "heuristic_fallback"
    cpu_cores: int = 4
    recommended_threads: int = 3
    available_models: list[str] = field(default_factory=list)
    recommended_model: str = "qwen2.5-coder:7b-instruct-q4_K_M"

    @property
    def is_gpu_accelerated(self) -> bool:
        return self.backend_mode == "ollama_gpu"


def calculate_adaptive_timeout(input_tokens: int, backend_mode: str) -> float:
    """Calculate dynamic timeout based on hardware backend and input length.
    
    Formula:
        Timeout = base_timeout + (input_tokens / 100) * sec_per_100_tok
    """
    if backend_mode == "ollama_gpu":
        base_timeout = 3.0
        sec_per_100_tok = 1.0
        max_timeout = 15.0
    elif backend_mode == "ollama_cpu":
        base_timeout = 5.0
        sec_per_100_tok = 5.0
        max_timeout = 35.0
    else:
        base_timeout = 2.0
        sec_per_100_tok = 0.1
        max_timeout = 5.0

    calculated = base_timeout + (max(0, input_tokens) / 100.0) * sec_per_100_tok
    return round(min(max_timeout, max(base_timeout, calculated)), 2)


def probe_hardware() -> HardwareProfile:
    """Probe system resources to select optimal inference backend."""
    has_cuda = False
    vram_gb = 0.0
    ram_gb = 16.0  # safe default
    cpu_cores = os.cpu_count() or 4
    # Reserve 1 core for MCP stdio / host responsiveness
    recommended_threads = max(1, cpu_cores - 1)

    # 1. Check CUDA via nvidia-smi if available
    try:
        if shutil.which("nvidia-smi"):
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=memory.total,memory.free", "--format=csv,noheader,nounits"],
                timeout=2,
                text=True,
            )
            lines = out.strip().splitlines()
            if lines:
                total, _ = [float(x.strip()) for x in lines[0].split(",")]
                has_cuda = True
                vram_gb = round(total / 1024, 2)
    except Exception:
        pass

    # 2. Check Apple Silicon Unified Memory
    if platform.system() == "Darwin" and platform.processor() == "arm":
        try:
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], timeout=2, text=True)
            vram_gb = round(float(out.strip()) / (1024**3), 2)
            has_cuda = True
        except Exception:
            pass

    # 3. Check system RAM on Windows / Linux
    try:
        if platform.system() == "Windows":
            out = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance Win32_PhysicalMemory | Measure-Object -Property Capacity -Sum).Sum / 1GB",
                ],
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

    # 4. Probe Ollama (via HTTP endpoint or CLI)
    has_ollama = False
    available_models: list[str] = []
    try:
        req = urllib_request.Request("http://localhost:11434/api/tags", headers={"User-Agent": "token-context-mcp"})
        with urllib_request.urlopen(req, timeout=1.0) as resp:
            if resp.status == 200:
                has_ollama = True
                data = json.loads(resp.read().decode("utf-8"))
                available_models = [m.get("name", "") for m in data.get("models", []) if "name" in m]
    except (urllib_error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        has_ollama = shutil.which("ollama") is not None

    # 5. Resolve Model
    override_model = os.environ.get("TOKEN_CONTEXT_SAMPLING_MODEL")
    if override_model:
        recommended_model = override_model
    elif available_models:
        # Match 7b coder models first
        coder_7b = [m for m in available_models if "qwen2.5-coder:7b" in m or ("7b" in m and "coder" in m)]
        if coder_7b:
            recommended_model = coder_7b[0]
        else:
            coder_any = [m for m in available_models if "coder" in m or "qwen" in m]
            recommended_model = coder_any[0] if coder_any else available_models[0]
    else:
        recommended_model = "qwen2.5-coder:7b-instruct-q4_K_M"

    # 6. Select Backend Mode
    if has_ollama and has_cuda and vram_gb >= 6.0:
        backend_mode = "ollama_gpu"
        recommended_backend = "local_ollama"
    elif has_ollama and ram_gb >= 6.0:
        backend_mode = "ollama_cpu"
        recommended_backend = "local_ollama"
    else:
        backend_mode = "heuristic_fallback"
        recommended_backend = "heuristic_fallback"

    return HardwareProfile(
        has_cuda=has_cuda,
        vram_gb=vram_gb,
        ram_gb=ram_gb,
        has_ollama=has_ollama,
        recommended_backend=recommended_backend,
        backend_mode=backend_mode,
        cpu_cores=cpu_cores,
        recommended_threads=recommended_threads,
        available_models=available_models,
        recommended_model=recommended_model,
    )

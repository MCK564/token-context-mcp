from __future__ import annotations

from token_context_mcp.sampling.hardware_probe import HardwareProfile, probe_hardware
from token_context_mcp.sampling.router import SamplingRouter


def test_hardware_probe_returns_valid_profile() -> None:
    profile = probe_hardware()
    assert isinstance(profile, HardwareProfile)
    assert profile.ram_gb > 0
    assert profile.recommended_backend in {"local_ollama", "heuristic_fallback"}


def test_sampling_router_heuristic_fallback() -> None:
    # Force heuristic backend
    mock_hardware = HardwareProfile(
        has_cuda=False,
        vram_gb=0.0,
        ram_gb=8.0,
        has_ollama=False,
        recommended_backend="heuristic_fallback",
    )
    router = SamplingRouter(hardware=mock_hardware)
    sample_text = """
import os
import sys

class InvoiceScanner:
    def scan(self, document):
        return parse(document)

def helper():
    pass
"""
    result = router.summarize(sample_text, intent="test_compression", max_tokens=150)
    assert result["status"] == "success"
    assert result["backend"] == "heuristic_fallback"
    data = result["data"]
    assert "InvoiceScanner" in data["key_symbols"]
    assert "scan" in data["key_symbols"]
    assert len(data["relationships"]) > 0

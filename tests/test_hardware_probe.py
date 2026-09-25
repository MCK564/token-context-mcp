from __future__ import annotations

import platform
from unittest.mock import patch, MagicMock

import pytest

from token_context_mcp.sampling.hardware_probe import (
    HardwareProfile,
    probe_hardware,
    reset_hardware_cache,
)
from token_context_mcp.sampling.router import SamplingRouter
from token_context_mcp.memory.service import MemoryService
from token_context_mcp.server import build_server


@pytest.fixture(autouse=True)
def clean_hardware_cache():
    reset_hardware_cache()
    yield
    reset_hardware_cache()


def test_build_server_does_not_probe_hardware(tmp_path):
    """build_server with extensions must not eagerly probe hardware resources."""
    config_path = tmp_path / "repos.toml"
    config_path.write_text(
        """
[server]
host = "127.0.0.1"
port = 8765
output_mode = "structured"
enable_extensions = true

[repos.test_repo]
name = "test"
root = "."
"""
    )
    with patch("token_context_mcp.sampling.router.probe_hardware") as mock_probe:
        server = build_server(config_path, enable_extensions=True)
        assert server is not None
        mock_probe.assert_not_called()


def test_sampling_router_lazy_probe_and_caching():
    """Initializing SamplingRouter does not probe; 2 x summarize probes only once."""
    mock_profile = HardwareProfile(
        has_cuda=False,
        vram_gb=0.0,
        ram_gb=16.0,
        has_ollama=False,
        recommended_backend="heuristic_fallback",
        backend_mode="heuristic_fallback",
    )

    with patch("token_context_mcp.sampling.router.probe_hardware", return_value=mock_profile) as mock_probe:
        router = SamplingRouter()
        # Router created: no probe yet
        mock_probe.assert_not_called()

        # First summarize calls probe
        router.summarize("def foo(): pass")
        assert mock_probe.call_count == 1

        # Second summarize uses cached profile on router
        router.summarize("def bar(): pass")
        assert mock_probe.call_count == 1


def test_probe_hardware_process_cache_ttl():
    """probe_hardware caches result within TTL."""
    p1 = probe_hardware()
    assert isinstance(p1, HardwareProfile)

    # Calling again returns cached object
    p2 = probe_hardware()
    assert p1 is p2

    # Force refresh gives new object or re-evaluates
    p3 = probe_hardware(force_refresh=True)
    assert p3 is not None


def test_memory_service_dependency_injection():
    """MemoryService receives router via DI and uses it during consolidate."""
    mock_router = MagicMock()
    mock_router.summarize.return_value = {
        "status": "success",
        "engine": "mock_engine",
        "data": {"insights": "test"},
    }

    mem = MemoryService(":memory:", router=mock_router)
    assert mem.router is mock_router

    mem.memory_put("k1", "val1")
    res = mem.memory_consolidate()
    assert res["status"] == "consolidated"
    mock_router.summarize.assert_called_once()


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows ctypes test")
def test_windows_ctypes_ram_query():
    """On Windows, ctypes GlobalMemoryStatusEx successfully retrieves ram_gb."""
    profile = probe_hardware(force_refresh=True)
    assert profile.ram_gb > 0.0

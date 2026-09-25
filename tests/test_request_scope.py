"""Tests for M3.6 request_scope context manager in RetrievalService and inspect_symbol."""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any

import pytest

from token_context_mcp.config import AppConfig, RepositoryConfig, ServerConfig, save_config, load_config
from token_context_mcp.index.runner import build_index
from token_context_mcp.retrieve.freshness import FreshnessCache
from token_context_mcp.retrieve.service import RetrievalService
from token_context_mcp.retrieve.workflows import CompositeWorkflowEngine


@pytest.fixture()
def request_scope_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "main.py").write_text(
        """def helper():
    return 42

def target_symbol():
    return helper()
""",
        encoding="utf-8",
    )
    config_path = tmp_path / "config" / "repos.toml"
    repo = RepositoryConfig(repo_id="test-scope", root=repo_root.resolve())
    save_config(config_path, AppConfig(repositories={"test-scope": repo}, server=ServerConfig()))
    build_index(repo, config_path.parent / "indexes", network_policy="declared-deny-not-enforced")
    return config_path


def test_inspect_symbol_uses_request_scope_one_freshness_zero_hashes(
    request_scope_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = request_scope_repo
    cfg = load_config(config_path)
    service = RetrievalService(cfg, config_path)
    engine = CompositeWorkflowEngine(service)

    compute_calls = 0
    orig_compute = FreshnessCache._compute_snapshot

    def counting_compute(self: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal compute_calls
        compute_calls += 1
        return orig_compute(self, *args, **kwargs)

    monkeypatch.setattr(FreshnessCache, "_compute_snapshot", counting_compute)

    sha256_calls = 0
    orig_sha256 = hashlib.sha256

    def counting_sha256(*args: Any, **kwargs: Any) -> Any:
        nonlocal sha256_calls
        sha256_calls += 1
        return orig_sha256(*args, **kwargs)

    monkeypatch.setattr(hashlib, "sha256", counting_sha256)

    # Call inspect_symbol
    res = engine.inspect_symbol("test-scope", query="target_symbol")
    assert res["data"]["status"] == "resolved"
    assert res["data"]["target_symbol_id"] is not None

    # Freshness computed exactly once
    assert compute_calls == 1, f"Expected 1 freshness computation, got {compute_calls}"

    # 0 sha256 hashing calls when repository files have not changed
    assert sha256_calls == 0, f"Expected 0 sha256 calls, got {sha256_calls}"

    # Active scope is reset after exiting context
    assert service._active_scope is None


def test_request_scope_thread_isolation(request_scope_repo: Path) -> None:
    config_path = request_scope_repo
    cfg = load_config(config_path)
    service = RetrievalService(cfg, config_path)

    scopes_in_threads: dict[int, str | None] = {}
    barrier = threading.Barrier(2)

    def worker(repo_id: str) -> None:
        tid = threading.get_ident()
        with service.request_scope(repo_id):
            barrier.wait()
            scopes_in_threads[tid] = service._active_scope.repo_id if service._active_scope else None

    t1 = threading.Thread(target=worker, args=("test-scope",))
    t2 = threading.Thread(target=worker, args=("test-scope",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(scopes_in_threads) == 2
    assert all(val == "test-scope" for val in scopes_in_threads.values())
    assert service._active_scope is None

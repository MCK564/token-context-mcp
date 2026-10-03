"""Tests for M3.2 ReadConnectionPool, index optimization, and schema v2.2 compatibility."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from token_context_mcp.config import AppConfig, RepositoryConfig, ServerConfig, index_directory, save_config, load_config
from token_context_mcp.index.runner import build_index, current_pointer_path
from token_context_mcp.index.sqlite_store import ReadConnectionPool, SQLiteStore
from token_context_mcp.retrieve.service import RetrievalService


@pytest.fixture()
def pool_repo_config(tmp_path: Path) -> tuple[Path, Path]:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "sample.py").write_text(
        "def alpha_func(): pass\ndef beta_func(): pass\nclass MyClass: pass\n",
        encoding="utf-8",
    )

    config_path = tmp_path / "config" / "repos.toml"
    repo = RepositoryConfig(repo_id="test-pool", root=repo_root.resolve())
    save_config(config_path, AppConfig(repositories={"test-pool": repo}, server=ServerConfig()))
    build_index(repo, config_path.parent / "indexes", network_policy="declared-deny-not-enforced")
    return config_path, repo_root


def test_pool_single_thread_connect_once(pool_repo_config: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    config_path, _ = pool_repo_config
    cfg = load_config(config_path)
    service = RetrievalService(cfg, config_path)

    connect_calls = 0
    orig_connect = sqlite3.connect

    def counting_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        nonlocal connect_calls
        connect_calls += 1
        return orig_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", counting_connect)

    # 10 consecutive calls to find_symbols on the same thread
    for _ in range(10):
        res = service.find_symbols("test-pool", pattern="alpha", limit=5)
        assert len(res["data"]["symbols"]) >= 1

    # sqlite3.connect should be called exactly once
    assert connect_calls == 1


def test_pool_parallel_threads_distinct_connections(pool_repo_config: tuple[Path, Path]) -> None:
    config_path, _ = pool_repo_config
    cfg = load_config(config_path)
    service = RetrievalService(cfg, config_path)

    conns: list[sqlite3.Connection] = []
    lock = threading.Lock()

    # Both threads must be alive together: a finished thread's ident can be reused by the next one,
    # which would legitimately hand back the same per-thread connection.
    barrier = threading.Barrier(2)

    def worker() -> None:
        store = service._store("test-pool")
        with store.connection() as conn:
            with lock:
                conns.append(conn)
            barrier.wait(timeout=10)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(conns) == 2
    # Two distinct connection instances for two threads
    assert conns[0] is not conns[1]


def test_pool_pointer_switch_closes_old_connections(pool_repo_config: tuple[Path, Path]) -> None:
    config_path, repo_root = pool_repo_config
    cfg = load_config(config_path)
    service = RetrievalService(cfg, config_path)
    repo = cfg.repositories["test-pool"]
    idx_dir = index_directory(config_path)

    # Make an initial query so pool creates connection to DB 1
    res1 = service.find_symbols("test-pool", pattern="alpha", limit=5)
    assert len(res1["data"]["symbols"]) >= 1

    ptr_file = current_pointer_path(idx_dir, "test-pool")
    data1 = json.loads(ptr_file.read_text(encoding="utf-8"))
    old_db_path = str((idx_dir / data1["db"]).resolve())

    # Check pool has connection for this path
    with service._pool._lock:
        active_keys = [k for k in service._pool._connections if k[1] == old_db_path]
        assert len(active_keys) >= 1
        old_conn = service._pool._connections[active_keys[0]]

    # Re-index to create DB 2
    (repo_root / "sample.py").write_text("def gamma_func(): pass\n", encoding="utf-8")
    time.sleep(0.05)
    build_index(repo, idx_dir, network_policy="declared-deny-not-enforced")

    # Force cache expiry by waiting > 1.0s or resetting cache timestamp
    service._pointer_cache["test-pool"] = (0.0, Path(old_db_path), data1["index_run_id"])

    # Query again
    res2 = service.find_symbols("test-pool", pattern="gamma", limit=5)
    assert len(res2["data"]["symbols"]) >= 1

    # Verify old connection was closed and removed from pool
    with service._pool._lock:
        remaining_old = [k for k in service._pool._connections if k[1] == old_db_path]
        assert len(remaining_old) == 0

    # Checking that old_conn is closed (executing on closed connection raises sqlite3.ProgrammingError)
    with pytest.raises(sqlite3.ProgrammingError):
        old_conn.execute("SELECT 1;")


def test_pool_legacy_schema_warning(pool_repo_config: tuple[Path, Path]) -> None:
    config_path, _ = pool_repo_config
    idx_dir = index_directory(config_path)
    ptr_file = current_pointer_path(idx_dir, "test-pool")
    data = json.loads(ptr_file.read_text(encoding="utf-8"))
    db_path = idx_dir / data["db"]

    # Modify metadata in DB to set index_schema_version = "2.1"
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE metadata SET value = ? WHERE key = 'index_schema_version';", (json.dumps("2.1"),))
    conn.commit()
    conn.close()

    cfg = load_config(config_path)
    service = RetrievalService(cfg, config_path)

    # 1. find_symbols returns results with warning
    res = service.find_symbols("test-pool", pattern="alpha", limit=5)
    assert len(res["data"]["symbols"]) >= 1
    assert "index_schema_outdated_reindex_recommended" in res["warnings"]

    # 2. status returns results with warning
    stat = service.status("test-pool")
    assert stat["data"]["index_schema_version"] == "2.1"
    assert "index_schema_outdated_reindex_recommended" in stat["warnings"]

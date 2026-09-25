"""Tests for M3.2a Versioned Snapshots, Pointer file, and snapshot GC."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from token_context_mcp.config import AppConfig, RepositoryConfig, ServerConfig, save_config, index_directory
from token_context_mcp.index.runner import build_index, current_pointer_path, gc_snapshots
from token_context_mcp.retrieve.service import RetrievalService


@pytest.fixture()
def versioned_repo_config(tmp_path: Path) -> tuple[Path, Path]:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "main.py").write_text("def sample_func_one(): pass\n", encoding="utf-8")

    config_path = tmp_path / "config" / "repos.toml"
    repo = RepositoryConfig(repo_id="test-snap", root=repo_root.resolve())
    save_config(config_path, AppConfig(repositories={"test-snap": repo}, server=ServerConfig()))
    build_index(repo, config_path.parent / "indexes", network_policy="declared-deny-not-enforced")
    return config_path, repo_root


def test_concurrent_read_during_reindex(versioned_repo_config: tuple[Path, Path]) -> None:
    config_path, repo_root = versioned_repo_config
    from token_context_mcp.config import load_config
    cfg = load_config(config_path)
    service = RetrievalService(cfg, config_path)
    repo = cfg.repositories["test-snap"]
    idx_dir = index_directory(config_path)

    # Verify pointer file exists
    ptr_file = current_pointer_path(idx_dir, "test-snap")
    assert ptr_file.is_file()
    initial_ptr = json.loads(ptr_file.read_text(encoding="utf-8"))
    initial_run_id = initial_ptr["index_run_id"]
    assert initial_run_id

    stop_reader = threading.Event()
    reader_exceptions: list[Exception] = []
    read_count = 0

    def reader_loop() -> None:
        nonlocal read_count
        while not stop_reader.is_set():
            try:
                res = service.find_symbols("test-snap", pattern="sample_func", limit=5)
                assert len(res["data"]["symbols"]) >= 1
                read_count += 1
            except Exception as e:
                reader_exceptions.append(e)
            time.sleep(0.01)

    t_reader = threading.Thread(target=reader_loop)
    t_reader.start()

    run_ids: list[str] = [initial_run_id]
    try:
        # Re-index 3 times
        for i in range(1, 4):
            (repo_root / "main.py").write_text(f"def sample_func_{i}(): pass\n", encoding="utf-8")
            time.sleep(0.05)
            manifest = build_index(repo, idx_dir, network_policy="declared-deny-not-enforced")
            new_run_id = str(manifest["index_run_id"])
            run_ids.append(new_run_id)

            # Within <= 1.1s, service._store sees new index_run_id
            t0 = time.monotonic()
            updated = False
            while time.monotonic() - t0 <= 1.2:
                st = service._store("test-snap")
                if st.metadata().get("index_run_id") == new_run_id:
                    updated = True
                    break
                time.sleep(0.05)
            assert updated is True, f"Service failed to see new index_run_id {new_run_id} within 1s"
    finally:
        stop_reader.set()
        t_reader.join(timeout=2.0)

    # 1. No reader exceptions
    assert not reader_exceptions, f"Reader thread encountered exceptions: {reader_exceptions}"
    assert read_count > 5, f"Reader ran too few iterations: {read_count}"

    # 2. Test GC of old snapshots using max_age_seconds=0.0
    latest_db = json.loads(ptr_file.read_text(encoding="utf-8"))["db"]
    sqlite_files_before = list(idx_dir.glob("test-snap.*.sqlite"))
    assert len(sqlite_files_before) >= 3

    # Run GC with max_age_seconds=0
    removed = gc_snapshots(idx_dir, "test-snap", current_db_name=latest_db, max_age_seconds=0.0)
    assert len(removed) >= 2

    # Latest DB was not removed
    assert (idx_dir / latest_db).exists()

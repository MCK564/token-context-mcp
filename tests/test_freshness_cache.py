"""Tests for M3.1 FreshnessCache and fast freshness detection."""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Any

import pytest

from token_context_mcp.config import AppConfig, RepositoryConfig, ServerConfig, save_config
from token_context_mcp.index.runner import build_index
from token_context_mcp.models import FileRecord
from token_context_mcp.retrieve.freshness import FreshnessCache
from token_context_mcp.retrieve.service import RetrievalService


@pytest.fixture()
def fresh_repo_config(tmp_path: Path) -> tuple[Path, Path]:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "main.py").write_text("def hello(): pass\n", encoding="utf-8")
    (repo_root / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    (repo_root / "config.json").write_text('{"v": 1}\n', encoding="utf-8")
    sub = repo_root / "pkg"
    sub.mkdir()
    (sub / "submod.py").write_text("def sub(): pass\n", encoding="utf-8")

    config_path = tmp_path / "config" / "repos.toml"
    repo = RepositoryConfig(repo_id="test-fresh", root=repo_root.resolve())
    save_config(config_path, AppConfig(repositories={"test-fresh": repo}, server=ServerConfig()))
    build_index(repo, config_path.parent / "indexes", network_policy="declared-deny-not-enforced")
    return config_path, repo_root


def test_freshness_cache_ttl_avoids_stat_and_hash(fresh_repo_config: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    config_path, repo_root = fresh_repo_config
    from token_context_mcp.config import load_config
    cfg = load_config(config_path)
    service = RetrievalService(cfg, config_path)

    # Initial call to populate cache
    res1 = service.status("test-fresh")
    assert res1["freshness"] == "fresh"

    # Count os.stat and hashlib calls on second call within TTL
    repo_file_stat_calls = 0
    hash_calls = 0

    orig_stat = os.stat
    orig_sha256 = hashlib.sha256

    resolved_root = repo_root.resolve()

    def counting_stat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        nonlocal repo_file_stat_calls
        try:
            p = Path(path).resolve()
            if resolved_root in p.parents or p == resolved_root:
                repo_file_stat_calls += 1
        except Exception:
            pass
        return orig_stat(path, *args, **kwargs)

    def counting_sha256(data: bytes = b"", *args: Any, **kwargs: Any) -> Any:
        nonlocal hash_calls
        hash_calls += 1
        return orig_sha256(data, *args, **kwargs)

    monkeypatch.setattr(os, "stat", counting_stat)
    monkeypatch.setattr(hashlib, "sha256", counting_sha256)

    res2 = service.status("test-fresh")
    assert res2["freshness"] == "fresh"
    # Within TTL (2s), 0 repo file stat calls and 0 hash calls
    assert repo_file_stat_calls == 0
    assert hash_calls == 0


def test_touch_mtime_without_content_change_hashes_once_and_stays_fresh(fresh_repo_config: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    config_path, repo_root = fresh_repo_config
    from token_context_mcp.config import load_config
    cfg = load_config(config_path)
    service = RetrievalService(cfg, config_path)

    # Touch mtime of main.py without changing content
    main_py = repo_root / "main.py"
    stat_before = main_py.stat()
    new_mtime = stat_before.st_mtime + 50.0
    os.utime(main_py, (new_mtime, new_mtime))

    # Invalidate snapshot cache to force re-check
    service._freshness_cache.invalidate()

    hash_calls = 0
    orig_sha256 = hashlib.sha256

    def counting_sha256(data: bytes = b"", *args: Any, **kwargs: Any) -> Any:
        nonlocal hash_calls
        hash_calls += 1
        return orig_sha256(data, *args, **kwargs)

    monkeypatch.setattr(hashlib, "sha256", counting_sha256)

    res = service.status("test-fresh")
    assert res["freshness"] == "fresh"
    # main.py was touched so it is hashed once to verify content
    assert hash_calls == 1

    # Second check (even after invalidating snapshot cache, because _hash_cache caches by (path, size, mtime)):
    service._freshness_cache.invalidate()
    hash_calls = 0
    res2 = service.status("test-fresh")
    assert res2["freshness"] == "fresh"
    assert hash_calls == 0


def test_added_python_file_detected_stale(fresh_repo_config: tuple[Path, Path]) -> None:
    config_path, repo_root = fresh_repo_config
    from token_context_mcp.config import load_config
    cfg = load_config(config_path)
    service = RetrievalService(cfg, config_path)

    # Add a new supported python file
    new_file = repo_root / "new_mod.py"
    new_file.write_text("def new_func(): pass\n", encoding="utf-8")

    service._freshness_cache.invalidate()
    res = service.status("test-fresh")
    assert res["freshness"] == "stale"
    assert "new_mod.py" in res["data"]["added_paths"]


def test_edit_readme_stays_fresh_and_recorded_in_changed_non_indexed(fresh_repo_config: tuple[Path, Path]) -> None:
    config_path, repo_root = fresh_repo_config
    from token_context_mcp.config import load_config
    cfg = load_config(config_path)
    service = RetrievalService(cfg, config_path)

    # Modify README.md (unsupported extension / docs)
    readme = repo_root / "README.md"
    readme.write_text("# Updated Documentation\nExtra notes.\n", encoding="utf-8")

    service._freshness_cache.invalidate()
    res = service.status("test-fresh")
    assert res["freshness"] == "fresh"
    assert "README.md" in res["data"]["changed_non_indexed"]
    assert "README.md" not in res["data"]["pending_paths"]


def test_search_source_repeated_calls_zero_hash(fresh_repo_config: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    config_path, repo_root = fresh_repo_config
    from token_context_mcp.config import load_config
    cfg = load_config(config_path)
    service = RetrievalService(cfg, config_path)

    # Warm-up call
    res1 = service.search_source("test-fresh", query="hello", limit=5)
    assert len(res1["data"]["matches"]) > 0

    # Count hashes during second search_source call
    hash_calls = 0
    orig_sha256 = hashlib.sha256

    def counting_sha256(data: bytes = b"", *args: Any, **kwargs: Any) -> Any:
        nonlocal hash_calls
        hash_calls += 1
        return orig_sha256(data, *args, **kwargs)

    monkeypatch.setattr(hashlib, "sha256", counting_sha256)

    res2 = service.search_source("test-fresh", query="hello", limit=5)
    assert len(res2["data"]["matches"]) > 0
    # Zero hash operations when repo files have not changed
    assert hash_calls == 0


def test_indexed_json_change_reported_in_changed_non_indexed_and_repo_stays_fresh(fresh_repo_config: tuple[Path, Path]) -> None:
    config_path, repo_root = fresh_repo_config
    from token_context_mcp.config import load_config
    cfg = load_config(config_path)
    service = RetrievalService(cfg, config_path)

    # Edit config.json (indexed file with parse_status="not_parsed")
    cfg_json = repo_root / "config.json"
    cfg_json.write_text('{"v": 2, "updated": true}\n', encoding="utf-8")

    service._freshness_cache.invalidate()
    res = service.status("test-fresh")
    assert res["freshness"] == "fresh"
    assert "config.json" in res["data"]["changed_non_indexed"]
    assert "config.json" not in res["data"]["pending_paths"]
    assert res["data"]["pending_path_count"] == 0


def test_unindexed_json_or_md_file_ignored_by_fast_freshness_scan(fresh_repo_config: tuple[Path, Path]) -> None:
    config_path, repo_root = fresh_repo_config
    from token_context_mcp.config import load_config
    cfg = load_config(config_path)
    service = RetrievalService(cfg, config_path)

    # Create new .json and .md files that were not in index
    (repo_root / "eval_out.json").write_text('{"eval": true}\n', encoding="utf-8")
    (repo_root / "NOTES.md").write_text("# My notes\n", encoding="utf-8")

    service._freshness_cache.invalidate()
    res = service.status("test-fresh")
    assert res["freshness"] == "fresh"
    assert "eval_out.json" not in res["data"]["added_paths"]
    assert "NOTES.md" not in res["data"]["added_paths"]
    assert "eval_out.json" not in res["data"]["pending_paths"]
    assert "NOTES.md" not in res["data"]["pending_paths"]
    assert res["data"]["pending_path_count"] == 0


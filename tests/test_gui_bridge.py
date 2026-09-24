from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from token_context_mcp.gui.bridge import (
    CacheManager,
    RepoManager,
    ServerController,
    detect_ai_hardware,
)


@pytest.fixture
def temp_config_env():
    with tempfile.TemporaryDirectory(prefix="tcmcp_gui_test_") as tmpdir:
        config_path = Path(tmpdir) / "repos.toml"
        repo_dir = Path(tmpdir) / "sample-repo"
        repo_dir.mkdir()
        (repo_dir / "main.py").write_text("def hello(): pass\n", encoding="utf-8")
        yield config_path, repo_dir


def test_repo_manager_crud(temp_config_env):
    config_path, repo_dir = temp_config_env
    mgr = RepoManager(config_path)

    # 1. Initial list should be empty
    repos = mgr.list_repositories()
    assert len(repos) == 0

    # 2. Add repo
    res = mgr.add_repository("sample", repo_dir)
    assert res["repo_id"] == "sample"

    # 3. List should show repo
    repos = mgr.list_repositories()
    assert len(repos) == 1
    assert repos[0]["repo_id"] == "sample"
    assert repos[0]["freshness"] == "not_indexed"

    # 4. Server config load and update
    cfg = mgr.get_server_config()
    assert "max_result_tokens" in cfg
    mgr.update_server_config({"max_result_tokens": 2048, "enable_extensions": True})
    updated_cfg = mgr.get_server_config()
    assert updated_cfg["max_result_tokens"] == 2048
    assert updated_cfg["enable_extensions"] is True

    # 5. Delete repo
    mgr.delete_repository("sample", purge_db=True)
    assert len(mgr.list_repositories()) == 0


def test_cache_manager(temp_config_env):
    config_path, _ = temp_config_env
    cache_mgr = CacheManager(config_path)

    stats = cache_mgr.get_storage_stats()
    assert "total_size_mb" in stats
    assert "databases" in stats
    assert stats["databases_count"] == 0

    # Vacuum on empty should succeed
    reclaimed = cache_mgr.vacuum_database()
    assert reclaimed >= 0


def test_ai_hardware_detection():
    hw = detect_ai_hardware()
    assert isinstance(hw, str)
    assert len(hw) > 0


def test_server_controller_configs(temp_config_env):
    config_path, _ = temp_config_env
    ctrl = ServerController(config_path)

    claude_cfg = ctrl.get_client_config("claude")
    assert "mcpServers" in claude_cfg
    assert "token-context" in claude_cfg

    vscode_cfg = ctrl.get_client_config("vscode")
    assert "servers" in vscode_cfg
    assert "token-context" in vscode_cfg

    antigravity_cfg = ctrl.get_client_config("antigravity")
    assert "mcpServers" in antigravity_cfg

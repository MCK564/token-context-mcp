from __future__ import annotations

import json
from pathlib import Path

import pytest

from token_context_mcp.config import (
    default_config_path,
    load_config,
    save_config,
    unregister_repository,
    update_repository,
)
from token_context_mcp.models import AppConfig, RepositoryConfig, ServerConfig
from token_context_mcp.retrieve.service import RetrievalError, RetrievalService
from token_context_mcp.retrieve.token_budget import estimate_tokens


def test_explicit_global_config_override_is_independent_of_working_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    configured = tmp_path / "shared" / "repos.toml"
    monkeypatch.setenv("TOKEN_CONTEXT_CONFIG", str(configured))
    assert default_config_path() == configured.resolve()


def test_configured_result_cap_is_enforced(indexed_config: Path) -> None:
    config = load_config(indexed_config)
    save_config(
        indexed_config,
        AppConfig(
            repositories=config.repositories,
            server=ServerConfig(max_result_tokens=256, max_graph_nodes=2, max_symbol_results=1),
        ),
    )
    service = RetrievalService(load_config(indexed_config), indexed_config)
    with pytest.raises(RetrievalError, match="between 32 and 256"):
        service.repo_map("demo", budget_tokens=257)
    response = service.find_symbols("demo", pattern="a", limit=20)
    assert len(response["data"]["symbols"]) <= 1
    assert "symbol_limit_capped_by_server" in response["warnings"]


def test_cap_warnings_describe_actual_truncation(indexed_config: Path) -> None:
    config = load_config(indexed_config)
    service = RetrievalService(config, indexed_config)
    alpha = service.find_symbols("demo", pattern="alpha", limit=1)["data"]["symbols"][0]

    # The request is larger than the server cap, but alpha's graph has only
    # alpha -> beta, so traversal finishes before the cap binds.
    complete = service.impact_slice("demo", symbol_id=alpha["symbol_id"], depth=1, max_nodes=500)
    assert complete["data"]["nodes_visited"] == 2
    assert complete["data"]["node_limit_reached"] is False
    assert "graph_node_limit_capped_by_server" not in complete["warnings"]

    save_config(
        indexed_config,
        AppConfig(
            repositories=config.repositories,
            server=ServerConfig(max_result_tokens=8192, max_graph_nodes=1, max_symbol_results=20),
        ),
    )
    capped_service = RetrievalService(load_config(indexed_config), indexed_config)
    capped = capped_service.impact_slice("demo", symbol_id=alpha["symbol_id"], depth=1, max_nodes=500)
    assert capped["data"]["nodes_visited"] == 1
    assert capped["data"]["node_limit_reached"] is True
    assert capped["truncated"] is True
    assert "graph_node_limit_capped_by_server" in capped["warnings"]


def test_symbol_cap_warning_requires_more_matching_rows(indexed_config: Path) -> None:
    config = load_config(indexed_config)
    save_config(
        indexed_config,
        AppConfig(
            repositories=config.repositories,
            server=ServerConfig(max_result_tokens=256, max_graph_nodes=2, max_symbol_results=1),
        ),
    )
    service = RetrievalService(load_config(indexed_config), indexed_config)
    response = service.find_symbols("demo", pattern="does-not-exist", limit=20)
    assert response["data"]["symbols"] == []
    assert response["data"]["omitted_count"] == 0
    assert response["truncated"] is False
    assert "symbol_limit_capped_by_server" not in response["warnings"]


def test_no_tool_exceeds_server_max_result_tokens(indexed_config: Path) -> None:
    config = load_config(indexed_config)
    save_config(
        indexed_config,
        AppConfig(
            repositories=config.repositories,
            server=ServerConfig(max_result_tokens=256, max_graph_nodes=2, max_symbol_results=1),
        ),
    )
    service = RetrievalService(load_config(indexed_config), indexed_config)
    alpha = service.find_symbols("demo", pattern="alpha", limit=1)["data"]["symbols"][0]
    responses = [
        service.status("demo"),
        service.repo_map("demo", budget_tokens=256),
        service.file_skeleton("demo", path="app.py", max_tokens=256),
        service.symbol_context("demo", symbol_id=alpha["symbol_id"], max_tokens=256),
        service.impact_slice("demo", symbol_id=alpha["symbol_id"], depth=3, max_nodes=500),
    ]
    for response in responses:
        assert estimate_tokens(json.dumps(response)) <= 256


def test_update_requires_force_and_unregister_removes_registration(tmp_path: Path) -> None:
    config_path = tmp_path / "repos.toml"
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    save_config(config_path, AppConfig(repositories={"demo": RepositoryConfig(repo_id="demo", root=first)}))
    with pytest.raises(Exception, match="requires --force"):
        update_repository(config_path, "demo", second)
    updated = update_repository(config_path, "demo", second, force=True)
    assert updated.root == second.resolve()
    removed = unregister_repository(config_path, "demo")
    assert removed.root == second.resolve()
    assert "demo" not in load_config(config_path).repositories

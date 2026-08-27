from __future__ import annotations

from pathlib import Path

import pytest

from token_context_mcp.config import default_config_path, load_config, save_config
from token_context_mcp.models import AppConfig, ServerConfig
from token_context_mcp.retrieve.service import RetrievalError, RetrievalService


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
            server=ServerConfig(max_result_tokens=64, max_graph_nodes=2, max_symbol_results=1),
        ),
    )
    service = RetrievalService(load_config(indexed_config), indexed_config)
    with pytest.raises(RetrievalError, match="between 32 and 64"):
        service.repo_map("demo", budget_tokens=65)
    response = service.find_symbols("demo", pattern="a", limit=20)
    assert len(response["data"]["symbols"]) <= 1
    assert "symbol_limit_capped_by_server" in response["warnings"]

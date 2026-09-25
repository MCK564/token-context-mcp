"""Tests for M3.4 index-time global PageRank and ranking table."""
from __future__ import annotations

from pathlib import Path
import pytest

from token_context_mcp.config import AppConfig, RepositoryConfig, ServerConfig, save_config, load_config
from token_context_mcp.index.runner import build_index
from token_context_mcp.models import EdgeRecord, SymbolRecord
from token_context_mcp.retrieve.ranking import compute_global_ranks
from token_context_mcp.retrieve.service import RetrievalService


def _make_symbol(symbol_id: str, name: str, path: str = "src/main.py", roles: list[str] | None = None) -> SymbolRecord:
    return SymbolRecord(
        symbol_id=symbol_id,
        path=path,
        name=name,
        qualified_name=f"main.{name}",
        kind="function",
        signature="() -> None",
        start_line=1,
        end_line=5,
        start_byte=0,
        end_byte=50,
        body_start_byte=10,
        body_end_byte=50,
        is_private=False,
        roles=roles or [],
    )


def _make_edge(src: str, tgt: str, confidence: float = 0.9) -> EdgeRecord:
    return EdgeRecord(
        source_symbol_id=src,
        target_symbol_id=tgt,
        target_name=tgt,
        edge_kind="call",
        status="resolved",
        backend="ast",
        confidence=confidence,
        source_path="src/main.py",
        source_line=2,
        evidence=[],
    )


def test_compute_global_ranks_basic() -> None:
    s1 = _make_symbol("s1", "caller")
    s2 = _make_symbol("s2", "mid")
    s3 = _make_symbol("s3", "callee")
    s4 = _make_symbol("s4", "isolated")

    e1 = _make_edge("s1", "s2", 0.9)
    e2 = _make_edge("s2", "s3", 0.8)

    ranks = compute_global_ranks([s1, s2, s3, s4], [e1, e2])
    assert len(ranks) == 4
    rank_dict = {item[0]: (item[1], item[2]) for item in ranks}

    # mid and callee receive forward flow; caller receives reverse flow
    assert rank_dict["s2"][0] > rank_dict["s4"][0]
    assert rank_dict["s3"][0] > rank_dict["s4"][0]
    assert any("pagerank:" in b for b in rank_dict["s1"][1])


def test_compute_global_ranks_utility_trap_dampened() -> None:
    symbols = [_make_symbol(f"caller_{i}", f"caller_{i}") for i in range(12)]
    util = _make_symbol("util", "helper_leaf")
    symbols.append(util)

    # 12 callers call util, util calls nothing
    edges = [_make_edge(f"caller_{i}", "util", 0.95) for i in range(12)]

    ranks = compute_global_ranks(symbols, edges)
    rank_dict = {item[0]: (item[1], item[2]) for item in ranks}

    # util has high in-degree z-score and out-degree 0 -> utility trap triggered
    assert "utility_trap_dampened" in rank_dict["util"][1]


def test_compute_global_ranks_role_bonuses() -> None:
    s1 = _make_symbol("s1", "cli_main", roles=["declared_entry_point"])
    s2 = _make_symbol("s2", "plain_func")

    ranks = compute_global_ranks([s1, s2], [])
    rank_dict = {item[0]: (item[1], item[2]) for item in ranks}

    assert rank_dict["s1"][0] >= rank_dict["s2"][0] + 3.0
    assert "role:declared_entry_point" in rank_dict["s1"][1]


@pytest.fixture()
def global_rank_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "app.py").write_text(
        """def core_service():
    return 1

def entry():
    return core_service()
""",
        encoding="utf-8",
    )
    config_path = tmp_path / "config" / "repos.toml"
    repo = RepositoryConfig(repo_id="test-gr", root=repo_root.resolve())
    save_config(config_path, AppConfig(repositories={"test-gr": repo}, server=ServerConfig()))
    build_index(repo, config_path.parent / "indexes", network_policy="declared-deny-not-enforced")
    return config_path


def test_repo_map_global_mode_uses_symbol_rank_table(global_rank_repo: Path) -> None:
    config_path = global_rank_repo
    cfg = load_config(config_path)
    service = RetrievalService(cfg, config_path)

    # Global mode: query is None
    res = service.repo_map("test-gr", query=None, budget_tokens=2048)
    assert "global_rank_table_missing" not in res["warnings"]
    assert len(res["data"]["symbols"]) >= 2

    # Check store has symbol_rank table
    _, store, _ = service._repository_store("test-gr")
    assert store.has_symbol_rank()
    ranks = store.symbol_ranks()
    assert len(ranks) >= 2


def test_repo_map_global_mode_fallback_warning_when_table_missing(global_rank_repo: Path) -> None:
    config_path = global_rank_repo
    cfg = load_config(config_path)
    service = RetrievalService(cfg, config_path)

    # Drop symbol_rank table to simulate legacy DB
    from token_context_mcp.index.sqlite_store import SQLiteStore
    _, store, _ = service._repository_store("test-gr")
    write_store = SQLiteStore(store.path, read_only=False)
    with write_store.connection() as conn:
        conn.execute("DROP TABLE symbol_rank")

    # Invalidate graph cache
    service._graph_cache.invalidate("test-gr")

    res = service.repo_map("test-gr", query=None, budget_tokens=2048)
    assert "global_rank_table_missing" in res["warnings"]

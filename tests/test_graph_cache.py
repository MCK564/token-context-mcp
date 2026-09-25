"""Tests for M3.3 in-memory graph cache and CSR representation."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import pytest

from token_context_mcp.config import AppConfig, RepositoryConfig, ServerConfig, save_config, load_config
from token_context_mcp.index.runner import build_index
from token_context_mcp.models import EdgeRecord, FileRecord, SymbolRecord
from token_context_mcp.retrieve.graph_cache import GraphCache, RepoGraph
from token_context_mcp.retrieve.service import RetrievalService


@pytest.fixture()
def graph_cache_repo(tmp_path: Path) -> tuple[Path, RepositoryConfig]:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "module_a.py").write_text(
        """def func_a():
    return 1

def func_b():
    return func_a()
""",
        encoding="utf-8",
    )
    (repo_root / "module_b.py").write_text(
        """from module_a import func_b

def func_c():
    return func_b()
""",
        encoding="utf-8",
    )
    config_path = tmp_path / "config" / "repos.toml"
    repo = RepositoryConfig(repo_id="test-gc", root=repo_root.resolve())
    save_config(config_path, AppConfig(repositories={"test-gc": repo}, server=ServerConfig()))
    build_index(repo, config_path.parent / "indexes", network_policy="declared-deny-not-enforced")
    return config_path, repo


def test_repo_map_second_call_zero_sqlite_queries(graph_cache_repo: tuple[Path, RepositoryConfig]) -> None:
    config_path, _ = graph_cache_repo
    cfg = load_config(config_path)
    service = RetrievalService(cfg, config_path)

    # First call warms cache
    res1 = service.repo_map("test-gc", budget_tokens=2048)
    assert len(res1["data"]["symbols"]) >= 3

    # Second call uses in-memory graph cache
    res2 = service.repo_map("test-gc", budget_tokens=2048)
    assert len(res2["data"]["symbols"]) == len(res1["data"]["symbols"])
    assert service.last_query_count == 0


def test_impact_slice_second_call_zero_sqlite_queries(graph_cache_repo: tuple[Path, RepositoryConfig]) -> None:
    config_path, _ = graph_cache_repo
    cfg = load_config(config_path)
    service = RetrievalService(cfg, config_path)

    # First find a symbol
    res_symbols = service.find_symbols("test-gc", pattern="func_c")
    sym_id = res_symbols["data"]["symbols"][0]["symbol_id"]

    # First impact_slice call warms graph cache
    res1 = service.impact_slice("test-gc", symbol_id=sym_id, direction="callees")
    assert len(res1["data"]["symbols"]) >= 1

    # Second call should make 0 sqlite queries
    res2 = service.impact_slice("test-gc", symbol_id=sym_id, direction="callees")
    assert len(res2["data"]["symbols"]) == len(res1["data"]["symbols"])
    assert service.last_query_count == 0


def test_graph_cache_refreshed_on_reindex(graph_cache_repo: tuple[Path, RepositoryConfig]) -> None:
    config_path, repo = graph_cache_repo
    cfg = load_config(config_path)
    service = RetrievalService(cfg, config_path)

    res1 = service.repo_map("test-gc", budget_tokens=2048)
    initial_count = len(res1["data"]["symbols"])

    # Add a new file and re-index
    (repo.root / "module_c.py").write_text("def func_d(): return 99\n", encoding="utf-8")
    build_index(repo, config_path.parent / "indexes", network_policy="declared-deny-not-enforced")

    # Invalidate pointer cache or let pointer TTL expire
    service._pointer_cache.clear()

    res2 = service.repo_map("test-gc", budget_tokens=2048)
    assert len(res2["data"]["symbols"]) == initial_count + 1


def test_repo_graph_csr_and_traversal() -> None:
    s1 = SymbolRecord(
        symbol_id="sym1",
        path="a.py",
        name="sym1",
        qualified_name="a.sym1",
        kind="function",
        signature="() -> None",
        start_line=1,
        end_line=2,
        start_byte=0,
        end_byte=20,
        body_start_byte=10,
        body_end_byte=20,
        is_private=False,
    )
    s2 = SymbolRecord(
        symbol_id="sym2",
        path="a.py",
        name="sym2",
        qualified_name="a.sym2",
        kind="function",
        signature="() -> None",
        start_line=3,
        end_line=4,
        start_byte=21,
        end_byte=40,
        body_start_byte=30,
        body_end_byte=40,
        is_private=False,
    )
    s3 = SymbolRecord(
        symbol_id="sym3",
        path="b.py",
        name="sym3",
        qualified_name="b.sym3",
        kind="function",
        signature="() -> None",
        start_line=1,
        end_line=2,
        start_byte=0,
        end_byte=20,
        body_start_byte=10,
        body_end_byte=20,
        is_private=False,
    )
    e1 = EdgeRecord(
        source_symbol_id="sym1",
        target_symbol_id="sym2",
        target_name="sym2",
        edge_kind="calls",
        status="resolved",
        backend="ast",
        confidence=0.9,
        source_path="a.py",
        source_line=2,
        evidence=[],
    )
    e2 = EdgeRecord(
        source_symbol_id="sym2",
        target_symbol_id="sym3",
        target_name="sym3",
        edge_kind="calls",
        status="resolved",
        backend="ast",
        confidence=0.8,
        source_path="a.py",
        source_line=4,
        evidence=[],
    )
    f1 = FileRecord(path="a.py", sha256="hash_a", size=100, mtime_ns=0, language="python", parse_status="ok", warnings=[])
    f2 = FileRecord(path="b.py", sha256="hash_b", size=100, mtime_ns=0, language="python", parse_status="ok", warnings=[])

    graph = RepoGraph(
        repo_id="test",
        index_run_id="run1",
        symbols=[s1, s2, s3],
        edges=[e1, e2],
        files=[f1, f2],
    )

    assert graph.out_offsets == [0, 1, 2, 2]
    assert graph.out_targets == [1, 2]
    assert graph.out_weights == [0.9, 0.8]
    assert graph.in_offsets == [0, 0, 1, 2]
    assert graph.in_sources == [0, 1]
    assert graph.in_weights == [0.9, 0.8]

    # Test traversal
    visited, edges, limit_reached = graph.traverse("sym1", direction="callees", depth=2, max_nodes=10)
    assert visited == ["sym1", "sym2", "sym3"]
    assert len(edges) == 2
    assert not limit_reached


def test_graph_cache_lru_eviction() -> None:
    cache = GraphCache(capacity=3)
    dummy_sym = SymbolRecord(
        symbol_id="s",
        path="a.py",
        name="s",
        qualified_name="s",
        kind="function",
        signature="() -> None",
        start_line=1,
        end_line=1,
        start_byte=0,
        end_byte=10,
        body_start_byte=5,
        body_end_byte=10,
        is_private=False,
    )

    class DummyStore:
        def symbols(self) -> list[SymbolRecord]:
            return [dummy_sym]

        def edges(self) -> list[EdgeRecord]:
            return []

        def files(self) -> list[FileRecord]:
            return []

    store = DummyStore()  # type: ignore

    g1 = cache.get_graph("r1", "run1", store)
    g2 = cache.get_graph("r2", "run1", store)
    g3 = cache.get_graph("r3", "run1", store)

    assert len(cache._cache) == 3

    # Access r1 to make it most-recently used
    _ = cache.get_graph("r1", "run1", store)

    # Insert r4 -> r2 should be evicted (r1 was used, r3 was used after r2)
    _ = cache.get_graph("r4", "run1", store)
    assert len(cache._cache) == 3
    assert ("r2", "run1") not in cache._cache
    assert ("r1", "run1") in cache._cache
    assert ("r3", "run1") in cache._cache
    assert ("r4", "run1") in cache._cache

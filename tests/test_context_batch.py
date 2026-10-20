from __future__ import annotations

from pathlib import Path

from token_context_mcp.config import load_config
from token_context_mcp.retrieve.batch import ContextBatchExecutor
from token_context_mcp.retrieve.service import RetrievalService
from token_context_mcp.retrieve.workflows import CompositeWorkflowEngine


def test_context_batch_executor(indexed_config: Path) -> None:
    config = load_config(indexed_config)
    service = RetrievalService(config, indexed_config)
    wf = CompositeWorkflowEngine(service)
    executor = ContextBatchExecutor(service, wf)

    # 1. Successful chained batch: find symbol, then inspect it
    batch_ops = [
        {"op": "find_symbols", "args": {"pattern": "alpha"}},
        {"op": "get_symbol_context", "args": {"symbol_id": "$prev.data.symbols[0].symbol_id"}},
    ]
    res = executor.execute_batch("demo", batch_ops, budget_tokens=2048)
    assert res["status"] == "success"
    assert res["executed_count"] == 2
    assert res["operations"][0]["op"] == "find_symbols"
    assert res["operations"][1]["op"] == "get_symbol_context"
    sym_res = res["operations"][1]["result"]
    assert "data" in sym_res
    assert sym_res["data"]["root_symbol_id"].endswith("alpha:cb2c1748da59f14e")


def test_context_batch_rejects_mutating_or_invalid_op(indexed_config: Path) -> None:
    config = load_config(indexed_config)
    service = RetrievalService(config, indexed_config)
    wf = CompositeWorkflowEngine(service)
    executor = ContextBatchExecutor(service, wf)

    # Rejection of mutating op
    bad_batch = [{"op": "memory_put", "args": {"key": "k", "value": "v"}}]
    res = executor.execute_batch("demo", bad_batch)
    assert res["status"] == "error"
    assert "not a permitted" in res["error"]


def test_context_batch_bounds(indexed_config: Path) -> None:
    config = load_config(indexed_config)
    service = RetrievalService(config, indexed_config)
    wf = CompositeWorkflowEngine(service)
    executor = ContextBatchExecutor(service, wf)

    # Over 10 operations
    oversized = [{"op": "find_symbols", "args": {"pattern": "x"}}] * 11
    res = executor.execute_batch("demo", oversized)
    assert res["status"] == "error"
    assert "exceeds maximum limit" in res["error"]

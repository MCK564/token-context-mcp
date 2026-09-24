"""Benchmark retrieval tool latencies and hashing overhead (M0 baseline).

Measures p50, p95, and max execution times over 20 iterations per tool,
and counts calls to sha256_file and sha256_bytes via monkeypatching.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from pathlib import Path
from typing import Any, Callable

import token_context_mcp.index.hashing as hashing_mod
import token_context_mcp.retrieve.service as service_mod
from token_context_mcp.config import default_config_path, load_config
from token_context_mcp.retrieve.service import RetrievalService
from token_context_mcp.retrieve.workflows import CompositeWorkflowEngine


def percentile(data: list[float], pct: float) -> float:
    """Calculate percentile from a sorted list of numbers."""
    if not data:
        return 0.0
    if len(data) == 1:
        return data[0]
    data_sorted = sorted(data)
    idx = (len(data_sorted) - 1) * (pct / 100.0)
    floor_idx = math.floor(idx)
    ceil_idx = math.ceil(idx)
    if floor_idx == ceil_idx:
        return data_sorted[int(idx)]
    d0 = data_sorted[floor_idx] * (ceil_idx - idx)
    d1 = data_sorted[ceil_idx] * (idx - floor_idx)
    return d0 + d1


def run_benchmark(
    repo_id: str,
    config_path: Path | None = None,
    iterations: int = 20,
) -> dict[str, Any]:
    cfg_p = config_path or default_config_path()
    config = load_config(cfg_p)
    service = RetrievalService(config, cfg_p)
    workflow = CompositeWorkflowEngine(service)

    # Resolve sample entities for the repo
    from token_context_mcp.config import index_directory
    from token_context_mcp.index.runner import database_path
    from token_context_mcp.index.sqlite_store import SQLiteStore
    idx_dir = index_directory(cfg_p)
    db = database_path(idx_dir, repo_id)
    if db.exists():
        store = SQLiteStore(db)
        all_syms = store.symbols()
        # Prefer a non-test symbol if possible
        code_syms = [s for s in all_syms if not s.path.startswith(("tests/", "evals/"))]
        target_sym = code_syms[0] if code_syms else all_syms[0]
        sample_symbol_id = target_sym.symbol_id
        sample_path = target_sym.path
        sample_name = target_sym.name
    sample_module = sample_path.replace("\\", "/").rsplit(".", 1)[0] if sample_path else None

    # Define tools to benchmark
    tools: list[tuple[str, Callable[[], Any]]] = [
        ("list_repositories", lambda: service.list_repositories()),
        ("get_index_status", lambda: service.status(repo_id)),
        ("get_repo_map@1024", lambda: service.repo_map(repo_id, budget_tokens=1024)),
        ("find_symbols", lambda: service.find_symbols(repo_id, pattern=sample_name, limit=10)),
        ("search_source", lambda: service.search_source(repo_id, query=sample_name, limit=10)),
    ]

    if sample_path:
        tools.append(("get_file_skeleton", lambda: service.file_skeleton(repo_id, path=sample_path)))
    if sample_symbol_id:
        tools.append(("get_symbol_context", lambda: service.symbol_context(repo_id, symbol_id=sample_symbol_id, max_tokens=2048)))
        tools.append(("get_impact_slice", lambda: service.impact_slice(repo_id, symbol_id=sample_symbol_id, depth=2, max_nodes=50)))
    if sample_module:
        tools.append(("get_module_dependents", lambda: service.module_dependents(repo_id, module_path=sample_module)))

    tools.append(("inspect_symbol", lambda: workflow.inspect_symbol(repo_id, query=sample_name)))

    # Setup monkeypatch counters
    sha256_file_calls = 0
    sha256_bytes_calls = 0

    orig_sha256_file = hashing_mod.sha256_file
    orig_sha256_bytes = hashing_mod.sha256_bytes

    def counting_sha256_file(path: Path) -> str:
        nonlocal sha256_file_calls
        sha256_file_calls += 1
        return orig_sha256_file(path)

    def counting_sha256_bytes(raw: bytes) -> str:
        nonlocal sha256_bytes_calls
        sha256_bytes_calls += 1
        return orig_sha256_bytes(raw)

    hashing_mod.sha256_file = counting_sha256_file
    hashing_mod.sha256_bytes = counting_sha256_bytes
    service_mod.sha256_file = counting_sha256_file

    results: list[dict[str, Any]] = []

    try:
        for tool_name, tool_fn in tools:
            # Warm up 1 run
            try:
                tool_fn()
            except Exception:
                pass

            durations_ms: list[float] = []
            sha256_file_calls = 0
            sha256_bytes_calls = 0

            for _ in range(iterations):
                t0 = time.perf_counter()
                try:
                    tool_fn()
                except Exception as ex:
                    pass
                t1 = time.perf_counter()
                durations_ms.append((t1 - t0) * 1000.0)

            durations_sorted = sorted(durations_ms)
            p50 = percentile(durations_sorted, 50.0)
            p95 = percentile(durations_sorted, 95.0)
            max_latency = max(durations_sorted) if durations_sorted else 0.0

            file_hashes_per_call = round(sha256_file_calls / iterations, 2)
            byte_hashes_per_call = round(sha256_bytes_calls / iterations, 2)

            results.append({
                "tool": tool_name,
                "iterations": iterations,
                "p50_ms": round(p50, 2),
                "p95_ms": round(p95, 2),
                "max_ms": round(max_latency, 2),
                "sha256_file_per_call": file_hashes_per_call,
                "sha256_bytes_per_call": byte_hashes_per_call,
                "total_sha256_file_calls": sha256_file_calls,
                "total_sha256_bytes_calls": sha256_bytes_calls,
            })
    finally:
        # Restore original functions
        hashing_mod.sha256_file = orig_sha256_file
        hashing_mod.sha256_bytes = orig_sha256_bytes
        service_mod.sha256_file = orig_sha256_file

    return {
        "repo_id": repo_id,
        "iterations": iterations,
        "tools": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark retrieval tool latencies and hashing counts.")
    parser.add_argument("--repo-id", default="token-context", help="Repository ID to benchmark")
    parser.add_argument("--config", default=None, help="Path to repos.toml configuration")
    parser.add_argument("--iterations", type=int, default=20, help="Number of benchmark iterations (default 20)")
    parser.add_argument("--output", default=None, help="Path to save JSON benchmark output")

    args = parser.parse_args()
    cfg_p = Path(args.config).expanduser().resolve() if args.config else None

    report = run_benchmark(args.repo_id, config_path=cfg_p, iterations=args.iterations)

    print(f"=== Latency Benchmark for repo '{args.repo_id}' (n={args.iterations}) ===")
    print(f"{'Tool':<25} {'p50 (ms)':>10} {'p95 (ms)':>10} {'max (ms)':>10} {'sha256_file':>12} {'sha256_bytes':>12}")
    print("-" * 85)
    for t in report["tools"]:
        print(f"{t['tool']:<25} {t['p50_ms']:>10.2f} {t['p95_ms']:>10.2f} {t['max_ms']:>10.2f} {t['sha256_file_per_call']:>12.1f} {t['sha256_bytes_per_call']:>12.1f}")

    if args.output:
        out_p = Path(args.output).expanduser().resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with out_p.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"\nSaved benchmark results to {out_p}")


if __name__ == "__main__":
    main()

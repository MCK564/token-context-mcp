"""Benchmark retrieval tool latencies and hashing overhead (M5 protocol).

Protocol (Section 3):
- Records machine, OS, Python version, CPU core count in JSON.
- 5 warm-up iterations discarded, 20 measurement iterations per tool.
- Runs the full suite 3 consecutive times.
- Reports median p50, min-max range across the 3 rounds.
- Marks noisy: true if max_p50 / min_p50 > 1.5.
- Counts sha256_file, os_stat, etc. via monkeypatching.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import sqlite3
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

import token_context_mcp.index.hashing as hashing_mod
import token_context_mcp.retrieve.service as service_mod
from token_context_mcp.config import default_config_path, index_directory, load_config
from token_context_mcp.index.runner import database_path
from token_context_mcp.index.sqlite_store import SQLiteStore
from token_context_mcp.retrieve.service import RetrievalService
from token_context_mcp.retrieve.workflows import CompositeWorkflowEngine


def percentile(data: list[float], pct: float) -> float:
    """Calculate percentile from a list of numbers."""
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


def run_single_benchmark_round(
    repo_id: str,
    config_path: Path | None = None,
    warmup_runs: int = 5,
    iterations: int = 20,
) -> dict[str, Any]:
    cfg_p = config_path or default_config_path()
    config = load_config(cfg_p)
    service = RetrievalService(config, cfg_p)
    workflow = CompositeWorkflowEngine(service)

    idx_dir = index_directory(cfg_p)
    db = database_path(idx_dir, repo_id)
    sample_symbol_id = ""
    sample_path = ""
    sample_name = "test"
    if db.exists():
        store = SQLiteStore(db)
        all_syms = store.symbols()
        code_syms = [s for s in all_syms if not s.path.startswith(("tests/", "evals/"))]
        target_sym = code_syms[0] if code_syms else all_syms[0]
        sample_symbol_id = target_sym.symbol_id
        sample_path = target_sym.path
        sample_name = target_sym.name
    sample_module = sample_path.replace("\\", "/").rsplit(".", 1)[0] if sample_path else None

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

    sha256_calls = 0
    sha256_total_bytes = 0
    os_stat_calls = 0
    sqlite3_connect_calls = 0
    sha256_file_calls = 0
    sha256_bytes_calls = 0

    orig_sha256 = hashlib.sha256
    orig_os_stat = os.stat
    orig_sqlite3_connect = sqlite3.connect
    orig_sha256_file = hashing_mod.sha256_file
    orig_sha256_bytes = hashing_mod.sha256_bytes

    def counting_sha256(data: bytes = b"") -> Any:
        nonlocal sha256_calls, sha256_total_bytes
        sha256_calls += 1
        sha256_total_bytes += len(data)
        return orig_sha256(data)

    def counting_os_stat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        nonlocal os_stat_calls
        os_stat_calls += 1
        return orig_os_stat(path, *args, **kwargs)

    def counting_sqlite3_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        nonlocal sqlite3_connect_calls
        sqlite3_connect_calls += 1
        return orig_sqlite3_connect(*args, **kwargs)

    def counting_sha256_file(path: Path) -> str:
        nonlocal sha256_file_calls
        sha256_file_calls += 1
        return orig_sha256_file(path)

    def counting_sha256_bytes(raw: bytes) -> str:
        nonlocal sha256_bytes_calls
        sha256_bytes_calls += 1
        return orig_sha256_bytes(raw)

    hashlib.sha256 = counting_sha256
    os.stat = counting_os_stat
    sqlite3.connect = counting_sqlite3_connect
    hashing_mod.sha256_file = counting_sha256_file
    hashing_mod.sha256_bytes = counting_sha256_bytes
    service_mod.sha256_file = counting_sha256_file

    results: list[dict[str, Any]] = []

    try:
        for tool_name, tool_fn in tools:
            # 5 Warm-up runs (discarded)
            for _ in range(warmup_runs):
                try:
                    tool_fn()
                except Exception:
                    pass

            durations_ms: list[float] = []
            sha256_calls = 0
            sha256_total_bytes = 0
            os_stat_calls = 0
            sqlite3_connect_calls = 0
            sha256_file_calls = 0
            sha256_bytes_calls = 0

            # 20 measurement runs
            for _ in range(iterations):
                t0 = time.perf_counter()
                try:
                    tool_fn()
                except Exception:
                    pass
                t1 = time.perf_counter()
                durations_ms.append((t1 - t0) * 1000.0)

            durations_sorted = sorted(durations_ms)
            p50 = percentile(durations_sorted, 50.0)
            p95 = percentile(durations_sorted, 95.0)
            max_lat = max(durations_sorted) if durations_sorted else 0.0

            results.append({
                "tool": tool_name,
                "iterations": iterations,
                "warmup_runs": warmup_runs,
                "p50_ms": round(p50, 2),
                "p95_ms": round(p95, 2),
                "max_ms": round(max_lat, 2),
                "sha256_file_per_call": round(sha256_file_calls / iterations, 2),
                "total_sha256_file_calls": sha256_file_calls,
                "os_stat_per_call": round(os_stat_calls / iterations, 2),
                "sqlite3_connect_per_call": round(sqlite3_connect_calls / iterations, 2),
            })
    finally:
        hashlib.sha256 = orig_sha256
        os.stat = orig_os_stat
        sqlite3.connect = orig_sqlite3_connect
        hashing_mod.sha256_file = orig_sha256_file
        hashing_mod.sha256_bytes = orig_sha256_bytes
        service_mod.sha256_file = orig_sha256_file

    return {
        "repo_id": repo_id,
        "iterations": iterations,
        "warmup_runs": warmup_runs,
        "tools": results,
    }


def run_benchmark_protocol(
    repo_id: str,
    config_path: Path | None = None,
    rounds_count: int = 3,
    warmup_runs: int = 5,
    iterations: int = 20,
) -> dict[str, Any]:
    """Execute the full benchmark 3 times and aggregate medians and noisy flags."""
    rounds_data: list[dict[str, Any]] = []

    for round_idx in range(1, rounds_count + 1):
        r = run_single_benchmark_round(
            repo_id,
            config_path=config_path,
            warmup_runs=warmup_runs,
            iterations=iterations,
        )
        r["round"] = round_idx
        rounds_data.append(r)

    # Tool map across rounds
    tool_names = [t["tool"] for t in rounds_data[0]["tools"]]
    aggregated_tools: list[dict[str, Any]] = []

    for tool in tool_names:
        p50_vals = [next(t["p50_ms"] for t in r["tools"] if t["tool"] == tool) for r in rounds_data]
        p95_vals = [next(t["p95_ms"] for t in r["tools"] if t["tool"] == tool) for r in rounds_data]
        max_vals = [next(t["max_ms"] for t in r["tools"] if t["tool"] == tool) for r in rounds_data]
        sha256_vals = [next(t["sha256_file_per_call"] for t in r["tools"] if t["tool"] == tool) for r in rounds_data]

        med_p50 = statistics.median(p50_vals)
        min_p50 = min(p50_vals)
        max_p50 = max(p50_vals)
        is_noisy = (max_p50 / min_p50 > 1.5) if min_p50 > 0 else False

        aggregated_tools.append({
            "tool": tool,
            "median_p50_ms": round(med_p50, 2),
            "p50_runs": [round(x, 2) for x in p50_vals],
            "min_p50_ms": round(min_p50, 2),
            "max_p50_ms": round(max_p50, 2),
            "noisy": is_noisy,
            "median_p95_ms": round(statistics.median(p95_vals), 2),
            "median_max_ms": round(statistics.median(max_vals), 2),
            "sha256_file_per_call": round(statistics.mean(sha256_vals), 2),
        })

    return {
        "repo_id": repo_id,
        "protocol": "Section 3 Protocol (5 warmup, 20 measure, 3 runs)",
        "environment": {
            "platform": platform.platform(),
            "python_version": sys.version,
            "cpu_count": os.cpu_count(),
        },
        "rounds_count": rounds_count,
        "iterations_per_round": iterations,
        "warmup_per_round": warmup_runs,
        "summary": aggregated_tools,
        "rounds": rounds_data,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark retrieval tool latencies (Section 3 Protocol).")
    parser.add_argument("--repo-id", default="token-context", help="Repository ID to benchmark")
    parser.add_argument("--config", default=None, help="Path to repos.toml configuration")
    parser.add_argument("--iterations", type=int, default=20, help="Number of benchmark iterations (default 20)")
    parser.add_argument("--warmup", type=int, default=5, help="Number of warmup iterations (default 5)")
    parser.add_argument("--runs", type=int, default=3, help="Number of consecutive protocol rounds (default 3)")
    parser.add_argument("--output", default=None, help="Path to save JSON benchmark output")

    args = parser.parse_args()
    cfg_p = Path(args.config).expanduser().resolve() if args.config else None

    report = run_benchmark_protocol(
        args.repo_id,
        config_path=cfg_p,
        rounds_count=args.runs,
        warmup_runs=args.warmup,
        iterations=args.iterations,
    )

    print(f"==========================================================================================")
    print(f"LATENCY BENCHMARK (Section 3 Protocol): repo='{args.repo_id}'  runs={args.runs}  iters={args.iterations}")
    print(f"Environment: {report['environment']['platform']} | Python {report['environment']['python_version'].split()[0]}")
    print(f"==========================================================================================")
    print(f"{'Tool':<25} | {'Med p50':>8} | {'p50 Runs':<20} | {'Noisy':<6} | {'Med p95':>8} | {'sha256_file':>11}")
    print(f"------------------------------------------------------------------------------------------")
    for t in report["summary"]:
        runs_str = str(t['p50_runs'])
        noisy_str = "YES" if t['noisy'] else "no"
        print(f"{t['tool']:<25} | {t['median_p50_ms']:>8.2f} | {runs_str:<20} | {noisy_str:<6} | {t['median_p95_ms']:>8.2f} | {t['sha256_file_per_call']:>11.1f}")
    print(f"==========================================================================================")

    if args.output:
        out_p = Path(args.output).expanduser().resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Saved benchmark results to {out_p}")


if __name__ == "__main__":
    main()

"""Deterministic context-cost measurement (comparisons C1 and C2).

C1 answers "does the tool reduce context?" by comparing the tokens needed to
read a repository's source against the tokens actually emitted by the retrieval
tools. C2 answers "did a change help?" by running the same script across two
versions and diffing the JSON.

No provider is contacted and no token is billed. Local byte estimates are not a
billing claim; see docs/BENCHMARK.md before quoting these numbers as cost.

Usage:
    python evals/measure_context_cost.py --repo-id bench-invoice
    python evals/measure_context_cost.py --repo-id bench-invoice --output evals/reports/c1-invoice.json
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from token_context_mcp.config import default_config_path, index_directory, load_config
from token_context_mcp.index.runner import database_path
from token_context_mcp.index.sqlite_store import SQLiteStore
from token_context_mcp.retrieve.service import RetrievalError, RetrievalService
from token_context_mcp.retrieve.token_budget import estimate_tokens

SOURCE_SUFFIXES = (".py", ".js", ".jsx", ".ts", ".tsx")


def payload_tokens(response: dict[str, Any]) -> int:
    """Tokens the caller actually receives, not the value the envelope declares."""
    return estimate_tokens(json.dumps(response))


def declared_tokens(response: dict[str, Any]) -> int:
    return int(response.get("budget", {}).get("estimated_tokens", 0))


def baseline_tokens(root: Path) -> dict[str, Any]:
    """Naive arm: read every parseable source file in the repository."""
    files = [
        path
        for path in root.rglob("*")
        if path.suffix.lower() in SOURCE_SUFFIXES
        and ".venv" not in path.parts
        and "__pycache__" not in path.parts
        and path.is_file()
    ]
    total_bytes = sum(path.stat().st_size for path in files)
    return {
        "file_count": len(files),
        "bytes": total_bytes,
        "tokens": math.ceil(total_bytes / 4),
    }


def edge_precision(config_path: Path, repo_id: str) -> dict[str, Any]:
    store = SQLiteStore(database_path(index_directory(config_path), repo_id), read_only=True)
    symbols = store.symbols()
    edges = [edge for symbol in symbols for edge in store.edges_from(symbol.symbol_id)]
    ambiguous = sum(1 for edge in edges if edge.status == "ambiguous")
    return {
        "symbols": len(symbols),
        "edges": len(edges),
        "ambiguous_edges": ambiguous,
        "ambiguous_rate": round(ambiguous / len(edges), 4) if edges else None,
    }


def measure(repo_id: str, config_path: Path) -> dict[str, Any]:
    config = load_config(config_path)
    service = RetrievalService(config, config_path)
    root = config.repositories[repo_id].root
    base = baseline_tokens(root)
    calls: list[dict[str, Any]] = []

    def record(label: str, response: dict[str, Any], *, expect_bound: int | None) -> None:
        actual = payload_tokens(response)
        declared = declared_tokens(response)
        calls.append(
            {
                "call": label,
                "declared_tokens": declared,
                "payload_tokens": actual,
                "accounting_gap": round(actual / declared, 2) if declared else None,
                "over_server_cap": actual > config.server.max_result_tokens,
                "exceeds_expected_bound": (actual > expect_bound) if expect_bound else None,
                "truncated": response.get("truncated"),
                "saving_vs_baseline": round(base["tokens"] / actual, 1) if actual else None,
            }
        )

    for budget in (512, 1024, 2048):
        if budget > config.server.max_result_tokens:
            continue
        record(f"repo_map@{budget}", service.repo_map(repo_id, budget_tokens=budget), expect_bound=budget)

    found = service.find_symbols(repo_id, pattern="_", limit=5)
    record("find_symbols(limit=5)", found, expect_bound=None)

    symbols = found.get("data", {}).get("symbols", [])
    if symbols:
        symbol_id = symbols[0]["symbol_id"]
        path = symbols[0]["path"]
        try:
            record(
                "file_skeleton@1024",
                service.file_skeleton(repo_id, path=path, max_tokens=1024),
                expect_bound=1024,
            )
        except RetrievalError:
            pass
        for budget in (1024, 2048):
            if budget > config.server.max_result_tokens:
                continue
            record(
                f"symbol_context@{budget}",
                service.symbol_context(repo_id, symbol_id=symbol_id, depth=1, max_tokens=budget),
                expect_bound=budget,
            )
        record(
            "impact_slice(depth=2,max_nodes=75)",
            service.impact_slice(repo_id, symbol_id=symbol_id, depth=2, max_nodes=75),
            expect_bound=config.server.max_result_tokens,
        )

    worst_gap = max((item["accounting_gap"] or 0) for item in calls) if calls else 0
    return {
        "repo_id": repo_id,
        "estimator_version": "utf8-bytes-div-4-v1",
        "server_max_result_tokens": config.server.max_result_tokens,
        "baseline": base,
        "index": edge_precision(config_path, repo_id),
        "calls": calls,
        "summary": {
            "worst_accounting_gap": worst_gap,
            "calls_over_server_cap": sum(1 for item in calls if item["over_server_cap"]),
            "budget_contract_holds": worst_gap <= 1.15,
        },
        "note": "payload_tokens is a local byte estimate, not a provider billing figure",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure context cost for a registered repository")
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = measure(args.repo_id, args.config)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")

    base = report["baseline"]
    index = report["index"]
    print(f"repo: {report['repo_id']}")
    print(f"  baseline   : {base['file_count']} files, {base['bytes']:,} bytes ~ {base['tokens']:,} tokens")
    ambiguous = f"{index['ambiguous_rate']:.1%}" if index["ambiguous_rate"] is not None else "n/a"
    print(f"  index      : {index['symbols']} symbols, {index['edges']} edges, {ambiguous} ambiguous")
    print(f"  {'call':36s} {'declared':>9s} {'payload':>9s} {'gap':>6s} {'saving':>8s}")
    for item in report["calls"]:
        gap = f"{item['accounting_gap']:.1f}x" if item["accounting_gap"] else "-"
        saving = f"{item['saving_vs_baseline']:.1f}x" if item["saving_vs_baseline"] else "-"
        flag = "  OVER-CAP" if item["over_server_cap"] else ""
        print(f"  {item['call']:36s} {item['declared_tokens']:>9,} {item['payload_tokens']:>9,} "
              f"{gap:>6s} {saving:>8s}{flag}")
    summary = report["summary"]
    print(f"\n  worst accounting gap : {summary['worst_accounting_gap']}x "
          f"({'PASS' if summary['budget_contract_holds'] else 'FAIL: declared budget does not bound payload'})")
    print(f"  calls over server cap: {summary['calls_over_server_cap']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Deterministic context-cost measurement (comparisons C1 and C2).

C1 answers "does the tool reduce context?" by comparing the tokens needed to
read a repository's source against the tokens actually emitted by the retrieval
tools. C2 answers "did a change help?" by running the same script across two
versions and diffing the JSON.

Every figure is measured at the MCP wire, not at the RetrievalService return
value: it wraps each response through the same `server._result()` helper the
running server uses, then serialises the resulting `CallToolResult` the way
the MCP SDK does before it reaches an agent. An earlier version of this script
measured the service dict directly, which under-reported the real payload by
the size of the `structured_content` duplicate that server.py used to also
place in `content` (see docs/REMEDIATION_AND_BENCHMARK_PLAN.en.md, W1/W1b) —
`calls_over_server_cap` passed at the service layer while the wire response
exceeded the cap. Measuring the wire is what would have caught that.

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
import time
from pathlib import Path
from typing import Any

from token_context_mcp.config import default_config_path, index_directory, load_config
from token_context_mcp.index.runner import database_path
from token_context_mcp.index.sqlite_store import SQLiteStore
from token_context_mcp.retrieve.service import RetrievalError, RetrievalService
from token_context_mcp.retrieve.token_budget import estimate_tokens
from token_context_mcp.server import _result

SOURCE_SUFFIXES = (".py", ".js", ".jsx", ".ts", ".tsx")


def wire_tokens(response: dict[str, Any]) -> int:
    """Tokens for the bytes an MCP client actually receives for this call.

    Wraps the service response through the server's own result envelope
    (`content` summary + `structured_content` payload) and serialises it the
    way the MCP SDK does on the wire. This is the number that bounds what an
    agent is billed for one tool call, not `budget.estimated_tokens` and not
    the size of the bare service dict.
    """
    wrapped = _result(response)
    wire = wrapped.model_dump(mode="json", by_alias=True)
    return estimate_tokens(json.dumps(wire))


def service_payload_tokens(response: dict[str, Any]) -> int:
    """Tokens for the RetrievalService return value alone, no MCP envelope.

    Kept for comparison with the pre-W1b harness; do not use this to judge
    whether a response fits the server's token cap — use wire_tokens.
    """
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
    resolved = sum(1 for edge in edges if edge.status == "resolved")
    return {
        "symbols": len(symbols),
        "edges": len(edges),
        "ambiguous_edges": ambiguous,
        "ambiguous_rate": round(ambiguous / len(edges), 4) if edges else None,
        "resolved_rate": round(resolved / len(edges), 4) if edges else None,
        "basis": "edge_status / observed_edges" if edges else "no_edges_observed",
    }


def measure(repo_id: str, config_path: Path) -> dict[str, Any]:
    config = load_config(config_path)
    service = RetrievalService(config, config_path)
    root = config.repositories[repo_id].root
    base = baseline_tokens(root)
    calls: list[dict[str, Any]] = []

    def record(
        label: str,
        response: dict[str, Any],
        *,
        expect_bound: int | None,
        elapsed_seconds: float | None = None,
        sqlite_execute_count: int | None = None,
    ) -> None:
        wire = wire_tokens(response)
        service_only = service_payload_tokens(response)
        declared = declared_tokens(response)
        call: dict[str, Any] = {
            "call": label,
            "declared_tokens": declared,
            "service_payload_tokens": service_only,
            "wire_tokens": wire,
            "accounting_gap": round(wire / declared, 2) if declared else None,
            "envelope_overhead": round(wire / service_only, 2) if service_only else None,
            "over_server_cap": wire > config.server.max_result_tokens,
            "exceeds_expected_bound": (wire > expect_bound) if expect_bound else None,
            "truncated": response.get("truncated"),
            "saving_vs_baseline": round(base["tokens"] / wire, 1) if wire else None,
        }
        if elapsed_seconds is not None:
            call["elapsed_seconds"] = round(elapsed_seconds, 4)
        if sqlite_execute_count is not None:
            call["sqlite_execute_count"] = sqlite_execute_count
        entries = response.get("data", {}).get("symbols", [])
        if isinstance(entries, list) and entries:
            entry_costs = [estimate_tokens(json.dumps(entry, ensure_ascii=False)) for entry in entries]
            call.update(
                {
                    "returned_symbols": len(entries),
                    "mean_entry_tokens": round(sum(entry_costs) / len(entry_costs), 2),
                    "max_entry_tokens": max(entry_costs),
                    "service_tokens_per_symbol": round(service_only / len(entries), 2),
                    "wire_tokens_per_symbol": round(wire / len(entries), 2),
                }
            )
        calls.append(call)

    for budget in (512, 1024, 2048):
        if budget > config.server.max_result_tokens:
            continue
        started = time.perf_counter()
        response = service.repo_map(repo_id, budget_tokens=budget)
        record(
            f"repo_map@{budget}",
            response,
            expect_bound=budget,
            elapsed_seconds=time.perf_counter() - started,
            sqlite_execute_count=service.last_query_count,
        )

    source_budget = min(4096, config.server.max_result_tokens)
    source_search = service.search_source(repo_id, query="ocr", limit=100, max_tokens=source_budget)
    record(f"search_source(ocr)@{source_budget}", source_search, expect_bound=source_budget)

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
    repo_map_calls = [item for item in calls if item["call"].startswith("repo_map@")]
    expected_bound_checks = [
        item["exceeds_expected_bound"]
        for item in calls
        if item["exceeds_expected_bound"] is not None
    ]
    return {
        "repo_id": repo_id,
        "estimator_version": "utf8-bytes-div-4-v1",
        "measurement_layer": "mcp_wire (CallToolResult, content summary + structured_content)",
        "server_max_result_tokens": config.server.max_result_tokens,
        "baseline": base,
        "index": edge_precision(config_path, repo_id),
        "calls": calls,
        "summary": {
            "worst_accounting_gap": worst_gap,
            "calls_over_server_cap": sum(1 for item in calls if item["over_server_cap"]),
            # The declared estimate is intentionally smaller than the full
            # wire envelope after X1 reserves framing room. The contract gate
            # is therefore the requested-budget bound, not wire/estimate
            # overhead (which remains a useful diagnostic in worst_gap).
            "budget_contract_holds": all(not exceeded for exceeded in expected_bound_checks),
            "repo_map_1024_under_one_second": any(
                item["call"] == "repo_map@1024" and item.get("elapsed_seconds", float("inf")) < 1
                for item in repo_map_calls
            ),
            "repo_map_max_sqlite_execute_count": max(
                (item.get("sqlite_execute_count", 0) for item in repo_map_calls), default=0
            ),
            "search_source_ocr_files": len(
                {
                    item["path"]
                    for item in source_search.get("data", {}).get("matches", [])
                    if isinstance(item, dict) and isinstance(item.get("path"), str)
                }
            ),
        },
        "note": "wire_tokens is a local byte estimate of the MCP response, not a provider billing figure",
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
    print(f"  {'call':36s} {'declared':>9s} {'service':>9s} {'wire':>9s} {'gap':>6s} {'saving':>8s}")
    for item in report["calls"]:
        gap = f"{item['accounting_gap']:.1f}x" if item["accounting_gap"] else "-"
        saving = f"{item['saving_vs_baseline']:.1f}x" if item["saving_vs_baseline"] else "-"
        flag = "  OVER-CAP" if item["over_server_cap"] else ""
        print(f"  {item['call']:36s} {item['declared_tokens']:>9,} {item['service_payload_tokens']:>9,} "
              f"{item['wire_tokens']:>9,} {gap:>6s} {saving:>8s}{flag}")
    summary = report["summary"]
    print(f"\n  worst accounting gap (wire) : {summary['worst_accounting_gap']}x "
          f"({'PASS' if summary['budget_contract_holds'] else 'FAIL: declared budget does not bound the wire payload'})")
    print(f"  calls over server cap (wire): {summary['calls_over_server_cap']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

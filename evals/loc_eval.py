"""Evaluation harness for localization tasks (M5 LARGER-lite).

Evaluates search_source retrieval quality on code localization tasks.
Measures:
- File Acc@5: percentage of tasks with at least 1 gold file in top 5 files.
- File Recall@5: fraction of gold files found in top 5 files.
- Symbol Recall@10: fraction of gold symbols found in top 10 returned symbols.
- Wire Tokens: estimated response tokens using utf8-bytes-div-4-v1.
- Latency: p50 and p95 latency over repeated iterations (5 runs, discard first).
"""
from __future__ import annotations

import argparse
import inspect
import json
import math
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from token_context_mcp.config import default_config_path, load_config
from token_context_mcp.retrieve.service import RetrievalService


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


def estimate_wire_tokens(payload: Any) -> int:
    """Estimate payload tokens via utf8-bytes-div-4-v1."""
    if not isinstance(payload, str):
        payload_str = json.dumps(payload, ensure_ascii=False)
    else:
        payload_str = payload
    return max(1, math.ceil(len(payload_str.encode("utf-8")) / 4))


def _neighbor_path_and_name(n: Any) -> tuple[str | None, str | None, str | None, str | None]:
    """Return (symbol_id, path, name, anchor_id) for a neighbor row or dict."""
    if isinstance(n, (list, tuple)) and len(n) >= 2:
        sym_id = str(n[0]) if n else None
        loc = str(n[1])
        path = loc.rsplit(":", 1)[0] if ":" in loc else loc
        name = str(n[2]).split(" ", 1)[-1].strip() if len(n) >= 3 else None
        anchor = str(n[5]) if len(n) >= 6 else None
        return sym_id, path.replace("\\", "/"), name, anchor
    if isinstance(n, dict):
        path = n.get("path")
        return (
            n.get("symbol_id"),
            str(path).replace("\\", "/") if path else None,
            n.get("qualified_name") or n.get("name"),
            n.get("anchor_id"),
        )
    return None, None, None, None


def _interleaved(response_data: dict[str, Any]) -> list[tuple[str, Any]]:
    """Merged ranking: each match, immediately followed by the neighbors expanded from it.

    Neighbors whose anchor is not among the matches go last, in their given order.
    """
    matches = response_data.get("matches", [])
    neighbors = response_data.get("neighbors", []) or []
    by_anchor: dict[str, list[Any]] = {}
    orphans: list[Any] = []
    match_ids = {m.get("symbol_id") for m in matches}
    for n in neighbors:
        anchor = _neighbor_path_and_name(n)[3]
        if anchor and anchor in match_ids:
            by_anchor.setdefault(anchor, []).append(n)
        else:
            orphans.append(n)
    merged: list[tuple[str, Any]] = []
    for m in matches:
        merged.append(("match", m))
        for n in by_anchor.pop(m.get("symbol_id"), []):
            merged.append(("neighbor", n))
    merged.extend(("neighbor", n) for n in orphans)
    return merged


def extract_ranked_files(response_data: dict[str, Any]) -> list[str]:
    """Distinct files in merged order (match, then its neighbors)."""
    files: list[str] = []
    seen: set[str] = set()
    for kind, item in _interleaved(response_data):
        if kind == "match":
            p = item.get("path")
            p = str(p).replace("\\", "/") if p else None
        else:
            p = _neighbor_path_and_name(item)[1]
        if p and p not in seen:
            seen.add(p)
            files.append(p)
    return files


def extract_ranked_symbols(
    response_data: dict[str, Any],
    symbol_id_map: dict[str, tuple[str, str]],
) -> list[tuple[str, str]]:
    """Distinct (path, qualified_name) pairs in merged order (match, then its neighbors)."""
    symbols: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for kind, item in _interleaved(response_data):
        pair: tuple[str, str] | None = None
        if kind == "match":
            sym_id = item.get("symbol_id")
            if sym_id and sym_id in symbol_id_map:
                raw_p, raw_name = symbol_id_map[sym_id]
                pair = (raw_p.replace("\\", "/"), raw_name)
            elif item.get("path") and (item.get("qualified_name") or item.get("name")):
                pair = (str(item["path"]).replace("\\", "/"), item.get("qualified_name") or item["name"])
        else:
            sym_id, path, name, _ = _neighbor_path_and_name(item)
            if sym_id and sym_id in symbol_id_map:
                raw_p, raw_name = symbol_id_map[sym_id]
                pair = (raw_p.replace("\\", "/"), raw_name)
            elif path and name:
                pair = (path, name)
        if pair and pair not in seen:
            seen.add(pair)
            symbols.append(pair)
    return symbols


def evaluate_single_task(
    task: dict[str, Any],
    response: dict[str, Any],
    symbol_id_map: dict[str, tuple[str, str]],
    latencies_ms: list[float],
) -> dict[str, Any]:
    """Calculate all 4 metrics for a single task."""
    data = response.get("data", {})
    ranked_files = extract_ranked_files(data)
    ranked_symbols = extract_ranked_symbols(data, symbol_id_map)

    gold_files = task.get("gold_files", [])
    gold_symbols_spec = task.get("gold_symbols", [])
    gold_symbol_pairs = {(s["path"], s["qualified_name"]) for s in gold_symbols_spec}

    top_5_files = ranked_files[:5]
    top_10_symbols = ranked_symbols[:10]

    # File Acc@5: at least 1 gold file in top 5
    found_gold_files_5 = [f for f in gold_files if f in top_5_files]
    file_acc_5 = 1.0 if len(found_gold_files_5) > 0 else 0.0

    # File Recall@5: fraction of gold files in top 5
    file_recall_5 = (
        len(set(gold_files) & set(top_5_files)) / len(gold_files) if gold_files else 0.0
    )

    # First gold file rank
    first_file_rank: int | None = None
    for idx, f in enumerate(ranked_files, start=1):
        if f in gold_files:
            first_file_rank = idx
            break

    # Symbol recall over everything the agent receives (matches + neighbors, budget-bound)
    sym_recall_resp = (
        len(set(ranked_symbols) & gold_symbol_pairs) / len(gold_symbol_pairs) if gold_symbol_pairs else 0.0
    )
    neighbor_count = len(data.get("neighbors", []) or [])

    # Symbol Recall@10
    found_symbols_10 = set(top_10_symbols) & gold_symbol_pairs
    sym_recall_10 = (
        len(found_symbols_10) / len(gold_symbol_pairs) if gold_symbol_pairs else 0.0
    )

    # First gold symbol rank
    first_sym_rank: int | None = None
    for idx, sym in enumerate(ranked_symbols, start=1):
        if sym in gold_symbol_pairs:
            first_sym_rank = idx
            break

    file_mrr = 1.0 / first_file_rank if first_file_rank else 0.0
    sym_mrr = 1.0 / first_sym_rank if first_sym_rank else 0.0
    sym_acc_1 = 1.0 if first_sym_rank == 1 else 0.0
    sym_acc_3 = 1.0 if first_sym_rank and first_sym_rank <= 3 else 0.0
    test_ratio_top_10 = (
        sum(1 for p, _ in top_10_symbols if p.startswith(("tests/", "evals/"))) / max(1, len(top_10_symbols))
    )

    gold_sym_terms_matched: list[str] = []
    if gold_symbols_spec:
        query_words = [w.lower() for w in task["query"].split() if w.strip()]
        for gs in gold_symbols_spec:
            s_name = gs.get("name", "").lower()
            s_qname = gs.get("qualified_name", "").lower()
            for w in query_words:
                if w in s_name or w in s_qname:
                    if w not in gold_sym_terms_matched:
                        gold_sym_terms_matched.append(w)

    wire_tokens = estimate_wire_tokens(response)
    p50_latency = percentile(latencies_ms, 50.0) if latencies_ms else 0.0

    return {
        "id": task["id"],
        "group": task.get("group", ""),
        "split": task.get("split", ""),
        "query": task["query"],
        "hit": file_acc_5 > 0,
        "first_gold_file_rank": first_file_rank,
        "first_gold_sym_rank": first_sym_rank,
        "file_acc_at_5": file_acc_5,
        "file_recall_at_5": file_recall_5,
        "file_mrr": round(file_mrr, 4),
        "sym_recall_at_10": sym_recall_10,
        "sym_recall_in_response": sym_recall_resp,
        "neighbor_count": neighbor_count,
        "sym_mrr": round(sym_mrr, 4),
        "sym_acc_at_1": sym_acc_1,
        "sym_acc_at_3": sym_acc_3,
        "test_ratio_top_10": round(test_ratio_top_10, 4),
        "gold_sym_terms_matched": gold_sym_terms_matched,
        "wire_tokens": wire_tokens,
        "latency_ms": round(p50_latency, 2),
        "latencies_ms": [round(t, 2) for t in latencies_ms],
        "top_5_files": top_5_files,
        "top_10_symbols": [f"{p}::{name}" for p, name in top_10_symbols],
    }


def compute_aggregate(tasks_results: list[dict[str, Any]]) -> dict[str, Any]:
    if not tasks_results:
        return {
            "task_count": 0,
            "file_acc_at_5": 0.0,
            "file_recall_at_5": 0.0,
            "file_mrr": 0.0,
            "sym_recall_at_10": 0.0,
            "sym_recall_in_response": 0.0,
            "mean_neighbor_count": 0.0,
            "sym_mrr": 0.0,
            "sym_acc_at_1": 0.0,
            "sym_acc_at_3": 0.0,
            "mean_test_ratio_top_10": 0.0,
            "mean_wire_tokens": 0.0,
            "latency_p50_ms": 0.0,
            "latency_p95_ms": 0.0,
        }

    n = len(tasks_results)
    file_acc = sum(t["file_acc_at_5"] for t in tasks_results) / n
    file_recall = sum(t["file_recall_at_5"] for t in tasks_results) / n
    file_mrr = sum(t["file_mrr"] for t in tasks_results) / n
    sym_recall = sum(t["sym_recall_at_10"] for t in tasks_results) / n
    sym_recall_resp = sum(t.get("sym_recall_in_response", 0.0) for t in tasks_results) / n
    mean_neighbors = sum(t.get("neighbor_count", 0) for t in tasks_results) / n
    sym_mrr = sum(t["sym_mrr"] for t in tasks_results) / n
    sym_acc_1 = sum(t["sym_acc_at_1"] for t in tasks_results) / n
    sym_acc_3 = sum(t["sym_acc_at_3"] for t in tasks_results) / n
    test_ratio = sum(t["test_ratio_top_10"] for t in tasks_results) / n
    mean_tokens = sum(t["wire_tokens"] for t in tasks_results) / n

    all_latencies: list[float] = []
    for t in tasks_results:
        all_latencies.extend(t.get("latencies_ms", []))

    lat_p50 = percentile(all_latencies, 50.0) if all_latencies else 0.0
    lat_p95 = percentile(all_latencies, 95.0) if all_latencies else 0.0

    return {
        "task_count": n,
        "file_acc_at_5": round(file_acc, 4),
        "file_recall_at_5": round(file_recall, 4),
        "file_mrr": round(file_mrr, 4),
        "sym_recall_at_10": round(sym_recall, 4),
        "sym_recall_in_response": round(sym_recall_resp, 4),
        "mean_neighbor_count": round(mean_neighbors, 2),
        "sym_mrr": round(sym_mrr, 4),
        "sym_acc_at_1": round(sym_acc_1, 4),
        "sym_acc_at_3": round(sym_acc_3, 4),
        "mean_test_ratio_top_10": round(test_ratio, 4),
        "mean_wire_tokens": round(mean_tokens, 1),
        "latency_p50_ms": round(lat_p50, 2),
        "latency_p95_ms": round(lat_p95, 2),
    }


def run_evaluation(
    tasks_file: Path,
    arm: str,
    split: str = "all",
    config_path: Path | None = None,
    output_path: Path | None = None,
    expand: str | None = None,
    expand_k: int | None = None,
    expand_hops: int | None = None,
    min_confidence: float | None = None,
    limit: int = 20,
    max_tokens: int | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    cfg_p = config_path or default_config_path()
    config = load_config(cfg_p)
    service = RetrievalService(config, cfg_p)

    raw_data = json.loads(tasks_file.read_text(encoding="utf-8"))
    repo_id = raw_data.get("repo_id", "token-context")
    reviewed = raw_data.get("reviewed", False)
    all_tasks = raw_data.get("tasks", [])

    if split != "all":
        tasks = [t for t in all_tasks if t.get("split") == split]
    else:
        tasks = all_tasks

    # Pre-build symbol_id -> (path, qualified_name) mapping from store
    repo, store, meta = service._repository_store(repo_id)
    all_symbols = store.symbols()
    symbol_id_map: dict[str, tuple[str, str]] = {
        s.symbol_id: (s.path, s.qualified_name or s.name) for s in all_symbols
    }

    # Inspect search_source signature for forward parameters
    sig = inspect.signature(service.search_source)
    supports_expand = "expand" in sig.parameters

    search_kwargs: dict[str, Any] = {
        "limit": limit,
    }
    if max_tokens is not None:
        search_kwargs["max_tokens"] = max_tokens
    if profile is not None:
        search_kwargs["profile"] = profile

    if supports_expand:
        if expand is not None:
            search_kwargs["expand"] = expand
        if expand_k is not None:
            search_kwargs["expand_k"] = expand_k
        if expand_hops is not None:
            search_kwargs["expand_hops"] = expand_hops
        if min_confidence is not None:
            search_kwargs["min_confidence"] = min_confidence

    task_results: list[dict[str, Any]] = []

    for task in tasks:
        if arm.upper() == "ORACLE":
            query = task["gold_symbols"][0]["qualified_name"]
        elif arm == "A0_vi":
            query = task.get("query_vi") or task["query"]
        else:
            query = task["query"]

        latencies_ms: list[float] = []
        last_response: dict[str, Any] = {}

        # 5 repetitions, discard first (warmup)
        for rep in range(5):
            t0 = time.perf_counter()
            resp = service.search_source(repo_id, query=query, **search_kwargs)
            t1 = time.perf_counter()
            if rep > 0:
                latencies_ms.append((t1 - t0) * 1000.0)
            last_response = resp

        task_res = evaluate_single_task(task, last_response, symbol_id_map, latencies_ms)
        task_res["eval_query"] = query
        task_results.append(task_res)

    # Compute aggregates overall and by group
    overall = compute_aggregate(task_results)

    groups = ["a_keyword", "b_hidden_dep", "c_multi_file"]
    by_group: dict[str, Any] = {}
    for g in groups:
        g_tasks = [t for t in task_results if t["group"] == g]
        by_group[g] = compute_aggregate(g_tasks)

    report = {
        "repo_id": repo_id,
        "arm": arm,
        "split": split,
        "reviewed": reviewed,
        "split_seed": raw_data.get("split_seed", 20260926),
        "search_parameters": {
            "limit": limit,
            "max_tokens": max_tokens or 2048,
            "profile": profile,
            "expand": expand,
            "expand_k": expand_k,
            "expand_hops": expand_hops,
            "min_confidence": min_confidence,
        },
        "task_count": len(task_results),
        "overall": overall,
        "by_group": by_group,
        "tasks": task_results,
    }

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate code localization tasks (M5)")
    parser.add_argument("--tasks", type=Path, default=Path("evals/tasks/loc_token_context.json"))
    parser.add_argument("--arm", type=str, required=True, help="Arm label (e.g. A0, A1, A2)")
    parser.add_argument("--split", choices=["dev", "heldout", "all"], default="all")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expand", type=str, help="expand mode for search_source (auto|none|graph)")
    parser.add_argument("--expand-k", type=int, help="max neighbors per anchor")
    parser.add_argument("--expand-hops", type=int, help="max BFS depth")
    parser.add_argument("--min-confidence", type=float, help="min edge confidence threshold")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--profile", type=str, default=None)

    args = parser.parse_args()

    default_out = Path(f"evals/out/m5/loc_{args.arm}_{args.split}.json")
    out_path = args.output or default_out

    report = run_evaluation(
        tasks_file=args.tasks,
        arm=args.arm,
        split=args.split,
        config_path=args.config,
        output_path=out_path,
        expand=args.expand,
        expand_k=args.expand_k,
        expand_hops=args.expand_hops,
        min_confidence=args.min_confidence,
        limit=args.limit,
        max_tokens=args.max_tokens,
        profile=args.profile,
    )

    print(f"==========================================================================================================")
    print(f"LOC EVAL: Arm={report['arm']}  Split={report['split']}  Tasks={report['task_count']}  Reviewed={report['reviewed']}")
    print(f"==========================================================================================================")
    print(f"{'Group':<14} | {'Tasks':<5} | {'Acc@5':<7} | {'FileMRR':<7} | {'SymRec@10':<9} | {'SymMRR':<7} | {'SymAcc@1':<8} | {'Tokens':<7} | {'p50(ms)':<7}")
    print(f"----------------------------------------------------------------------------------------------------------")
    for g, metrics in report["by_group"].items():
        print(f"{g:<14} | {metrics['task_count']:<5} | {metrics['file_acc_at_5']:<7.4f} | {metrics['file_mrr']:<7.4f} | {metrics['sym_recall_at_10']:<9.4f} | {metrics['sym_mrr']:<7.4f} | {metrics['sym_acc_at_1']:<8.4f} | {metrics['mean_wire_tokens']:<7.1f} | {metrics['latency_p50_ms']:<7.2f}")
    print(f"----------------------------------------------------------------------------------------------------------")
    ov = report["overall"]
    print(f"{'OVERALL':<14} | {ov['task_count']:<5} | {ov['file_acc_at_5']:<7.4f} | {ov['file_mrr']:<7.4f} | {ov['sym_recall_at_10']:<9.4f} | {ov['sym_mrr']:<7.4f} | {ov['sym_acc_at_1']:<8.4f} | {ov['mean_wire_tokens']:<7.1f} | {ov['latency_p50_ms']:<7.2f}")
    print(f"==========================================================================================================")
    print(f"Report saved to: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

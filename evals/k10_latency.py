"""K10: p50 latency of search_source / get_symbol_context for a FIXED query set, run once per code version.

``bench_latency.py`` picks its sample query from the first symbol of the index, so two code versions that index a
different symbol first are timed on different queries and are not comparable.  This script takes the queries
explicitly so the same inputs run on both versions::

    python evals/k10_latency.py --config cfg.toml --repo-id heldout-zod --queries zod3 '$ZodError' parse --output out.json
    python evals/k10_latency.py compare base.json new.json --output k10.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path


def measure(config: Path, repo_id: str, queries: list[str], iterations: int, warmup: int, rounds: int) -> dict:
    from token_context_mcp.config import load_config
    from token_context_mcp.retrieve.service import RetrievalService

    service = RetrievalService(load_config(config), config)
    out: dict[str, dict] = {}
    for q in queries:
        p50s: list[float] = []
        for _ in range(rounds):
            for _ in range(warmup):
                service.search_source(repo_id, query=q, limit=10)
            samples = []
            for _ in range(iterations):
                t = time.perf_counter()
                service.search_source(repo_id, query=q, limit=10)
                samples.append((time.perf_counter() - t) * 1000)
            p50s.append(statistics.median(samples))
        out[q] = {"p50_ms": round(statistics.median(p50s), 3), "p50_runs": [round(x, 3) for x in p50s]}
    return {"repo_id": repo_id, "queries": out}


def compare(base: dict, new: dict, tolerance: float = 0.20, floor_ms: float = 0.0) -> dict:
    rows = []
    ok = True
    for q, b in base["queries"].items():
        n = new["queries"].get(q)
        if n is None:
            continue
        ratio = n["p50_ms"] / b["p50_ms"] if b["p50_ms"] else None
        within = n["p50_ms"] <= b["p50_ms"] * (1 + tolerance) or (n["p50_ms"] - b["p50_ms"]) <= floor_ms
        ok &= within
        rows.append({"query": q, "base_p50_ms": b["p50_ms"], "new_p50_ms": n["p50_ms"], "ratio": round(ratio, 3) if ratio else None, "within": within})
    return {"repo_id": base["repo_id"], "rows": rows, "all_within_20pct": ok, "floor_ms": floor_ms}


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    ap.add_argument("--config", type=Path)
    ap.add_argument("--repo-id")
    ap.add_argument("--queries", nargs="+")
    ap.add_argument("--iterations", type=int, default=30)
    ap.add_argument("--warmup", type=int, default=5)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--output", type=Path)
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("base", type=Path, nargs="+")
    cmp_.add_argument("--new", type=Path, nargs="+", required=True)
    cmp_.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if args.cmd == "compare":
        reports = [compare(json.loads(b.read_text()), json.loads(n.read_text())) for b, n in zip(args.base, args.new)]
        merged = {"repos": reports, "all_within_20pct": all(r["all_within_20pct"] for r in reports)}
        args.output.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
        for r in reports:
            print(r["repo_id"], "OK" if r["all_within_20pct"] else "NOT within 20 %", [(x["query"], x["base_p50_ms"], x["new_p50_ms"]) for x in r["rows"]])
        return 0
    res = measure(args.config, args.repo_id, args.queries, args.iterations, args.warmup, args.rounds)
    args.output.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

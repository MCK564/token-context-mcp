"""Latency of search_source on the real localization task queries (M5 protocol, section 3).

Unlike bench_latency.py (one fixed query per tool), this replays every query of a task file,
for each expand mode, so the numbers reflect the AND -> OR top-up path and graph expansion.
Protocol: 1 warm-up pass over all queries is discarded, then `--passes` measured passes;
the whole round is repeated `--runs` times and the median of per-run p50/p95 is reported.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path

from token_context_mcp.config import default_config_path, load_config
from token_context_mcp.retrieve.service import RetrievalService


def _pct(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    idx = (len(ordered) - 1) * pct / 100.0
    lo, hi = int(idx), min(int(idx) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (idx - lo)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", default="token-context")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--tasks", type=Path, default=Path("evals/tasks/loc_token_context.json"))
    parser.add_argument("--modes", default="none,graph")
    parser.add_argument("--passes", type=int, default=5)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    queries = [t["query"] for t in json.loads(args.tasks.read_text(encoding="utf-8"))["tasks"]]
    service = RetrievalService(load_config(args.config), args.config)
    report: dict[str, object] = {
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "cpu_count": os.cpu_count(),
        },
        "repo_id": args.repo_id,
        "tasks_file": str(args.tasks),
        "query_count": len(queries),
        "protocol": {"warmup_passes": 1, "passes": args.passes, "runs": args.runs},
        "modes": {},
    }
    for mode in args.modes.split(","):
        runs = []
        for _ in range(args.runs):
            for q in queries:  # warm-up pass
                service.search_source(args.repo_id, query=q, expand=mode, max_tokens=args.max_tokens)
            samples: list[float] = []
            for _ in range(args.passes):
                for q in queries:
                    t0 = time.perf_counter()
                    service.search_source(args.repo_id, query=q, expand=mode, max_tokens=args.max_tokens)
                    samples.append((time.perf_counter() - t0) * 1000.0)
            runs.append({"p50": _pct(samples, 50), "p95": _pct(samples, 95), "max": max(samples)})
        p50s = [r["p50"] for r in runs]
        report["modes"][mode] = {  # type: ignore[index]
            "runs": [{k: round(v, 2) for k, v in r.items()} for r in runs],
            "median_p50_ms": round(statistics.median(p50s), 2),
            "median_p95_ms": round(statistics.median(r["p95"] for r in runs), 2),
            "noisy": max(p50s) / max(min(p50s), 1e-9) > 1.5,
        }
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

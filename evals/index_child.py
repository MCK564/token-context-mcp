"""Run one ``build_index`` in a fresh process and print a single JSON line (used by evals/index_bench.py).

Kept separate from the parent so that the parent can sample the RSS of the whole process tree
(this process plus any pool workers it spawns) while the index runs.
"""
from __future__ import annotations

import argparse
import inspect
import json
import sys
import time
import tracemalloc
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--tracemalloc", action="store_true")
    parser.add_argument("--verify-hashes", action="store_true")
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args()

    from token_context_mcp.config import get_repository, index_directory, load_config
    from token_context_mcp.index.runner import build_index

    config = load_config(args.config)
    repository = get_repository(config, args.repo_id)
    kwargs: dict[str, object] = {"network_policy": "declared-deny-not-enforced"}
    accepted = inspect.signature(build_index).parameters
    if args.verify_hashes and "verify_hashes" in accepted:
        kwargs["verify_hashes"] = True
    if args.workers is not None and "workers" in accepted:
        kwargs["workers"] = args.workers
    if args.tracemalloc:
        tracemalloc.start()
    started = time.perf_counter()
    manifest = build_index(repository, index_directory(args.config), **kwargs)
    wall = time.perf_counter() - started
    result: dict[str, object] = {
        "wall_s": round(wall, 3),
        "manifest": {
            key: manifest.get(key)
            for key in (
                "index_schema_version", "index_run_id", "files_seen", "files_indexed", "files_skipped",
                "files_reused", "files_reparsed", "symbols_indexed", "edges_indexed",
                "parse_source_calls", "timings_ms", "warnings", "write_mode", "edge_resolution", "files_stat_skipped",
                "incremental", "parse_mode",
            )
        },
    }
    if args.tracemalloc:
        result["tracemalloc_peak_mb"] = round(tracemalloc.get_traced_memory()[1] / 1e6, 1)
    print("RESULT " + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

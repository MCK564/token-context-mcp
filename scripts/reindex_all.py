#!/usr/bin/env python3
"""Reindex all registered repositories in the configuration sequentially."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from token_context_mcp.config import default_config_path, index_directory, load_config
from token_context_mcp.index.runner import build_index


def main() -> int:
    parser = argparse.ArgumentParser(description="Reindex all registered repositories.")
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config_path(),
        help="Path to configuration TOML file.",
    )
    args = parser.parse_args()

    config_path = args.config.resolve()
    if not config_path.is_file():
        print(f"Configuration file not found: {config_path}", file=sys.stderr)
        return 1

    config = load_config(config_path)
    idx_dir = index_directory(config_path)
    print(f"Loaded config: {config_path}")
    print(f"Index directory: {idx_dir}")
    print(f"Found {len(config.repositories)} repositories: {', '.join(config.repositories.keys())}\n")

    total_start = time.perf_counter()
    for repo_id, repo in config.repositories.items():
        print(f"--- Indexing repository: {repo_id} (root: {repo.root}) ---")
        t0 = time.perf_counter()
        manifest = build_index(
            repo,
            idx_dir,
            network_policy="declared-deny-not-enforced",
        )
        elapsed = time.perf_counter() - t0
        print(
            f"--> Finished {repo_id} in {elapsed:.3f}s "
            f"(run_id: {manifest.get('index_run_id')}, files: {manifest.get('files_indexed')}, "
            f"symbols: {manifest.get('symbols_indexed')}, edges: {manifest.get('edges_indexed')})\n"
        )

    total_elapsed = time.perf_counter() - total_start
    print(f"All repositories reindexed in {total_elapsed:.3f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

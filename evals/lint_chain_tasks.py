"""Linter for multi-turn chain task sets (L0)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from token_context_mcp.config import default_config_path, index_directory
from token_context_mcp.index.runner import database_path
from token_context_mcp.index.sqlite_store import SQLiteStore


def lint_chain_file(path: Path, config_path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    repo_id = data.get("repo_id")
    if not repo_id:
        return [f"{path.name}: missing repo_id"]

    db_path = database_path(index_directory(config_path), repo_id)
    if not db_path.exists():
        return [f"{path.name}: index DB not found for repo_id={repo_id} at {db_path}"]

    store = SQLiteStore(db_path, read_only=True)
    indexed_files = {f.path for f in store.files()}
    indexed_symbols = {(s.path, s.qualified_name) for s in store.symbols()}

    chains = data.get("chains", [])
    if len(chains) < 15:
        errors.append(f"{path.name}: expected >= 15 chains, got {len(chains)}")

    seen_ids: set[str] = set()
    for ch in chains:
        cid = ch.get("id", "")
        if not cid or cid in seen_ids:
            errors.append(f"{path.name}: duplicate or empty chain id '{cid}'")
        seen_ids.add(cid)
        for turn_key in ("q1", "q2", "q3"):
            turn = ch.get(turn_key)
            if not isinstance(turn, dict) or not turn.get("query"):
                errors.append(f"{path.name}: {cid}.{turn_key} missing query")
                continue
            for gf in turn.get("gold_files", []):
                if gf not in indexed_files:
                    errors.append(f"{path.name}: {cid}.{turn_key} unknown gold_file '{gf}'")
            g_syms = turn.get("gold_symbols", [])
            if not g_syms:
                errors.append(f"{path.name}: {cid}.{turn_key} has no gold_symbols")
            for gs in g_syms:
                key = (gs.get("path", ""), gs.get("qualified_name", ""))
                if key not in indexed_symbols:
                    errors.append(f"{path.name}: {cid}.{turn_key} unknown gold_symbol {key}")

    collisions = data.get("collisions", [])
    if len(collisions) < 8:
        errors.append(f"{path.name}: expected >= 8 collisions, got {len(collisions)}")
    for col in collisions:
        for role in ("q1_answer", "q2_prime_answer"):
            sym = col.get(role, {})
            key = (sym.get("path", ""), sym.get("qualified_name", ""))
            if key not in indexed_symbols:
                errors.append(f"{path.name}: collision {col.get('id')} unknown {role} {key}")

    mutations = data.get("mutations", [])
    if len(mutations) < 8:
        errors.append(f"{path.name}: expected >= 8 mutations, got {len(mutations)}")

    poisoning = data.get("poisoning", [])
    if len(poisoning) < 10:
        errors.append(f"{path.name}: expected >= 10 poisoning cases, got {len(poisoning)}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint chain evaluation task files.")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        default=[
            Path("evals/tasks/chain_rich.json"),
            Path("evals/tasks/chain_fastify.json"),
        ],
    )
    args = parser.parse_args()

    all_errors: list[str] = []
    for f in args.files:
        all_errors.extend(lint_chain_file(f, args.config))

    if all_errors:
        for err in all_errors:
            print("ERROR:", err, file=sys.stderr)
        return 1
    print(f"OK: linted {len(args.files)} chain task file(s) with 0 errors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

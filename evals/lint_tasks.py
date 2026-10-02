"""Linter for code localization task set (M5 LARGER-lite).

Validates adherence to the 6 task specification rules:
1. Every gold_symbols[i] exists in current index (matching path + qualified_name).
   Every gold_files[j] exists in the files table.
2. Paths in gold use '/' only, no '\\', no absolute path prefix.
3. Group 'b_hidden_dep' (Rule 15): after lower() and token splitting (snake/camel),
   the query tokens MUST NOT contain: target name, any part of qualified_name >= 4 chars,
   or the file stem of the target file.
4. Group 'c_multi_file': >= 2 distinct gold_files.
5. Exactly 10 tasks per group (30 total); split is reproducible from split_seed.
6. No two tasks have duplicate queries.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

from token_context_mcp.config import default_config_path, index_directory, load_config
from token_context_mcp.index.runner import database_path
from token_context_mcp.index.sqlite_store import SQLiteStore


def split_identifier_tokens(text: str) -> set[str]:
    """Split identifier/phrase into lowercase constituent tokens and raw tokens."""
    tokens: set[str] = set()
    # Add raw words
    tokens.update(re.findall(r"[a-zA-Z0-9]+", text.lower()))
    # Split camelCase
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    tokens.update(re.findall(r"[a-zA-Z0-9]+", s.lower()))
    return tokens


def lint_task_data(
    data: dict[str, Any],
    store: SQLiteStore | None = None,
    *,
    check_split: bool = True,
    per_group: int = 10,
) -> list[str]:
    errors: list[str] = []

    tasks = data.get("tasks", [])
    if not isinstance(tasks, list):
        return ["Tasks field must be a list"]

    split_seed = data.get("split_seed", 20260926)

    # Pre-fetch files and symbols from store if provided
    indexed_files: set[str] = set()
    indexed_symbols: set[tuple[str, str]] = set()

    if store is not None:
        try:
            indexed_files = {f.path for f in store.files()}
            indexed_symbols = {
                (s.path, s.qualified_name or s.name) for s in store.symbols()
            }
        except Exception as e:
            errors.append(f"Failed to query store: {e}")

    # Check Rule 5 part 1: group counts
    group_counts: dict[str, list[dict[str, Any]]] = {
        "a_keyword": [],
        "b_hidden_dep": [],
        "c_multi_file": [],
    }
    seen_queries: dict[str, str] = {}

    for idx, task in enumerate(tasks, 1):
        tid = task.get("id", f"task_{idx}")
        grp = task.get("group")
        query = task.get("query", "").strip()
        gold_files = task.get("gold_files", [])
        gold_symbols = task.get("gold_symbols", [])

        if grp not in group_counts:
            errors.append(f"[{tid}] Invalid group: {grp}")
        else:
            group_counts[grp].append(task)

        # Rule 6: Duplicate query check
        norm_query = query.lower()
        if norm_query in seen_queries:
            errors.append(f"[{tid}] Duplicate query with [{seen_queries[norm_query]}]: '{query}'")
        else:
            seen_queries[norm_query] = tid

        # Rule 2: Path formatting (POSIX forward slashes, non-absolute)
        for gf in gold_files:
            if "\\" in gf:
                errors.append(f"[{tid}] Rule 2: gold_file contains backslash: '{gf}'")
            if gf.startswith("/") or (len(gf) > 2 and gf[1] == ":"):
                errors.append(f"[{tid}] Rule 2: gold_file is an absolute path: '{gf}'")

        for gs in gold_symbols:
            gp = gs.get("path", "")
            if "\\" in gp:
                errors.append(f"[{tid}] Rule 2: gold_symbol path contains backslash: '{gp}'")
            if gp.startswith("/") or (len(gp) > 2 and gp[1] == ":"):
                errors.append(f"[{tid}] Rule 2: gold_symbol path is an absolute path: '{gp}'")

        # Rule 1: Existence in index
        if store is not None:
            for gf in gold_files:
                if gf not in indexed_files and not task.get("gold_pending_indexer") and not any(
                    g.get("gold_pending_indexer") and g.get("path") == gf for g in gold_symbols
                ):
                    errors.append(f"[{tid}] Rule 1: gold_file '{gf}' not found in index")

            for gs in gold_symbols:
                gp = gs.get("path", "")
                gq = gs.get("qualified_name", "")
                if gs.get("gold_pending_indexer"):
                    # Declared as "the old indexer cannot see this symbol yet" (assigned JS methods); the author
                    # verifies def_line by hand. The rest of the task is still linted.
                    if not gs.get("def_line"):
                        errors.append(f"[{tid}] Rule 1: pending gold_symbol '{gp}::{gq}' needs a def_line")
                    continue
                if (gp, gq) not in indexed_symbols:
                    errors.append(f"[{tid}] Rule 1: gold_symbol '{gp}::{gq}' not found in index")

        # Rule 3: Hidden dependencies must not leak target name, stem, or qualified_name parts (>= 4 chars)
        if grp == "b_hidden_dep":
            q_tokens = split_identifier_tokens(query)
            for gs in gold_symbols:
                gp = gs.get("path", "")
                gq = gs.get("qualified_name", "")
                target_name = gq.split(".")[-1]

                name_tokens = split_identifier_tokens(target_name)
                qname_tokens = {t for t in split_identifier_tokens(gq) if len(t) >= 4}

                filename = gp.rsplit("/", 1)[-1]
                stem = filename.split(".")[0] if "." in filename else filename
                stem_tokens = split_identifier_tokens(stem)

                forbidden = name_tokens | qname_tokens | stem_tokens
                overlap = q_tokens & forbidden
                if overlap:
                    errors.append(
                        f"[{tid}] Rule 3 (Rule 15): hidden_dep query leaks forbidden tokens {sorted(overlap)} (from target '{gp}::{gq}')"
                    )

        # Rule 4: Multi-file task requires >= 2 distinct files
        if grp == "c_multi_file":
            distinct_files = set(gold_files)
            if len(distinct_files) < 2:
                errors.append(
                    f"[{tid}] Rule 4: c_multi_file requires >= 2 distinct gold_files, found {len(distinct_files)}"
                )

    # Check Rule 5: Exactly ``per_group`` tasks per group (10 for the full sets, fewer for the light M13 sets)
    for grp_name, grp_tasks in group_counts.items():
        if len(grp_tasks) != per_group:
            errors.append(f"Rule 5: Group '{grp_name}' must have exactly {per_group} tasks, found {len(grp_tasks)}")

    # Check Rule 5: Split reproducibility from split_seed (skipped for all-test sets, e.g. M10 bench)
    if not check_split:
        return errors
    rnd = random.Random(split_seed)
    expected_dev_counts = {"a_keyword": 3, "b_hidden_dep": 3, "c_multi_file": 4}
    for grp_name, grp_tasks in group_counts.items():
        if len(grp_tasks) == 10:
            indices = list(range(1, 11))
            dev_chosen = set(rnd.sample(indices, expected_dev_counts[grp_name]))
            for idx_in_grp, task in enumerate(grp_tasks, 1):
                tid = task.get("id")
                expected_split = "dev" if idx_in_grp in dev_chosen else "heldout"
                actual_split = task.get("split")
                if actual_split != expected_split:
                    errors.append(
                        f"[{tid}] Rule 5: split mismatch for {grp_name} #{idx_in_grp}. Expected '{expected_split}', got '{actual_split}'"
                    )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint task set for code localization evaluation")
    parser.add_argument("--tasks", type=Path, default=Path("evals/tasks/loc_token_context.json"))
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--repo-id", type=str, default="token-context")
    parser.add_argument("--skip-index-check", action="store_true", help="Skip index database checks")
    parser.add_argument("--no-split-check", action="store_true",
                        help="Do not validate the dev/heldout split (all-test sets such as the M10 benchmark)")
    parser.add_argument("--per-group", type=int, default=10,
                        help="Expected number of tasks in each of the three groups (default 10; the light M13 sets use 5)")
    args = parser.parse_args()

    if not args.tasks.exists():
        print(f"ERROR: Task file does not exist: {args.tasks}", file=sys.stderr)
        return 1

    try:
        data = json.loads(args.tasks.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: Failed to parse JSON: {e}", file=sys.stderr)
        return 1

    store = None
    if not args.skip_index_check:
        cfg = load_config(args.config)
        idx_dir = index_directory(args.config)
        db_p = database_path(idx_dir, args.repo_id)
        if db_p.exists():
            store = SQLiteStore(db_p)
        else:
            print(f"WARNING: Database not found at {db_p}. Skipping index symbol checks.", file=sys.stderr)

    errors = lint_task_data(data, store=store, check_split=not args.no_split_check, per_group=args.per_group)

    if errors:
        print(f"FAIL: Found {len(errors)} task lint errors:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(f"SUCCESS: All {len(data.get('tasks', []))} tasks passed all 6 lint rules!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

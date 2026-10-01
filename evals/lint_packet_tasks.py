"""Linter for the M6.3a HCP-packet evaluation task set (M6 Session 1).

Validates:
1. Every target and every gold_context entry (path + qualified_name) exists in the
   current index.
2. Every task has >= 1 gold_context entry whose path differs from the target's path
   (a "must read something in another file" sanity check).
3. The recorded `split` (dev/heldout) is reproducible from `split_seed`: each task's
   target is bucketed as "method" (qualified_name contains "."), else "short_function"
   (<30 lines) or "long_function" (>100 lines) using the *current* index's line counts,
   tasks are grouped by bucket in the order they appear in the `tasks` array, and a
   fixed-count seeded sample (random.Random(split_seed), one shared instance, buckets
   visited in the order short_function -> long_function -> method) picks the "dev"
   tasks within each bucket. This mirrors evals/lint_tasks.py's per-group rnd.sample
   pattern from M5.

Task set authored 2026-09-27 assumed exactly 4 short_function / 4 long_function / 12
method targets with dev counts 2/2/4 (8 dev, 12 heldout total). If the task file is
edited later and a bucket's size no longer matches, this linter fails loudly rather
than silently re-deriving a different split.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

from token_context_mcp.config import default_config_path, index_directory, load_config
from token_context_mcp.index.runner import database_path
from token_context_mcp.index.sqlite_store import SQLiteStore

BUCKET_ORDER = ["short_function", "long_function", "method"]
EXPECTED_BUCKET_SIZE = {"short_function": 4, "long_function": 4, "method": 12}
EXPECTED_DEV_COUNT = {"short_function": 2, "long_function": 2, "method": 4}
MIN_GOLD = 3
MAX_GOLD = 8


def bucket_for(qualified_name: str, length: int) -> str:
    if "." in qualified_name:
        return "method"
    if length < 30:
        return "short_function"
    if length > 100:
        return "long_function"
    return "medium_function"  # not expected to occur; see EXPECTED_BUCKET_SIZE check


def lint_task_data(
    data: dict[str, Any],
    store: SQLiteStore | None = None,
    *,
    tasks_key: str = "tasks",
    check_split: bool = True,
    expected_total: int = 20,
) -> list[str]:
    errors: list[str] = []

    tasks = data.get(tasks_key, [])
    if not isinstance(tasks, list):
        return [f"'{tasks_key}' field must be a list"]

    split_seed = data.get("split_seed", 20260927)

    indexed_symbols: dict[tuple[str, str], Any] = {}
    if store is not None:
        try:
            indexed_symbols = {(s.path, s.qualified_name): s for s in store.symbols()}
        except Exception as e:  # pragma: no cover - defensive
            errors.append(f"Failed to query store: {e}")

    seen_ids: set[str] = set()
    bucket_task_ids: dict[str, list[str]] = {b: [] for b in BUCKET_ORDER}
    bucket_task_ids["medium_function"] = []

    for idx, task in enumerate(tasks, 1):
        tid = task.get("id", f"task_{idx}")
        if tid in seen_ids:
            errors.append(f"[{tid}] Duplicate task id")
        seen_ids.add(tid)

        target = task.get("target", {})
        t_path = target.get("path", "")
        t_qname = target.get("qualified_name", "")
        gold = task.get("gold_context", [])

        if not (MIN_GOLD <= len(gold) <= MAX_GOLD):
            errors.append(f"[{tid}] Rule: gold_context must have {MIN_GOLD}-{MAX_GOLD} entries, found {len(gold)}")

        # Rule 1: existence
        if store is not None:
            if not target.get("gold_pending_indexer") and (t_path, t_qname) not in indexed_symbols:
                errors.append(f"[{tid}] Rule 1: target '{t_path}::{t_qname}' not found in index")
            for gc in gold:
                gp, gq = gc.get("path", ""), gc.get("qualified_name", "")
                if not gc.get("gold_pending_indexer") and (gp, gq) not in indexed_symbols:
                    errors.append(f"[{tid}] Rule 1: gold_context '{gp}::{gq}' not found in index")
                if gc.get("need") not in ("signature", "body"):
                    errors.append(f"[{tid}] Rule: gold_context '{gp}::{gq}' has invalid need={gc.get('need')!r}")
                if not gc.get("why", "").strip():
                    errors.append(f"[{tid}] Rule: gold_context '{gp}::{gq}' missing non-empty 'why'")

        # Rule 2: >=1 cross-file gold_context entry
        if not any(gc.get("path", "") != t_path for gc in gold):
            errors.append(f"[{tid}] Rule 2: no gold_context entry outside target's own file ({t_path})")

        # Rule 3 prep: bucket the target from the live index (fallback: skip bucketing
        # if the target itself wasn't found, already reported above)
        if store is not None and (t_path, t_qname) in indexed_symbols:
            sym = indexed_symbols[(t_path, t_qname)]
            length = (sym.end_line or sym.start_line) - sym.start_line + 1
            bucket = bucket_for(t_qname, length)
            bucket_task_ids.setdefault(bucket, []).append(tid)

    # Rule 3: split reproducibility (only meaningful once every target resolved above)
    if store is not None and check_split:
        for b in BUCKET_ORDER:
            got_size = len(bucket_task_ids.get(b, []))
            exp_size = EXPECTED_BUCKET_SIZE[b]
            if got_size != exp_size:
                errors.append(
                    f"Rule 3: bucket '{b}' has {got_size} tasks, expected {exp_size} "
                    f"(task set assumptions no longer hold; update this linter's EXPECTED_* "
                    f"tables and re-derive the split if the task set was intentionally edited)"
                )
        if bucket_task_ids.get("medium_function"):
            errors.append(
                f"Rule 3: {len(bucket_task_ids['medium_function'])} target(s) fell into the "
                f"unexpected 'medium_function' bucket (30-100 lines, not a method): "
                f"{bucket_task_ids['medium_function']}"
            )

        if not errors or all(not e.startswith("Rule 3:") for e in errors):
            rnd = random.Random(split_seed)
            expected_split: dict[str, str] = {}
            for b in BUCKET_ORDER:
                ids_in_bucket = bucket_task_ids[b]
                n = len(ids_in_bucket)
                dev_k = EXPECTED_DEV_COUNT[b]
                dev_positions = set(rnd.sample(range(1, n + 1), dev_k))
                for pos, tid in enumerate(ids_in_bucket, 1):
                    expected_split[tid] = "dev" if pos in dev_positions else "heldout"

            for task in tasks:
                tid = task.get("id")
                actual = task.get("split")
                expected = expected_split.get(tid)
                if expected is not None and actual != expected:
                    errors.append(
                        f"[{tid}] Rule 3: split mismatch. Expected '{expected}' (seed {split_seed}), got '{actual}'"
                    )

    if check_split:
        dev_count = sum(1 for t in tasks if t.get("split") == "dev")
        heldout_count = sum(1 for t in tasks if t.get("split") == "heldout")
        if dev_count != 8 or heldout_count != 12:
            errors.append(f"Rule: expected exactly 8 dev / 12 heldout tasks, found {dev_count} dev / {heldout_count} heldout")

    if len(tasks) != expected_total:
        errors.append(f"Rule: expected exactly {expected_total} tasks, found {len(tasks)}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint the M6.3a HCP-packet task set")
    parser.add_argument("--tasks", type=Path, default=Path("evals/tasks/packet_token_context.json"))
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--repo-id", type=str, default="token-context")
    parser.add_argument("--skip-index-check", action="store_true", help="Skip index database checks")
    parser.add_argument("--tasks-key", type=str, default="tasks", help="top-level key holding the packet tasks")
    parser.add_argument("--no-split-check", action="store_true",
                        help="Do not validate the dev/heldout split (all-test sets such as the M10 benchmark)")
    parser.add_argument("--expected-total", type=int, default=20)
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

    errors = lint_task_data(
        data, store=store, tasks_key=args.tasks_key,
        check_split=not args.no_split_check, expected_total=args.expected_total,
    )

    if errors:
        print(f"FAIL: Found {len(errors)} task lint errors:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(f"SUCCESS: All {len(data.get(args.tasks_key, []))} tasks passed all lint rules!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

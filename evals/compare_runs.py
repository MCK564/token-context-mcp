"""Compare two benchmark runs (JSONL or summary JSON) task by task."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            task_id = item.get("id") or item.get("task_id")
            if task_id:
                rows[task_id] = item
    return rows


def compare_jsonl_files(base_file: Path, new_file: Path, arm: str) -> list[str]:
    base_rows = load_jsonl(base_file)
    new_rows = load_jsonl(new_file)
    diffs: list[str] = []

    if set(base_rows.keys()) != set(new_rows.keys()):
        diffs.append(f"[{arm}] Task keys mismatch: base={len(base_rows)} new={len(new_rows)}")

    for task_id in sorted(base_rows.keys()):
        if task_id not in new_rows:
            diffs.append(f"[{arm}] Task {task_id} missing in new")
            continue
        b = base_rows[task_id]
        n = new_rows[task_id]

        # Check top-5 files
        b_files = [f.get("path") if isinstance(f, dict) else f for f in (b.get("hit_files") or b.get("files") or [])][:5]
        n_files = [f.get("path") if isinstance(f, dict) else f for f in (n.get("hit_files") or n.get("files") or [])][:5]
        if b_files != n_files:
            diffs.append(f"[{arm}] {task_id} top-5 files mismatch:\n  base: {b_files}\n  new:  {n_files}")

        # Check hit status / acc@5
        for k in ["file_acc_at_5", "acc_at_5", "sym_recall_at_10", "hit"]:
            if k in b and k in n and b[k] != n[k]:
                diffs.append(f"[{arm}] {task_id} {k} mismatch: base={b[k]}, new={n[k]}")

        # Wire tokens (excluding timestamp / run_id variation)
        if "wire_tokens" in b and "wire_tokens" in n:
            diff_tokens = abs(b["wire_tokens"] - n["wire_tokens"])
            if diff_tokens > 20:  # Allow tiny header variations (e.g., commit_sha / run_id length)
                diffs.append(f"[{arm}] {task_id} wire_tokens mismatch: base={b['wire_tokens']}, new={n['wire_tokens']}")

    return diffs


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two benchmark runs.")
    parser.add_argument("--base-dir", type=Path, help="Base directory containing JSONL/summary files")
    parser.add_argument("--new-dir", type=Path, help="New directory containing JSONL/summary files")
    parser.add_argument("--base-file", type=Path, help="Single base JSONL file")
    parser.add_argument("--new-file", type=Path, help="Single new JSONL file")
    args = parser.parse_args()

    all_diffs: list[str] = []

    if args.base_file and args.new_file:
        diffs = compare_jsonl_files(args.base_file, args.new_file, args.base_file.stem)
        all_diffs.extend(diffs)
    elif args.base_dir and args.new_dir:
        base_files = {p.name: p for p in args.base_dir.glob("*.jsonl")}
        new_files = {p.name: p for p in args.new_dir.glob("*.jsonl")}
        common = sorted(set(base_files.keys()) & set(new_files.keys()))
        if not common:
            print(f"No common .jsonl files between {args.base_dir} and {args.new_dir}")
            return 1
        for name in common:
            diffs = compare_jsonl_files(base_files[name], new_files[name], name)
            all_diffs.extend(diffs)
    else:
        parser.print_help()
        return 2

    if not all_diffs:
        print("ALL TASKS IDENTICAL (0 differences in top-5 files, hit accuracy, symbol recall).")
        return 0
    else:
        print(f"Found {len(all_diffs)} differences:")
        for d in all_diffs[:30]:
            print(" ", d)
        if len(all_diffs) > 30:
            print(f"  ... and {len(all_diffs) - 30} more.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""Collect edge resolution reason statistics and diagnose failed tasks."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from token_context_mcp.config import load_config, index_directory


def extract_scope(evidence: list[str]) -> str:
    for item in evidence:
        if item.startswith("scope:"):
            return item[len("scope:"):]
    return "unknown"


def analyze_repo_edges(db_path: Path) -> dict[str, Any]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = con.cursor()

    total_edges = 0
    status_counts: Counter[str] = Counter()
    scope_counts: Counter[str] = Counter()
    status_scope_counts: dict[str, Counter[str]] = {
        "resolved": Counter(),
        "ambiguous": Counter(),
    }

    for row in cur.execute("SELECT status, evidence_json FROM edges"):
        total_edges += 1
        status = row[0]
        evidence = json.loads(row[1]) if row[1] else []
        scope = extract_scope(evidence)

        status_counts[status] += 1
        scope_counts[scope] += 1
        if status in status_scope_counts:
            status_scope_counts[status][scope] += 1
        else:
            status_scope_counts[status] = Counter({scope: 1})

    return {
        "total_edges": total_edges,
        "status_distribution": dict(status_counts),
        "scope_distribution": dict(scope_counts.most_common()),
        "resolved_by_scope": dict(status_scope_counts["resolved"].most_common()),
        "ambiguous_by_scope": dict(status_scope_counts.get("ambiguous", Counter()).most_common()),
    }


def analyze_csvhelper_group_b_failures(tasks_path: Path, r2_jsonl_path: Path) -> list[dict[str, Any]]:
    with open(tasks_path, "r", encoding="utf-8") as f:
        tasks_data = json.load(f)
    task_map = {t["id"]: t for t in tasks_data.get("tasks", []) if t.get("group") == "b_hidden_dep"}

    failures: list[dict[str, Any]] = []
    with open(r2_jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            tid = item.get("id") or item.get("task_id")
            if tid not in task_map:
                continue
            acc = item.get("file_acc_at_5") or (1 if item.get("hit") else 0)
            if acc < 1:
                t = task_map[tid]
                hit_files = [f.get("path") if isinstance(f, dict) else f for f in (item.get("hit_files") or item.get("files") or [])][:5]
                failures.append({
                    "task_id": tid,
                    "query": t.get("query"),
                    "gold_files": t.get("gold_files"),
                    "top_5_files": hit_files,
                    "reason": "Gold file not in top 5",
                })
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Edge reason stats and diagnostics.")
    parser.add_argument("--repo-id", help="Repository ID to analyze")
    parser.add_argument("--all", action="store_true", help="Analyze all registered repos")
    parser.add_argument("--config", type=Path, required=True, help="Path to repos.toml")
    parser.add_argument("--output", type=Path, help="Path to output JSON")
    args = parser.parse_args()

    cfg = load_config(args.config)
    idx_dir = index_directory(args.config)

    repo_ids = list(cfg.repositories.keys()) if args.all else ([args.repo_id] if args.repo_id else [])
    if not repo_ids:
        print("Please specify --repo-id or --all")
        return 1

    results: dict[str, Any] = {}
    for rid in repo_ids:
        db_path = idx_dir / f"{rid}.sqlite"
        if not db_path.exists():
            print(f"Database not found for {rid}: {db_path}")
            continue
        stats = analyze_repo_edges(db_path)
        results[rid] = stats
        print(f"\n=== Edge Reason Stats for {rid} ===")
        print(f"Total edges: {stats['total_edges']}")
        print(f"Status: {stats['status_distribution']}")
        print("Top ambiguous scopes:")
        for s, c in list(stats['ambiguous_by_scope'].items())[:8]:
            print(f"  {s}: {c}")

    if "bench-csvhelper" in results:
        tasks_p = Path("evals/tasks/bench_csvhelper.json")
        r2_p = Path("evals/out/m12/base_csvhelper/bench_csvhelper_R2.jsonl")
        if tasks_p.exists() and r2_p.exists():
            failures = analyze_csvhelper_group_b_failures(tasks_p, r2_p)
            results["csvhelper_group_b_failures"] = failures
            print(f"\nCsvHelper Group B Failures: {len(failures)} tasks")
            for f in failures:
                print(f"  {f['task_id']}: gold={f['gold_files']} top5={f['top_5_files']}")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"\nSaved stats to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

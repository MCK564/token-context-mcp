"""Shared regression gate (prompt section 4.4): compare a run against the pinned baseline.

Compares per-task *ranking* outputs of two loc_eval JSON files (and, with --edge, two
edge_eval JSON files). Latency and wire-token fields are reported but never gate.
Exit code 0 = identical, 1 = differences found.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

LOC_GATE_FIELDS = (
    "hit", "first_gold_file_rank", "first_gold_sym_rank", "file_acc_at_5", "file_recall_at_5",
    "file_mrr", "sym_recall_at_10", "sym_mrr", "sym_acc_at_1", "sym_acc_at_3",
    "top_5_files", "top_10_symbols",
)
EDGE_IGNORED_KEYS = {"tag", "index_run_id", "generated_at", "repo_id", "latency_ms", "timestamp"}


def _load(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def compare_loc(base: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    diffs: list[dict[str, Any]] = []
    b_tasks = {t["id"]: t for t in base["tasks"]}
    n_tasks = {t["id"]: t for t in new["tasks"]}
    for tid in sorted(set(b_tasks) | set(n_tasks)):
        if tid not in b_tasks or tid not in n_tasks:
            diffs.append({"task": tid, "field": "presence", "base": tid in b_tasks, "new": tid in n_tasks})
            continue
        for f in LOC_GATE_FIELDS:
            if b_tasks[tid].get(f) != n_tasks[tid].get(f):
                diffs.append({"task": tid, "field": f, "base": b_tasks[tid].get(f), "new": n_tasks[tid].get(f)})
    info = {
        "base_overall": base.get("overall"), "new_overall": new.get("overall"),
        "mean_wire_tokens_base": base.get("overall", {}).get("mean_wire_tokens"),
        "mean_wire_tokens_new": new.get("overall", {}).get("mean_wire_tokens"),
    }
    return {"kind": "loc", "tasks_compared": len(b_tasks), "differences": diffs, "info": info}


def _deep_diff(a: Any, b: Any, path: str, out: list[dict[str, Any]]) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k in EDGE_IGNORED_KEYS:
                continue
            if k not in a or k not in b:
                out.append({"path": f"{path}/{k}", "base": a.get(k, "<absent>"), "new": b.get(k, "<absent>")})
            else:
                _deep_diff(a[k], b[k], f"{path}/{k}", out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append({"path": path, "base": f"len={len(a)}", "new": f"len={len(b)}"})
        for i, (x, y) in enumerate(zip(a, b)):
            _deep_diff(x, y, f"{path}[{i}]", out)
    elif a != b:
        out.append({"path": path, "base": a, "new": b})


def compare_edge(base: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    diffs: list[dict[str, Any]] = []
    _deep_diff(base, new, "", diffs)
    return {"kind": "edge", "differences": diffs}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True, nargs="+", help="baseline JSON file(s)")
    ap.add_argument("--new", required=True, nargs="+", help="new JSON file(s), same order as --base")
    ap.add_argument("--kind", choices=["loc", "edge"], nargs="+", required=True)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    if not (len(args.base) == len(args.new) == len(args.kind)):
        ap.error("--base, --new and --kind must have the same number of entries")
    results = []
    for b, n, k in zip(args.base, args.new, args.kind):
        r = compare_loc(_load(b), _load(n)) if k == "loc" else compare_edge(_load(b), _load(n))
        r.update({"base_file": b, "new_file": n})
        results.append(r)
    ok = all(not r["differences"] for r in results)
    report = {"identical": ok, "results": results}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    for r in results:
        print(f"{r['kind']:5} {r['new_file']}: {len(r['differences'])} difference(s)")
        for d in r["differences"][:12]:
            print("   ", json.dumps(d, ensure_ascii=False)[:220])
    print("REGRESSION GATE:", "PASS (identical)" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

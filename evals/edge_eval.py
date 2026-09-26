"""Evaluate edge resolution accuracy against the gold set.

Measures:
1. Part A (Resolved Samples Evaluation):
   - Compares the resolved status and target in active index against gold labels.
   - Computes Precision, Accuracy, False Positive count on the stratified sample set.
2. Part B (Pattern Call Sites Recall):
   - Verifies whether each expected call site in src/ correctly resolved to the target.
   - Computes Recall breakdown across the 6 resolution patterns.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from token_context_mcp.config import default_config_path, index_directory, load_config
from token_context_mcp.index.runner import database_path
from token_context_mcp.index.sqlite_store import SQLiteStore
from token_context_mcp.models import EdgeRecord


def load_gold_set(gold_path: Path) -> dict[str, Any]:
    if not gold_path.exists():
        raise FileNotFoundError(f"Gold set file not found: {gold_path}")
    data = json.loads(gold_path.read_text(encoding="utf-8"))
    for req in ("repo_id", "part_a_resolved_samples", "part_b_call_sites"):
        if req not in data:
            raise ValueError(f"Gold set missing required field '{req}'")
    return data


def run_evaluation(
    repo_id: str,
    gold_data: dict[str, Any],
    config_path: Path | None = None,
    tag: str = "baseline",
) -> dict[str, Any]:
    cfg_p = config_path or default_config_path()
    config = load_config(cfg_p)
    idx_dir = index_directory(cfg_p)
    db_p = database_path(idx_dir, repo_id)

    if not db_p.exists():
        raise FileNotFoundError(f"Database not found for repo '{repo_id}' at {db_p}")

    store = SQLiteStore(db_p)
    metadata = store.metadata()
    edges = store.edges()

    # Index active edges by (source_path, source_line)
    edges_by_site: dict[tuple[str, int], list[EdgeRecord]] = defaultdict(list)
    edges_by_id: dict[str, EdgeRecord] = {}

    for e in edges:
        edges_by_site[(e.source_path, e.source_line)].append(e)

    # ----------------------------------------------------
    # Evaluate Part A: Resolved samples
    # ----------------------------------------------------
    part_a_samples = gold_data.get("part_a_resolved_samples", [])
    part_a_results = []
    part_a_correct = 0
    part_a_fp_found = 0
    part_a_tp_found = 0
    part_a_scope_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0, "fp": 0, "tp": 0})

    for sample in part_a_samples:
        src_path = sample["source_path"]
        src_line = sample["source_line"]
        expected_label = sample["label"]  # true_positive or false_positive
        scope = sample.get("scope", "unknown")
        expected_tgt = sample["target_symbol_id"]

        # Check edge in current index at this site
        site_edges = edges_by_site.get((src_path, src_line), [])
        matching_edge = None
        for candidate in site_edges:
            if candidate.target_symbol_id == expected_tgt:
                matching_edge = candidate
                break

        # If edge is present and resolved to the same target:
        is_edge_present = matching_edge is not None and matching_edge.status == "resolved"

        # Judgment:
        # If gold label is true_positive, it is correct IF it is resolved to the target.
        # If gold label is false_positive, in a baseline where the false edge exists, it is an FP flaw.
        # If fixed/filtered, the false edge should NOT be present.
        matched_correctly = False
        if expected_label == "true_positive":
            if is_edge_present:
                matched_correctly = True
                part_a_tp_found += 1
        elif expected_label == "false_positive":
            if not is_edge_present:
                matched_correctly = True  # correctly eliminated or unresolved
            else:
                part_a_fp_found += 1  # still producing false positive

        if matched_correctly:
            part_a_correct += 1

        part_a_scope_stats[scope]["total"] += 1
        if matched_correctly:
            part_a_scope_stats[scope]["correct"] += 1
        if expected_label == "false_positive" and is_edge_present:
            part_a_scope_stats[scope]["fp"] += 1
        if expected_label == "true_positive" and is_edge_present:
            part_a_scope_stats[scope]["tp"] += 1

        part_a_results.append({
            "edge_id": sample.get("edge_id"),
            "source_path": src_path,
            "source_line": src_line,
            "expected_target": expected_tgt,
            "gold_label": expected_label,
            "current_status": matching_edge.status if matching_edge else "none",
            "is_edge_present": is_edge_present,
            "is_correct": matched_correctly,
            "scope": scope,
        })

    part_a_total = len(part_a_samples)
    part_a_accuracy = round(part_a_correct / part_a_total, 4) if part_a_total else 0.0

    # ----------------------------------------------------
    # Evaluate Part B: Pattern Call Sites
    # ----------------------------------------------------
    part_b_sites = gold_data.get("part_b_call_sites", [])
    part_b_results = []
    part_b_found = 0
    pattern_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "found": 0})

    for site in part_b_sites:
        pat = site["pattern"]
        src_path = site["source_path"]
        src_line = site["source_line"]
        exp_tgt_id = site.get("expected_target_symbol_id")
        exp_tgt_name = site.get("expected_target_name")

        site_edges = edges_by_site.get((src_path, src_line), [])

        # Check if any edge at this site resolved to expected target
        found = False
        resolved_tgt = None
        for e in site_edges:
            if e.status != "resolved":
                continue
            is_match = False
            if exp_tgt_id:
                if e.target_symbol_id == exp_tgt_id or (e.target_symbol_id and e.target_symbol_id.startswith(f"{exp_tgt_id}:")):
                    is_match = True
            if not is_match and exp_tgt_name:
                if e.target_name == exp_tgt_name or (e.target_name and exp_tgt_name.endswith(f".{e.target_name}")):
                    is_match = True
            if is_match:
                found = True
                resolved_tgt = e.target_symbol_id or e.target_name
                break

        pattern_stats[pat]["total"] += 1
        if found:
            part_b_found += 1
            pattern_stats[pat]["found"] += 1

        part_b_results.append({
            "pattern": pat,
            "source_path": src_path,
            "source_line": src_line,
            "expected_target": exp_tgt_id or exp_tgt_name,
            "resolved_target": resolved_tgt,
            "resolved": found,
        })

    part_b_total = len(part_b_sites)
    part_b_recall = round(part_b_found / part_b_total, 4) if part_b_total else 0.0

    pattern_recalls = {
        pat: round(stat["found"] / stat["total"], 4) if stat["total"] else 0.0
        for pat, stat in pattern_stats.items()
    }

    report = {
        "tag": tag,
        "repo_id": repo_id,
        "index_run_id": metadata.get("index_run_id"),
        "reviewed_gold": gold_data.get("reviewed", False),
        "part_a": {
            "total_samples": part_a_total,
            "correct_predictions": part_a_correct,
            "accuracy": part_a_accuracy,
            "active_false_positives": part_a_fp_found,
            "active_true_positives": part_a_tp_found,
            "scope_breakdown": dict(part_a_scope_stats),
        },
        "part_b": {
            "total_call_sites": part_b_total,
            "resolved_call_sites": part_b_found,
            "overall_recall": part_b_recall,
            "pattern_recalls": pattern_recalls,
            "pattern_breakdown": dict(pattern_stats),
        }
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate edge resolution accuracy against gold set.")
    parser.add_argument("--repo-id", default="token-context", help="Repo ID")
    parser.add_argument("--config", default=None, help="Path to repos.toml")
    parser.add_argument("--gold", default="evals/gold/edges_token_context.json", help="Path to gold set JSON")
    parser.add_argument("--tag", default="baseline", help="Evaluation tag (e.g. baseline, m4_final)")
    parser.add_argument("--output", default=None, help="Path to output evaluation JSON")

    args = parser.parse_args()
    gold_p = Path(args.gold).expanduser().resolve()
    cfg_p = Path(args.config).expanduser().resolve() if args.config else None

    gold_data = load_gold_set(gold_p)
    report = run_evaluation(args.repo_id, gold_data, config_path=cfg_p, tag=args.tag)

    print(f"=== Edge Evaluation Report: tag='{report['tag']}', repo='{report['repo_id']}' ===")
    print(f"Index run ID: {report['index_run_id']}, Gold reviewed: {report['reviewed_gold']}")
    print()
    print("--- Part A: Stratified Resolved Samples ---")
    pa = report["part_a"]
    print(f"Total samples: {pa['total_samples']}, Accuracy: {pa['accuracy']*100:.2f}%")
    print(f"Active True Positives: {pa['active_true_positives']}, Active False Positives: {pa['active_false_positives']}")
    print("Scope Breakdown:")
    for sc, st in pa["scope_breakdown"].items():
        print(f"  {sc:<30} Total: {st['total']:2d} | Correct: {st['correct']:2d} | FP: {st['fp']:2d} | TP: {st['tp']:2d}")

    print()
    print("--- Part B: 6-Pattern Call Site Recall ---")
    pb = report["part_b"]
    print(f"Total Call Sites: {pb['total_call_sites']}, Resolved: {pb['resolved_call_sites']}, Overall Recall: {pb['overall_recall']*100:.2f}%")
    print("Pattern Recalls:")
    for pat, rec in pb["pattern_recalls"].items():
        st = pb["pattern_breakdown"][pat]
        print(f"  {pat:<25} {rec*100:6.1f}% ({st['found']}/{st['total']})")

    if args.output:
        out_p = Path(args.output).expanduser().resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with out_p.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"\nSaved evaluation report to {out_p}")


if __name__ == "__main__":
    main()

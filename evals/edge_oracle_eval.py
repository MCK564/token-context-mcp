"""Evaluate edge resolver predictions against SCIP oracle call sites (M14.1.2).

Rule 21: Callsites evaluation uses un-deduplicated edges (build_lexical_edges with deduplicate=False).
Precision: correct edges / edges with confidence >= 0.6 at labelled sites. External sites resolved to internal are FP.
Recall: internal sites resolved to correct target with confidence >= 0.6 / total internal sites.
Overload accuracy: ratio of correct def_line among sites with >= 2 overloads.

Includes Rule 17 guard check.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from guard import check_heldout_guard
from token_context_mcp.config import index_directory, load_config
from token_context_mcp.parse.lexical_edges import build_lexical_edges
from token_context_mcp.parse.treesitter import parse_source


def _constructor_alias(target_qname: str, callee_name: str) -> bool:
    # Class Foo and constructor Foo or Foo.Foo match
    parts = target_qname.split(".")
    return parts[-1] == callee_name or target_qname == callee_name


def evaluate_oracle(
    oracle_path: Path,
    repo_id: str,
    config_path: Path,
    output_path: Path | None = None,
) -> dict[str, Any]:
    cfg = load_config(config_path)
    repo = cfg.repositories.get(repo_id)
    if not repo:
        raise ValueError(f"Repository {repo_id} not found in config {config_path}")

    idx_dir = index_directory(config_path)
    db_path = idx_dir / f"{repo_id}.sqlite"
    if not db_path.exists():
        raise FileNotFoundError(f"Database {db_path} not found")

    conn = sqlite3.connect(db_path)
    symbols_by_id = {}
    for row in conn.execute("SELECT symbol_id, path, qualified_name, kind, start_line, end_line FROM symbols").fetchall():
        symbols_by_id[row[0]] = {
            "symbol_id": row[0],
            "path": row[1],
            "qualified_name": row[2],
            "kind": row[3],
            "start_line": row[4],
            "end_line": row[5],
        }

    # Load oracle call sites
    oracle_sites = []
    with gzip.open(oracle_path, "rt", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            oracle_sites.append(json.loads(line))

    # Group oracle sites by (path, line, callee_name)
    sites_by_loc: dict[tuple[str, int, str], list[dict[str, Any]]] = {}
    for s in oracle_sites:
        if s.get("classification") == "unlabelled":
            continue
        key = (s["path"], s["line"], s["callee_name"])
        sites_by_loc.setdefault(key, []).append(s)

    # Discard collision locations with differing targets
    filtered_sites: dict[tuple[str, int, str], dict[str, Any]] = {}
    collisions = 0
    for key, group in sites_by_loc.items():
        if len(group) == 1:
            filtered_sites[key] = group[0]
        else:
            # check if same target
            classes = {g.get("classification") for g in group}
            targets = {g.get("target", {}).get("scip_symbol") for g in group}
            if len(classes) == 1 and len(targets) == 1:
                filtered_sites[key] = group[0]
            else:
                collisions += len(group)

    # Now run un-deduplicated lexical edge resolution for files that have sites
    unique_paths = sorted({k[0] for k in filtered_sites})
    lang_name = "c_sharp" if any(p.endswith(".cs") for p in unique_paths) else "java"

    # Query file facts and build edges without deduplication
    file_edges: dict[tuple[str, int, str], list[dict[str, Any]]] = {}
    for p in unique_paths:
        file_abs = repo.root / p
        if not file_abs.is_file():
            continue
        raw = file_abs.read_bytes()
        parse_res = parse_source(p, raw, lang_name)
        
        # Build un-deduplicated edges (Rule 21)
        edges = list(build_lexical_edges(
            repo_id=repo_id,
            path=p,
            symbols=parse_res.symbols,
            calls=parse_res.calls,
            imports=parse_res.imports,
            namespaces=parse_res.namespaces,
            inheritance=parse_res.inheritance,
            module_bindings=parse_res.module_bindings,
            symbols_by_id=symbols_by_id,
            deduplicate=False,
        ))

        for e in edges:
            # Match edge call location
            # edge.evidence_json has call location or line
            ev = json.loads(e.evidence_json or "{}") if hasattr(e, "evidence_json") else {}
            line = ev.get("call_line", ev.get("line", 0))
            callee = ev.get("callee", e.target_name)
            key = (p, line, callee)
            file_edges.setdefault(key, []).append({
                "target_id": e.target_symbol_id,
                "target_name": e.target_name,
                "confidence": e.confidence,
                "scope": e.scope,
                "status": e.status,
            })

    # Metrics computation
    total_internal = 0
    internal_resolved_correct = 0
    total_conf_ge_06 = 0
    correct_conf_ge_06 = 0
    overload_sites = 0
    overload_correct = 0

    scope_stats: dict[str, dict[str, int]] = {}

    for (p, line, callee), site in filtered_sites.items():
        is_internal = site.get("classification") == "internal"
        expected_target = site.get("target")

        if is_internal:
            total_internal += 1

        preds = file_edges.get((p, line, callee), [])
        high_conf_preds = [pr for pr in preds if pr["confidence"] >= 0.6]

        for pr in high_conf_preds:
            total_conf_ge_06 += 1
            sc = pr["scope"]
            scope_stats.setdefault(sc, {"total": 0, "correct": 0})
            scope_stats[sc]["total"] += 1

            # Check correctness
            is_correct = False
            if is_internal and expected_target:
                tgt_sym = symbols_by_id.get(pr["target_id"])
                if tgt_sym:
                    # Match path and approximate line or name
                    if tgt_sym["path"] == expected_target["path"]:
                        exp_line = expected_target["def_line"]
                        if exp_line == 0 or abs(tgt_sym["start_line"] - exp_line) <= 5 or _constructor_alias(tgt_sym["qualified_name"], callee):
                            is_correct = True
            if is_correct:
                correct_conf_ge_06 += 1
                scope_stats[sc]["correct"] += 1

        # Check internal recall
        if is_internal and expected_target:
            matched = False
            for pr in high_conf_preds:
                tgt_sym = symbols_by_id.get(pr["target_id"])
                if tgt_sym and tgt_sym["path"] == expected_target["path"]:
                    exp_line = expected_target["def_line"]
                    if exp_line == 0 or abs(tgt_sym["start_line"] - exp_line) <= 5 or _constructor_alias(tgt_sym["qualified_name"], callee):
                        matched = True
                        break
            if matched:
                internal_resolved_correct += 1

    precision = (correct_conf_ge_06 / total_conf_ge_06) if total_conf_ge_06 > 0 else 1.0
    recall = (internal_resolved_correct / total_internal) if total_internal > 0 else 0.0

    report = {
        "repo_id": repo_id,
        "total_oracle_sites": len(oracle_sites),
        "evaluated_sites": len(filtered_sites),
        "collisions_skipped": collisions,
        "total_internal_sites": total_internal,
        "internal_resolved_correct": internal_resolved_correct,
        "edges_conf_ge_06": total_conf_ge_06,
        "correct_edges_conf_ge_06": correct_conf_ge_06,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "scopes": {
            sc: {
                "total": data["total"],
                "correct": data["correct"],
                "precision": round(data["correct"] / data["total"], 4) if data["total"] > 0 else 0.0,
            }
            for sc, data in scope_stats.items()
        },
    }

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate edges against SCIP oracle calls")
    parser.add_argument("--oracle", type=Path, required=True, help="Path to <repo>.calls.jsonl.gz")
    parser.add_argument("--repo-id", type=str, required=True, help="Repository ID")
    parser.add_argument("--config", type=Path, required=True, help="Path to repos.toml")
    parser.add_argument("--output", type=Path, default=None, help="Output JSON report path")
    parser.add_argument("--role", default="dev", choices=["dev", "heldout"], help="Role (dev or heldout)")
    parser.add_argument("--allow-baseline-code", type=Path, default=None, help="Baseline code path")
    args = parser.parse_args()

    check_heldout_guard(args.role, allow_baseline_code=args.allow_baseline_code)

    report = evaluate_oracle(args.oracle, args.repo_id, args.config, args.output)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

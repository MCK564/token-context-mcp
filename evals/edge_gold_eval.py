"""Evaluate edge resolution against an AST-sampled gold set.

Measures:
1. Precision on matched edges with confidence >= 0.6 across sampled call sites.
2. Recall on call sites that have an internal expected target symbol.
3. Breakdown of precision and coverage by resolution scope.

Enforces Rule 17 (held-out guard) when --role heldout is specified.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from guard import check_heldout_guard  # noqa: E402
from token_context_mcp.config import default_config_path, index_directory, load_config  # noqa: E402
from token_context_mcp.index.runner import database_path  # noqa: E402
from token_context_mcp.index.sqlite_store import SQLiteStore  # noqa: E402
from token_context_mcp.models import EdgeRecord, SymbolRecord  # noqa: E402


def extract_scope(evidence: list[str]) -> str:
    for item in evidence:
        if item.startswith("scope:"):
            return item[len("scope:"):]
    return "unknown"


def callee_matches(callee_text: str, target_name: str) -> bool:
    target_name = (target_name or "").strip()
    if not target_name:
        return False
    callee = callee_text.strip()
    if callee == target_name:
        return True
    callee_id = callee.split("(")[0].strip()
    if callee_id == target_name or callee_id.endswith(f".{target_name}") or callee_id.endswith(f"->{target_name}"):
        return True
    if callee_id.startswith("new ") and callee_id[4:].strip().split("(")[0].strip() == target_name:
        return True
    last_token = callee_id.split(".")[-1].strip()
    return last_token == target_name


def target_matches(edge: EdgeRecord, expected: dict[str, Any], symbols: dict[str, SymbolRecord]) -> bool:
    if not edge.target_symbol_id:
        return False
    sym = symbols.get(edge.target_symbol_id)
    if not sym:
        return False
    exp_path = expected.get("path")
    exp_qname = expected.get("qualified_name")
    if exp_path and sym.path != exp_path:
        return False
    if not exp_qname:
        return True
    sym_qname = sym.qualified_name
    if sym_qname == exp_qname:
        return True
    # Strip signature/overload parameters e.g. "Method(int)" vs "Method"
    if sym_qname.split("(")[0].strip() == exp_qname.split("(")[0].strip():
        return True
    return False


def load_gold_set(gold_path: Path) -> dict[str, Any]:
    if not gold_path.exists():
        raise FileNotFoundError(f"Gold set file not found: {gold_path}")
    data = json.loads(gold_path.read_text(encoding="utf-8"))
    if "sites" not in data and "call_sites" in data:
        data["sites"] = data["call_sites"]
    if "sites" not in data:
        raise ValueError(f"Gold set missing 'sites' in {gold_path}")
    return data


def run_edge_gold_evaluation(
    repo_id: str,
    gold_data: dict[str, Any],
    config_path: Path | None = None,
    tag: str = "baseline",
    role: str = "dev",
    allow_baseline_code: Path | str | None = None,
) -> dict[str, Any]:
    check_heldout_guard(role, allow_baseline_code=allow_baseline_code)

    cfg_p = config_path or default_config_path()
    idx_dir = index_directory(cfg_p)
    db_p = database_path(idx_dir, repo_id)
    if not db_p.exists():
        raise FileNotFoundError(f"Database not found for repo '{repo_id}' at {db_p}")

    store = SQLiteStore(db_p)
    metadata = store.metadata()
    edges = store.edges()
    symbols = {s.symbol_id: s for s in store.symbols()}

    edges_by_site: dict[tuple[str, int], list[EdgeRecord]] = defaultdict(list)
    for e in edges:
        edges_by_site[(e.source_path, e.source_line)].append(e)

    sites = gold_data.get("sites", [])
    site_evaluations: list[dict[str, Any]] = []

    total_ge_06 = 0
    correct_ge_06 = 0
    fp_ge_06 = 0

    scope_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"total_ge_06": 0, "correct_ge_06": 0, "fp_ge_06": 0})

    internal_sites = 0
    internal_resolved_correctly = 0

    for site in sites:
        src_path = site["path"]
        src_line = site["line"]
        callee_text = site.get("callee_text", "")
        expected = site.get("expected")
        reason = site.get("reason", "")

        is_internal = isinstance(expected, dict) and "qualified_name" in expected
        if is_internal:
            internal_sites += 1

        site_candidates = edges_by_site.get((src_path, src_line), [])
        matched_edges = [e for e in site_candidates if callee_matches(callee_text, e.target_name)]
        if not matched_edges and len(site_candidates) == 1:
            # Fallback if single edge at call site
            cand = site_candidates[0]
            if cand.target_name and cand.target_name in callee_text:
                matched_edges = [cand]

        site_correct = False
        resolved_edge = None

        if is_internal:
            for e in matched_edges:
                if e.status == "resolved" and target_matches(e, expected, symbols):
                    site_correct = True
                    resolved_edge = e
                    break
            if site_correct:
                internal_resolved_correctly += 1

        edge_evals = []
        for e in matched_edges:
            conf = e.confidence if e.confidence is not None else 0.0
            scope = extract_scope(e.evidence)
            is_edge_correct = False

            if is_internal:
                is_edge_correct = (e.status == "resolved" and target_matches(e, expected, symbols))
            else:
                # External / dynamic / unknown: an internal resolution is a false positive
                is_edge_correct = (e.status != "resolved" or not e.target_symbol_id)

            if conf >= 0.6:
                total_ge_06 += 1
                scope_stats[scope]["total_ge_06"] += 1
                if is_edge_correct:
                    correct_ge_06 += 1
                    scope_stats[scope]["correct_ge_06"] += 1
                else:
                    fp_ge_06 += 1
                    scope_stats[scope]["fp_ge_06"] += 1

            edge_evals.append({
                "target_name": e.target_name,
                "target_symbol_id": e.target_symbol_id,
                "status": e.status,
                "confidence": conf,
                "scope": scope,
                "is_correct": is_edge_correct,
            })

        site_evaluations.append({
            "path": src_path,
            "line": src_line,
            "callee_text": callee_text,
            "expected": expected,
            "reason": reason,
            "is_internal": is_internal,
            "site_resolved_correctly": site_correct,
            "resolved_edge": edge_evals,
        })

    precision = round(correct_ge_06 / total_ge_06, 4) if total_ge_06 > 0 else 1.0
    recall = round(internal_resolved_correctly / internal_sites, 4) if internal_sites > 0 else 1.0

    scope_report = {}
    for sc, st in sorted(scope_stats.items()):
        tot = st["total_ge_06"]
        cor = st["correct_ge_06"]
        prec = round(cor / tot, 4) if tot > 0 else 1.0
        scope_report[sc] = {
            "total_ge_06": tot,
            "correct_ge_06": cor,
            "fp_ge_06": st["fp_ge_06"],
            "precision": prec,
        }

    return {
        "tag": tag,
        "repo_id": repo_id,
        "role": role,
        "index_run_id": metadata.get("index_run_id"),
        "reviewed_gold": gold_data.get("reviewed", False),
        "total_call_sites": len(sites),
        "internal_call_sites": internal_sites,
        "precision": {
            "threshold": 0.6,
            "total_edges_ge_06": total_ge_06,
            "correct_edges": correct_ge_06,
            "false_positives": fp_ge_06,
            "precision": precision,
        },
        "recall": {
            "total_internal_sites": internal_sites,
            "resolved_correctly": internal_resolved_correctly,
            "recall": recall,
        },
        "scope_breakdown": scope_report,
        "sites": site_evaluations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate edge resolution against an AST-sampled gold set.")
    parser.add_argument("--gold", type=Path, required=True, help="Path to edge gold set JSON")
    parser.add_argument("--config", type=Path, default=None, help="Path to repos.toml")
    parser.add_argument("--repo-id", default=None, help="Repository ID in index")
    parser.add_argument("--role", default="dev", choices=["dev", "heldout"], help="Evaluation role (dev or heldout)")
    parser.add_argument("--allow-baseline-code", type=Path, default=None, help="Path to baseline code to bypass freeze guard")
    parser.add_argument("--tag", default="baseline", help="Tag for report (e.g. baseline, m12_final)")
    parser.add_argument("--output", type=Path, default=None, help="Path to output JSON")

    args = parser.parse_args()
    gold_data = load_gold_set(args.gold)
    repo_id = args.repo_id or gold_data.get("repo_id")
    if not repo_id:
        print("Error: --repo-id must be specified or present in gold file.", file=sys.stderr)
        return 2

    report = run_edge_gold_evaluation(
        repo_id=repo_id,
        gold_data=gold_data,
        config_path=args.config,
        tag=args.tag,
        role=args.role,
        allow_baseline_code=args.allow_baseline_code,
    )

    p_info = report["precision"]
    r_info = report["recall"]
    print(f"=== Edge Gold Evaluation: repo='{report['repo_id']}', tag='{report['tag']}', role='{report['role']}' ===")
    print(f"Sites: {report['total_call_sites']} total ({report['internal_call_sites']} internal targets)")
    print(f"Precision (conf >= 0.6): {p_info['precision']*100:.2f}% ({p_info['correct_edges']}/{p_info['total_edges_ge_06']}), FP: {p_info['false_positives']}")
    print(f"Recall (internal targets): {r_info['recall']*100:.2f}% ({r_info['resolved_correctly']}/{r_info['total_internal_sites']})")
    print("\nScope Breakdown (conf >= 0.6):")
    for sc, st in report["scope_breakdown"].items():
        print(f"  {sc:<25} Precision: {st['precision']*100:6.1f}% ({st['correct_ge_06']}/{st['total_ge_06']}) | FP: {st['fp_ge_06']}")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nSaved report to {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

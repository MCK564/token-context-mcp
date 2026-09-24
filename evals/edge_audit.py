"""Audit graph edges for suspicious disambiguations and in-degree hotspots (M0 baseline).

Defines suspicious edges (generic method names called via global fallback,
receiver type mismatches, ambiguous status, or low confidence) and reports
the top 20 destinations by in-degree.
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
from token_context_mcp.models import EdgeRecord, SymbolRecord

GENERIC_NAMES = {
    "get", "set", "run", "close", "save", "load", "update", "read", "write",
    "execute", "process", "format", "render", "parse", "connect", "handle",
    "start", "stop", "reset", "clear", "build", "create", "delete", "send"
}


def is_suspicious_edge(edge: EdgeRecord, target_sym: SymbolRecord | None) -> tuple[bool, list[str]]:
    """Determine whether an edge is suspicious and collect reasons."""
    reasons: list[str] = []

    # 1. Ambiguous resolution
    if edge.status == "ambiguous" or not edge.target_symbol_id:
        reasons.append("ambiguous_status")

    # 2. Low confidence
    if edge.confidence <= 0.40:
        reasons.append(f"low_confidence_{edge.confidence:.2f}")

    # 3. Global fallback scope
    evidence_str = " ".join(edge.evidence) if edge.evidence else ""
    if "scope:global" in evidence_str:
        reasons.append("scope_global_fallback")

    # 4. Generic method name with likely receiver mismatch
    name = edge.target_name.lower()
    if name in GENERIC_NAMES:
        # Check receiver
        for ev in edge.evidence:
            if ev.startswith("receiver:"):
                rec = ev.split(":", 1)[1].strip()
                if rec in {"dict", "os.environ", "response", "result", "raw", "manifest", "usage", "agent", "topic", "i"}:
                    reasons.append(f"generic_name_builtin_receiver:{rec}")
                elif target_sym and target_sym.qualified_name:
                    cls_prefix = target_sym.qualified_name.rsplit(".", 1)[0].lower()
                    if cls_prefix and cls_prefix not in rec.lower():
                        reasons.append(f"receiver_mismatch:{rec}_vs_{cls_prefix}")

    return len(reasons) > 0, reasons


def audit_edges(
    repo_id: str,
    config_path: Path | None = None,
    top_k: int = 20,
) -> dict[str, Any]:
    cfg_p = config_path or default_config_path()
    config = load_config(cfg_p)
    idx_dir = index_directory(cfg_p)
    db_path = database_path(idx_dir, repo_id)

    if not db_path.exists():
        raise FileNotFoundError(f"Database not found for repo '{repo_id}' at {db_path}")

    store = SQLiteStore(db_path)
    symbols = {s.symbol_id: s for s in store.symbols()}
    edges = store.edges()

    # Aggregate by target_symbol_id
    target_edges: dict[str, list[EdgeRecord]] = defaultdict(list)
    unresolved_edges: list[EdgeRecord] = []

    for edge in edges:
        if edge.target_symbol_id:
            target_edges[edge.target_symbol_id].append(edge)
        else:
            unresolved_edges.append(edge)

    # Calculate in-degree metrics
    target_stats: list[dict[str, Any]] = []
    total_suspicious = 0

    for target_id, in_edges in target_edges.items():
        sym = symbols.get(target_id)
        sym_name = sym.name if sym else target_id.split(":")[-2] if ":" in target_id else target_id
        sym_path = sym.path if sym else ""
        sym_qname = sym.qualified_name if sym else sym_name

        suspicious_count = 0
        reasons_tally: dict[str, int] = defaultdict(int)

        for e in in_edges:
            susp, reasons = is_suspicious_edge(e, sym)
            if susp:
                suspicious_count += 1
                total_suspicious += 1
                for r in reasons:
                    reasons_tally[r] += 1

        resolved_count = sum(1 for e in in_edges if e.status == "resolved")
        ambiguous_count = sum(1 for e in in_edges if e.status == "ambiguous")

        target_stats.append({
            "target_symbol_id": target_id,
            "name": sym_name,
            "qualified_name": sym_qname,
            "path": sym_path,
            "in_degree": len(in_edges),
            "resolved_count": resolved_count,
            "ambiguous_count": ambiguous_count,
            "suspicious_count": suspicious_count,
            "suspicious_ratio": round(suspicious_count / len(in_edges), 3) if in_edges else 0.0,
            "reasons": dict(reasons_tally),
        })

    # Sort by in_degree descending
    target_stats.sort(key=lambda x: (x["in_degree"], x["suspicious_count"]), reverse=True)
    top_targets = target_stats[:top_k]

    return {
        "repo_id": repo_id,
        "total_symbols": len(symbols),
        "total_edges": len(edges),
        "unresolved_edges": len(unresolved_edges),
        "total_suspicious_edges": total_suspicious,
        "top_destinations": top_targets,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit edges for suspicious resolution and in-degree traps.")
    parser.add_argument("--repo-id", default="token-context", help="Repository ID to audit")
    parser.add_argument("--config", default=None, help="Path to repos.toml configuration")
    parser.add_argument("--top", type=int, default=20, help="Number of top destinations to report (default 20)")
    parser.add_argument("--output", default=None, help="Path to save JSON audit report")

    args = parser.parse_args()
    cfg_p = Path(args.config).expanduser().resolve() if args.config else None

    report = audit_edges(args.repo_id, config_path=cfg_p, top_k=args.top)

    print(f"=== Edge Audit for repo '{args.repo_id}' ===")
    print(f"Total symbols: {report['total_symbols']}, Total edges: {report['total_edges']}, Suspicious edges: {report['total_suspicious_edges']}")
    print()
    print(f"{'#':<3} {'Target Symbol':<35} {'Path':<35} {'In-Deg':>7} {'Susp':>6} {'Amb':>5} {'Susp %':>7}")
    print("-" * 102)

    for i, t in enumerate(report["top_destinations"], 1):
        print(f"{i:<3} {t['qualified_name']:<35} {t['path']:<35} {t['in_degree']:>7} {t['suspicious_count']:>6} {t['ambiguous_count']:>5} {t['suspicious_ratio']*100:>6.1f}%")

    if args.output:
        out_p = Path(args.output).expanduser().resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with out_p.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"\nSaved edge audit report to {out_p}")


if __name__ == "__main__":
    main()

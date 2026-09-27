"""Composite retrieval workflows combining multi-step operations (P2)."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from token_context_mcp.retrieve.projection import OutputProjector
from token_context_mcp.retrieve.service import RetrievalError, RetrievalService
from token_context_mcp.retrieve.token_budget import estimate_tokens

# M6, E14: edges below this confidence, or produced by a non-"lexical" backend
# (ambiguous status, or a virtual_stub external-call guess), never surface as an
# inspect_symbol relationship in any view. See RetrievalService.symbol_relationships.
RELATIONSHIP_MIN_CONFIDENCE = 0.5


def _edge_other_id(edge: Dict[str, Any], target_symbol_id: str) -> Optional[str]:
    """The *other* endpoint of a relationship edge, from the target symbol's point of view."""
    if edge.get("source_symbol_id") == target_symbol_id:
        return edge.get("target_symbol_id") or edge.get("target_name")
    return edge.get("source_symbol_id")


def _edge_relation(edge: Dict[str, Any], target_symbol_id: str) -> str:
    return "callee" if edge.get("source_symbol_id") == target_symbol_id else "caller"


def _edge_compact_tuple(edge: Dict[str, Any], target_symbol_id: str) -> List[Any]:
    """``minimal`` view relationship shape: ``[symbol_id, "callee"|"caller", confidence]``."""
    return [_edge_other_id(edge, target_symbol_id), _edge_relation(edge, target_symbol_id), edge.get("confidence")]


def _edge_normal_dict(edge: Dict[str, Any]) -> Dict[str, Any]:
    """``normal``/``full`` view relationship shape (unchanged from the pre-M6 contract)."""
    return {
        "source": edge.get("source_symbol_id"),
        "target": edge.get("target_symbol_id") or edge.get("target_name"),
        "kind": edge.get("edge_kind"),
        "confidence": edge.get("confidence"),
    }


def _pack_rows_to_budget(rows: List[Any], budget_tokens: int) -> Tuple[List[Any], int]:
    """Keep as many leading rows (already sorted best-first) as fit in budget_tokens.

    Only a genuine, positive shortfall drops rows -- this is the E14 fix: relationships
    are no longer lost to an internal, unrelated packing budget (impact_slice's own),
    only to the composite call's own remaining budget, and only when they truly don't fit.
    """
    if budget_tokens <= 0 or not rows:
        return [], len(rows)
    kept = list(rows)
    while kept and estimate_tokens(json.dumps(kept)) > budget_tokens:
        kept.pop()
    return kept, len(rows) - len(kept)


class CompositeWorkflowEngine:
    """Executes high-frequency compound retrieval workflows in a single agent turn."""

    def __init__(self, service: RetrievalService) -> None:
        self.service = service

    def inspect_symbol(
        self,
        repo_id: str,
        query: str,
        view: str = "normal",
        budget_tokens: int = 2048,
    ) -> Dict[str, Any]:
        """Resolve a symbol candidate, fetch its definition context and immediate impact in one turn."""
        with self.service.request_scope(repo_id):
            return self._inspect_symbol_scoped(
                repo_id=repo_id,
                query=query,
                view=view,
                budget_tokens=budget_tokens,
            )

    def _inspect_symbol_scoped(
        self,
        repo_id: str,
        query: str,
        view: str = "normal",
        budget_tokens: int = 2048,
    ) -> Dict[str, Any]:
        budget_tokens = max(256, min(budget_tokens, 8192))
        edge_budget = min(1024, max(256, budget_tokens // 4))
        ctx_budget = min(4096, max(256, budget_tokens - edge_budget))


        # 1. Resolve candidates
        find_res = self.service.find_symbols(repo_id, pattern=query, limit=5)
        if "error" in find_res:
            return find_res

        symbols = find_res.get("data", {}).get("symbols", [])
        if not symbols:
            return {
                "schema_version": "1.0",
                "repo_id": repo_id,
                "index_run_id": find_res.get("index_run_id"),
                "freshness": find_res.get("freshness"),
                "budget": {"requested_tokens": budget_tokens, "estimated_tokens": 0},
                "truncated": False,
                "warnings": find_res.get("warnings", []),
                "evidence": [],
                "data": {
                    "status": "not_found",
                    "query": query,
                    "message": f"No symbol found matching '{query}'.",
                },
            }

        # Select target symbol: prefer exact name match
        target_sym = None
        exact_matches = [s for s in symbols if s.get("name", "").lower() == query.lower()]
        if len(exact_matches) == 1:
            target_sym = exact_matches[0]
        elif len(symbols) == 1:
            target_sym = symbols[0]
        else:
            # Ambiguous resolution
            candidates = [
                {
                    "symbol_id": s.get("symbol_id"),
                    "name": s.get("name"),
                    "kind": s.get("kind"),
                    "path": s.get("path"),
                    "start_line": s.get("start_line"),
                    "line": s.get("start_line"),
                }
                for s in symbols[:5]
            ]
            return {
                "schema_version": "1.0",
                "repo_id": repo_id,
                "index_run_id": find_res.get("index_run_id"),
                "freshness": find_res.get("freshness"),
                "budget": {"requested_tokens": budget_tokens, "estimated_tokens": 0},
                "truncated": False,
                "warnings": find_res.get("warnings", []),
                "evidence": [],
                "data": {
                    "status": "ambiguous",
                    "query": query,
                    "candidate_count": len(symbols),
                    "candidates": candidates,
                    "message": f"Found {len(symbols)} candidate symbols. Specify exact symbol_id.",
                },
            }

        symbol_id = target_sym["symbol_id"]

        # 2. Get symbol context with depth=0
        include_body = (view != "minimal")
        ctx_res = self.service.symbol_context(
            repo_id=repo_id,
            symbol_id=symbol_id,
            depth=0,
            include_body=include_body,
            max_tokens=ctx_budget,
        )
        if "error" in ctx_res:
            return ctx_res

        # 3. Fetch direct relationships straight from the graph (E14 fix): this bypasses
        # impact_slice's own internal packing budget entirely, so a small overall
        # budget_tokens can no longer wipe out every relationship the way it used to
        # (docs/BACKLOG.md E14) -- only the packing into edge_budget below can drop a
        # relationship now, and only when it genuinely doesn't fit.
        warnings: list[str] = []
        for w in ctx_res.get("warnings", []):
            if w not in warnings:
                warnings.append(w)

        try:
            rel_res = self.service.symbol_relationships(
                repo_id=repo_id,
                symbol_id=symbol_id,
                min_confidence=RELATIONSHIP_MIN_CONFIDENCE,
            )
            all_edges = rel_res.get("edges", [])
            relationships_filtered = rel_res.get("filtered_out_count", 0)
        except RetrievalError:
            all_edges = []
            relationships_filtered = 0
            if "relationships_unavailable" not in warnings:
                warnings.append("relationships_unavailable")

        # Extract matching symbol entry from ctx_res["data"]["symbols"]
        matched_entry = None
        for entry in ctx_res.get("data", {}).get("symbols", []):
            sym_rec = entry.get("symbol", {})
            if sym_rec.get("symbol_id") == symbol_id:
                matched_entry = entry
                break
        if not matched_entry and ctx_res.get("data", {}).get("symbols"):
            matched_entry = ctx_res["data"]["symbols"][0]

        matched_sym = dict(matched_entry.get("symbol", {})) if matched_entry else dict(target_sym)
        matched_content = matched_entry.get("content") if matched_entry else None

        retry_hint = None
        if view in ("normal", "full") and matched_content is None:
            if "content_omitted_budget" not in warnings:
                warnings.append("content_omitted_budget")
            retry_hint = {
                "tool": "get_symbol_context",
                "symbol_id": symbol_id,
                "include_body": True,
                "depth": 0,
                "max_tokens": 4096,
            }

        # Pack the (already deterministically sorted, quality-filtered) relationships
        # into whatever budget remains, in the view's own wire shape: minimal's compact
        # 3-tuples cost less per edge than normal/full's dicts, so each view packs its
        # own row representation rather than sharing one already-trimmed list.
        if view == "minimal":
            candidate_rows: list = [_edge_compact_tuple(e, symbol_id) for e in all_edges]
        else:
            candidate_rows = [_edge_normal_dict(e) for e in all_edges]
        rel_rows, omitted_edge_count = _pack_rows_to_budget(candidate_rows, edge_budget)

        if omitted_edge_count > 0 and "relationships_truncated" not in warnings:
            warnings.append("relationships_truncated")

        if view == "minimal":
            symbol_payload = {
                "symbol_id": matched_sym.get("symbol_id"),
                "name": matched_sym.get("name"),
                "kind": matched_sym.get("kind"),
                "path": matched_sym.get("path"),
                "start_line": matched_sym.get("start_line"),
                "signature": matched_sym.get("signature"),
            }
            composite_data = {
                "status": "resolved",
                "query": query,
                "target_symbol_id": symbol_id,
                "symbol": symbol_payload,
                "relationships": rel_rows,
                "relationship_count": len(rel_rows),
            }
            evidence = [matched_entry.get("evidence")] if matched_entry and matched_entry.get("evidence") else []
        elif view == "full":
            # M6 contract: full's relationships are the same filtered/packed list as
            # normal now (no more raw, unfiltered edges). data.packet is Phase 2 (M6.1/M6.2).
            composite_data = {
                "status": "resolved",
                "query": query,
                "target_symbol_id": symbol_id,
                "symbol": matched_sym,
                "content": matched_content,
                "relationships": rel_rows,
                "relationship_count": len(rel_rows),
            }
            evidence = ctx_res.get("evidence", [])
        else:  # normal
            normal_sym = {
                "symbol_id": matched_sym.get("symbol_id"),
                "name": matched_sym.get("name"),
                "qualified_name": matched_sym.get("qualified_name"),
                "kind": matched_sym.get("kind"),
                "path": matched_sym.get("path"),
                "signature": matched_sym.get("signature"),
                "start_line": matched_sym.get("start_line"),
                "end_line": matched_sym.get("end_line"),
                "roles": matched_sym.get("roles", []),
            }
            composite_data = {
                "status": "resolved",
                "query": query,
                "target_symbol_id": symbol_id,
                "symbol": normal_sym,
                "content": matched_content,
                "relationships": rel_rows,
                "relationship_count": len(rel_rows),
            }
            evidence = ctx_res.get("evidence", [])

        # M6 contract: distinct from relationships_omitted (budget-driven, below) --
        # this counts edges the resolved/lexical/confidence>=0.5 quality filter excluded.
        composite_data["relationships_filtered"] = relationships_filtered

        if omitted_edge_count > 0:
            composite_data["relationships_omitted"] = omitted_edge_count

        if retry_hint:
            composite_data["retry_hint"] = retry_hint

        ctx_est = ctx_res.get("budget", {}).get("estimated_tokens", 0)
        rel_est = estimate_tokens(json.dumps(rel_rows))
        total_estimated = min(budget_tokens, ctx_est + rel_est)
        is_truncated = bool(ctx_res.get("truncated")) or ("content_omitted_budget" in warnings) or (omitted_edge_count > 0)

        composite_envelope = {
            "schema_version": "1.0",
            "repo_id": repo_id,
            "index_run_id": ctx_res.get("index_run_id"),
            "freshness": ctx_res.get("freshness"),
            "budget": {
                "requested_tokens": budget_tokens,
                "estimated_tokens": total_estimated,
            },
            "truncated": is_truncated,
            "warnings": warnings,
            "evidence": evidence,
            "data": composite_data,
        }
        return composite_envelope

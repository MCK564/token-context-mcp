"""Composite retrieval workflows combining multi-step operations (P2)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from token_context_mcp.retrieve.projection import OutputProjector
from token_context_mcp.retrieve.service import RetrievalError, RetrievalService


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
        budget_tokens = max(256, min(budget_tokens, 8192))
        sub_budget = budget_tokens // 2

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
                {"symbol_id": s.get("symbol_id"), "name": s.get("name"), "kind": s.get("kind"), "path": s.get("path"), "line": s.get("line")}
                for s in symbols[:5]
            ]
            return {
                "schema_version": "1.0",
                "repo_id": repo_id,
                "index_run_id": find_res.get("index_run_id"),
                "freshness": find_res.get("freshness"),
                "data": {
                    "status": "ambiguous",
                    "query": query,
                    "candidate_count": len(symbols),
                    "candidates": candidates,
                    "message": f"Found {len(symbols)} candidate symbols. Specify exact symbol_id.",
                },
            }

        symbol_id = target_sym["symbol_id"]

        # 2. Get symbol context
        include_body = (view != "minimal")
        ctx_res = self.service.symbol_context(
            repo_id=repo_id,
            symbol_id=symbol_id,
            include_body=include_body,
            max_tokens=sub_budget,
        )
        if "error" in ctx_res:
            return ctx_res

        # 3. Get immediate impact slice (depth=1)
        impact_res = self.service.impact_slice(
            repo_id=repo_id,
            symbol_id=symbol_id,
            depth=1,
            max_nodes=20,
            max_tokens=sub_budget,
        )

        edges = impact_res.get("data", {}).get("edges", []) if "data" in impact_res else []

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

        if view == "minimal":
            symbol_payload = {
                "symbol_id": matched_sym.get("symbol_id"),
                "name": matched_sym.get("name"),
                "kind": matched_sym.get("kind"),
                "path": matched_sym.get("path"),
                "start_line": matched_sym.get("start_line"),
                "signature": matched_sym.get("signature"),
            }
            rel_payload = [
                {
                    "source": e.get("source_symbol_id"),
                    "target": e.get("target_symbol_id") or e.get("target_name"),
                    "kind": e.get("edge_kind"),
                    "confidence": e.get("confidence"),
                }
                for e in edges
            ]
            composite_data = {
                "status": "resolved",
                "query": query,
                "target_symbol_id": symbol_id,
                "symbol": symbol_payload,
                "relationships": rel_payload,
                "relationship_count": len(edges),
            }
        elif view == "full":
            composite_data = {
                "status": "resolved",
                "query": query,
                "target_symbol_id": symbol_id,
                "symbol": matched_sym,
                "content": matched_content,
                "relationships": edges,
                "relationship_count": len(edges),
            }
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
                "relationships": edges,
                "relationship_count": len(edges),
            }

        composite_envelope = {
            "schema_version": "1.0",
            "repo_id": repo_id,
            "index_run_id": ctx_res.get("index_run_id"),
            "freshness": ctx_res.get("freshness"),
            "data": composite_data,
        }
        if view == "full":
            if "evidence" in ctx_res:
                composite_envelope["evidence"] = ctx_res["evidence"]
            if "budget" in ctx_res:
                composite_envelope["budget"] = ctx_res["budget"]
            if "truncated" in ctx_res:
                composite_envelope["truncated"] = ctx_res["truncated"]

        return composite_envelope

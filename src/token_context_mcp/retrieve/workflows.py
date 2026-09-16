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
        ctx_res = self.service.symbol_context(
            repo_id=repo_id,
            symbol_id=symbol_id,
            include_body=True,
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

        composite_data = {
            "status": "resolved",
            "query": query,
            "target_symbol_id": symbol_id,
            "symbol": ctx_res.get("data", {}).get("symbol", {}),
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

        # Apply view projection if minimal requested
        if view == "minimal":
            return OutputProjector.project(composite_envelope, view="minimal")
        return composite_envelope

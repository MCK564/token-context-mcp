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

        # 3. Get immediate impact slice
        try:
            slice_tokens = max(edge_budget, 1536) if budget_tokens >= 2048 else edge_budget
            impact_res = self.service.impact_slice(
                repo_id=repo_id,
                symbol_id=symbol_id,
                depth=1,
                max_nodes=20,
                max_tokens=slice_tokens,
            )
        except RetrievalError as err:
            impact_res = {"error": {"code": "budget_exhausted", "message": str(err)}}

        warnings: list[str] = []
        for w in ctx_res.get("warnings", []):
            if w not in warnings:
                warnings.append(w)

        omitted_edge_count = 0
        if "error" in impact_res:
            err_code = impact_res["error"].get("code", "unknown")
            impact_warn = f"impact_unavailable:{err_code}"
            if impact_warn not in warnings:
                warnings.append(impact_warn)
            edges = []
            impact_est = 0
            impact_truncated = False
            try:
                st = self.service._store(repo_id)
                raw_edges = st.edges_from(symbol_id) + st.edges_to(symbol_id)
                omitted_edge_count = len(raw_edges)
            except Exception:
                omitted_edge_count = 0
        else:
            edges = impact_res.get("data", {}).get("edges", [])
            for w in impact_res.get("warnings", []):
                if w not in warnings:
                    warnings.append(w)
            impact_est = impact_res.get("budget", {}).get("estimated_tokens", 0)
            impact_truncated = bool(impact_res.get("truncated"))
            omitted_edge_count = impact_res.get("data", {}).get("omitted_edge_count", 0)
            if not edges and omitted_edge_count == 0:
                try:
                    st = self.service._store(repo_id)
                    raw_edges = st.edges_from(symbol_id) + st.edges_to(symbol_id)
                    if raw_edges:
                        omitted_edge_count = len(raw_edges)
                except Exception:
                    pass


        if omitted_edge_count > 0:
            if "relationships_truncated" not in warnings:
                warnings.append("relationships_truncated")

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

        rel_compact = [
            {
                "source": e.get("source_symbol_id"),
                "target": e.get("target_symbol_id") or e.get("target_name"),
                "kind": e.get("edge_kind"),
                "confidence": e.get("confidence"),
            }
            for e in edges
        ]

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
                "relationships": rel_compact,
                "relationship_count": len(rel_compact),
            }
            evidence = [matched_entry.get("evidence")] if matched_entry and matched_entry.get("evidence") else []
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
                "relationships": rel_compact,
                "relationship_count": len(rel_compact),
            }
            evidence = ctx_res.get("evidence", [])

        if omitted_edge_count > 0:
            composite_data["relationships_omitted"] = omitted_edge_count

        if retry_hint:
            composite_data["retry_hint"] = retry_hint

        ctx_est = ctx_res.get("budget", {}).get("estimated_tokens", 0)
        import json
        from token_context_mcp.retrieve.token_budget import estimate_tokens
        rel_est = estimate_tokens(json.dumps(rel_compact if view != "full" else edges))
        total_estimated = min(budget_tokens, ctx_est + rel_est)
        is_truncated = bool(ctx_res.get("truncated")) or impact_truncated or ("content_omitted_budget" in warnings) or (omitted_edge_count > 0)



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

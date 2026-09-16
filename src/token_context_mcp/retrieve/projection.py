"""Server-side projection and filtering for token efficiency (P1)."""
from __future__ import annotations

from typing import Any, Dict, List, Literal

ViewMode = Literal["minimal", "normal", "full"]


class OutputProjector:
    """Projects retrieval payloads into token-efficient views while preserving mandatory metadata."""

    MANDATORY_ROOT_KEYS = {
        "schema_version",
        "repo_id",
        "index_run_id",
        "freshness",
        "budget",
        "truncated",
        "warnings",
        "evidence",
    }

    @staticmethod
    def project(payload: Dict[str, Any], view: ViewMode = "normal") -> Dict[str, Any]:
        if view == "normal" or view == "full":
            return payload

        # Minimal View projection
        if "error" in payload or "data" not in payload:
            return payload

        projected = {k: v for k, v in payload.items() if k in OutputProjector.MANDATORY_ROOT_KEYS}
        data = payload.get("data", {})

        if not isinstance(data, dict):
            projected["data"] = data
            return projected

        new_data: Dict[str, Any] = {}

        # Project symbols list
        if "symbols" in data and isinstance(data["symbols"], list):
            new_symbols = []
            for item in data["symbols"]:
                if isinstance(item, dict):
                    # Keep concise symbol fields
                    new_symbols.append({
                        "symbol_id": item.get("symbol_id"),
                        "name": item.get("name"),
                        "kind": item.get("kind"),
                        "path": item.get("path"),
                        "line": item.get("line"),
                    })
                else:
                    new_symbols.append(item)
            new_data["symbols"] = new_symbols

        # Project symbol context
        if "symbol" in data and isinstance(data["symbol"], dict):
            sym = data["symbol"]
            new_data["symbol"] = {
                "symbol_id": sym.get("symbol_id"),
                "name": sym.get("name"),
                "kind": sym.get("kind"),
                "path": sym.get("path"),
                "line": sym.get("line"),
                "signature": sym.get("signature"),
            }
            if "body" in sym and sym["body"]:
                # If body is present, keep it in minimal if explicitly fetched
                new_data["symbol"]["body"] = sym["body"]

        # Project edges / impact slices
        if "edges" in data and isinstance(data["edges"], list):
            new_edges = []
            for edge in data["edges"]:
                if isinstance(edge, dict):
                    new_edges.append({
                        "source": edge.get("source"),
                        "target": edge.get("target"),
                        "relation": edge.get("relation"),
                    })
                elif isinstance(edge, (list, tuple)) and len(edge) >= 3:
                    new_edges.append(edge[:3])
                else:
                    new_edges.append(edge)
            new_data["edges"] = new_edges

        # Preserve query, focus, summary counts
        for key in ("query", "pattern", "focus_symbol_id", "total_symbols", "returned_count", "depth"):
            if key in data:
                new_data[key] = data[key]

        # Preserve remaining scalar keys
        for k, v in data.items():
            if k not in new_data and isinstance(v, (int, float, str, bool)):
                new_data[k] = v

        projected["data"] = new_data
        return projected

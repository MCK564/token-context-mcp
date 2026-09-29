"""Small pure helpers shared by the indexer (which stores them in the manifest) and the retrieval service."""
from __future__ import annotations

from typing import Any

from token_context_mcp.models import EdgeRecord


def edge_precision(edges: list[EdgeRecord]) -> dict[str, Any]:
    """Share of ambiguous / resolved edges among all observed edges."""
    if not edges:
        return {
            "ambiguous_rate": None,
            "resolved_rate": None,
            "basis": "no_edges_observed",
        }
    total = len(edges)
    return {
        "ambiguous_rate": round(sum(edge.status == "ambiguous" for edge in edges) / total, 3),
        "resolved_rate": round(sum(edge.status == "resolved" for edge in edges) / total, 3),
        "basis": "edge_status / observed_edges",
    }


def version_tuple(value: object) -> tuple[int, ...]:
    """``"2.10"`` -> ``(2, 10)``: schema versions compare numerically per component, never as strings."""
    parts: list[int] = []
    for piece in str(value).split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            digits = "".join(ch for ch in piece if ch.isdigit())
            parts.append(int(digits) if digits else 0)
    return tuple(parts)

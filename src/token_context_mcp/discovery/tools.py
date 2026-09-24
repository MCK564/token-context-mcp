"""Implementation of meta-tools for smart tool discovery."""
from __future__ import annotations

import re
from typing import Any

from token_context_mcp.discovery.catalog import TOOL_CATALOG, ToolMeta


def list_available_tools(category: str | None = None) -> dict[str, Any]:
    """Return compact catalog of available tools grouped by category."""
    categories: dict[str, list[dict[str, Any]]] = {}
    for name, meta in TOOL_CATALOG.items():
        if category and meta.category != category:
            continue
        categories.setdefault(meta.category, []).append(
            {
                "name": name,
                "summary": meta.summary,
                "parameters": meta.parameters_summary,
            }
        )

    return {
        "status": "success",
        "category_filter": category,
        "total_tools": sum(len(items) for items in categories.values()),
        "categories": categories,
    }


def search_tools(query: str, limit: int = 3) -> dict[str, Any]:
    """Smart keyword and semantic token overlap search over tool capabilities."""
    query_tokens = set(re.findall(r"\w+", query.lower()))
    scored: list[tuple[float, ToolMeta]] = []

    for meta in TOOL_CATALOG.values():
        score = 0.0
        # Check direct name match
        if meta.name.lower() in query.lower():
            score += 5.0
        # Check name token overlap
        name_tokens = set(meta.name.lower().split("_"))
        score += len(query_tokens & name_tokens) * 2.0
        # Check tag overlap
        tag_tokens = set(meta.tags)
        score += len(query_tokens & tag_tokens) * 1.5
        # Check summary overlap
        summary_tokens = set(re.findall(r"\w+", meta.summary.lower()))
        score += len(query_tokens & summary_tokens) * 1.0

        if score > 0:
            scored.append((score, meta))

    scored.sort(key=lambda item: item[0], reverse=True)
    results = [
        {
            "name": meta.name,
            "category": meta.category,
            "relevance_score": round(score, 2),
            "summary": meta.summary,
            "quick_parameters": meta.parameters_summary,
        }
        for score, meta in scored[:limit]
    ]

    return {
        "query": query,
        "matches_found": len(results),
        "tools": results,
    }


def get_tool_schema(tool_name: str, schema_dict: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return detailed tool schema on demand."""
    meta = TOOL_CATALOG.get(tool_name)
    if meta is None:
        return {
            "status": "not_found",
            "error": f"Tool '{tool_name}' not found in catalog.",
            "available_tools": list(TOOL_CATALOG.keys()),
        }

    schema = (schema_dict or {}).get(tool_name, {})
    return {
        "status": "success",
        "tool_name": meta.name,
        "category": meta.category,
        "summary": meta.summary,
        "parameters_summary": meta.parameters_summary,
        "schema": schema,
    }

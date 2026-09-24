from __future__ import annotations

from token_context_mcp.discovery.catalog import TOOL_CATALOG
from token_context_mcp.discovery.tools import get_tool_schema, list_available_tools, search_tools


def test_list_available_tools_contains_categories() -> None:
    catalog = list_available_tools()
    assert catalog["status"] == "success"
    assert catalog["total_tools"] == len(TOOL_CATALOG)
    assert catalog["total_tools"] >= 19
    assert "code_navigation" in catalog["categories"]
    assert "impact_analysis" in catalog["categories"]
    assert "shared_memory" in catalog["categories"]


def test_list_available_tools_with_category_filter() -> None:
    filtered = list_available_tools(category="shared_memory")
    assert filtered["category_filter"] == "shared_memory"
    assert "shared_memory" in filtered["categories"]
    assert "code_navigation" not in filtered["categories"]
    assert len(filtered["categories"]["shared_memory"]) >= 5


def test_search_tools_finds_relevant_tools() -> None:
    results = search_tools("who calls this function callers impact slice", limit=3)
    assert results["matches_found"] > 0
    names = [t["name"] for t in results["tools"]]
    assert any(name in {"get_impact_slice", "get_module_dependents", "inspect_symbol"} for name in names)
    # Verify tool chaining metadata is included
    first_tool = results["tools"][0]
    assert "recommended_followups" in first_tool
    assert "prerequisites" in first_tool


def test_search_tools_memory_intent() -> None:
    results = search_tools("store state or checkpoint for multi-agent", limit=2)
    assert results["matches_found"] > 0
    names = [t["name"] for t in results["tools"]]
    assert "memory_put" in names or "memory_lock" in names


def test_get_tool_schema_returns_spec() -> None:
    schema = get_tool_schema("get_impact_slice")
    assert schema["status"] == "success"
    assert schema["tool_name"] == "get_impact_slice"
    assert "parameters_summary" in schema
    assert "symbol_id" in schema["parameters_summary"]
    assert "recommended_followups" in schema
    assert "prerequisites" in schema


def test_get_tool_schema_unknown_tool() -> None:
    schema = get_tool_schema("non_existent_tool_xyz")
    assert schema["status"] == "not_found"

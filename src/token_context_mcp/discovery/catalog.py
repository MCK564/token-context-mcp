"""Catalog of tools, categories, and concise metadata for smart tool discovery.
Includes tool chaining and prerequisite declarations learned from Google Cloud GenAI A2A protocols.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolMeta:
    name: str
    category: str
    summary: str
    parameters_summary: dict[str, str]
    tags: list[str]
    recommended_followups: list[str] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)


TOOL_CATALOG: dict[str, ToolMeta] = {
    "list_repositories": ToolMeta(
        name="list_repositories",
        category="repository_admin",
        summary="List all registered repository IDs without exposing filesystem roots.",
        parameters_summary={},
        tags=["admin", "repos", "list", "registry"],
        recommended_followups=["get_repo_map", "get_index_status"],
    ),
    "get_index_status": ToolMeta(
        name="get_index_status",
        category="repository_admin",
        summary="Active snapshot metadata, freshness, file/symbol counts, and ambiguous edge rate.",
        parameters_summary={"repo_id": "string (required)"},
        tags=["status", "freshness", "metrics", "snapshot"],
        prerequisites=["list_repositories"],
    ),
    "get_repo_map": ToolMeta(
        name="get_repo_map",
        category="code_navigation",
        summary="Token-budgeted, PageRank-ordered symbols for orientation within a repository.",
        parameters_summary={
            "repo_id": "string (required)",
            "budget_tokens": "integer (optional)",
            "format": "compact | full",
            "profile": "locate | orient | impact | read",
        },
        tags=["map", "overview", "symbols", "pagerank", "budget"],
        recommended_followups=["find_symbols", "get_file_skeleton"],
        prerequisites=["list_repositories"],
    ),
    "find_symbols": ToolMeta(
        name="find_symbols",
        category="code_navigation",
        summary="Find source-backed symbols by name or qualified-name pattern (exact/wildcard).",
        parameters_summary={
            "repo_id": "string (required)",
            "pattern": "string (required)",
            "kind": "function | class | method (optional)",
            "limit": "integer (optional)",
        },
        tags=["symbols", "find", "search", "name", "definition"],
        recommended_followups=["inspect_symbol", "get_symbol_context", "get_impact_slice"],
        prerequisites=["list_repositories"],
    ),
    "search_source": ToolMeta(
        name="search_source",
        category="code_navigation",
        summary="Full-text FTS5 search across symbol bodies and source code, returning line spans and IDs.",
        parameters_summary={
            "repo_id": "string (required)",
            "query": "string (required)",
            "limit": "integer (optional)",
            "max_tokens": "integer (optional)",
        },
        tags=["search", "grep", "text", "body", "fts5", "ripgrep"],
        recommended_followups=["get_symbol_context", "get_file_skeleton"],
        prerequisites=["list_repositories"],
    ),
    "get_file_skeleton": ToolMeta(
        name="get_file_skeleton",
        category="code_navigation",
        summary="Public interface, imports, and source-backed signatures from a single file (elides bodies).",
        parameters_summary={
            "repo_id": "string (required)",
            "path": "string (required)",
            "include_private": "boolean (optional)",
        },
        tags=["skeleton", "outline", "file", "signatures", "imports"],
        recommended_followups=["get_symbol_context", "inspect_symbol"],
        prerequisites=["list_repositories"],
    ),
    "get_symbol_context": ToolMeta(
        name="get_symbol_context",
        category="impact_analysis",
        summary="Bounded source packet, definition, and immediate graph neighborhood for a symbol.",
        parameters_summary={
            "repo_id": "string (required)",
            "symbol_id": "string (required)",
            "depth": "integer (0-3)",
            "include_body": "boolean (optional)",
        },
        tags=["symbol", "context", "definition", "neighborhood"],
        recommended_followups=["get_impact_slice", "sample_summarize"],
        prerequisites=["find_symbols"],
    ),
    "get_impact_slice": ToolMeta(
        name="get_impact_slice",
        category="impact_analysis",
        summary="Traverse observed caller/callee AST edges from a symbol with confidence filtering.",
        parameters_summary={
            "repo_id": "string (required)",
            "symbol_id": "string (required)",
            "direction": "callers | callees | both",
            "depth": "integer (0-3)",
            "filter_ambiguous": "boolean (default: true)",
            "min_confidence": "float (optional, e.g. 0.5)",
        },
        tags=["impact", "callers", "callees", "graph", "blast_radius", "dependencies"],
        recommended_followups=["sample_summarize", "memory_put"],
        prerequisites=["find_symbols"],
    ),
    "get_module_dependents": ToolMeta(
        name="get_module_dependents",
        category="impact_analysis",
        summary="Parsed import relationships for an indexed path or module (importers and imported modules).",
        parameters_summary={
            "repo_id": "string (required)",
            "module": "string (module name or relative path)",
        },
        tags=["imports", "modules", "dependents", "architecture"],
        recommended_followups=["get_file_skeleton"],
        prerequisites=["list_repositories"],
    ),
    "inspect_symbol": ToolMeta(
        name="inspect_symbol",
        category="impact_analysis",
        summary="Composite 1-turn tool: resolves symbol, retrieves definition, and returns immediate impact graph.",
        parameters_summary={
            "repo_id": "string (required)",
            "query": "string (required)",
            "view": "minimal | normal | full",
            "budget_tokens": "integer (default: 2048)",
        },
        tags=["composite", "fast", "resolve", "context", "inspect"],
        recommended_followups=["sample_summarize", "memory_put"],
        prerequisites=["list_repositories"],
    ),
    "list_available_tools": ToolMeta(
        name="list_available_tools",
        category="tool_discovery",
        summary="Compact catalog of available tools grouped by category (consumes minimal tokens).",
        parameters_summary={"category": "string (optional)"},
        tags=["tools", "discovery", "list", "meta"],
        recommended_followups=["search_tools", "get_tool_schema"],
    ),
    "search_tools": ToolMeta(
        name="search_tools",
        category="tool_discovery",
        summary="Smart semantic/keyword search over tool capabilities to find the right tool for an intent.",
        parameters_summary={"query": "string (required)", "limit": "integer (default: 3)"},
        tags=["tools", "search", "intent", "discovery", "recommend"],
        recommended_followups=["get_tool_schema"],
    ),
    "get_tool_schema": ToolMeta(
        name="get_tool_schema",
        category="tool_discovery",
        summary="Retrieve detailed JSON schema and argument specifications for a specific tool on demand.",
        parameters_summary={"tool_name": "string (required)"},
        tags=["tools", "schema", "spec", "parameters"],
    ),
    "memory_put": ToolMeta(
        name="memory_put",
        category="shared_memory",
        summary="Store state, execution checkpoint, or cross-agent artifact in shared persistent memory.",
        parameters_summary={
            "key": "string (required)",
            "value": "any (required, string or JSON object)",
            "scope": "session | project | global",
            "ttl": "integer (seconds, optional)",
        },
        tags=["memory", "state", "shared", "checkpoint", "cache"],
        recommended_followups=["memory_consolidate", "memory_get"],
    ),
    "memory_get": ToolMeta(
        name="memory_get",
        category="shared_memory",
        summary="Retrieve a stored value or execution checkpoint from shared memory without prompt bloat.",
        parameters_summary={
            "key": "string (required)",
            "scope": "session | project | global",
        },
        tags=["memory", "state", "get", "read", "checkpoint"],
        prerequisites=["memory_put"],
    ),
    "memory_search": ToolMeta(
        name="memory_search",
        category="shared_memory",
        summary="Full-text search over shared memory entries and stored artifacts.",
        parameters_summary={
            "query": "string (required)",
            "scope": "session | project | global (optional)",
            "limit": "integer (default: 5)",
        },
        tags=["memory", "search", "artifacts", "state", "find"],
    ),
    "memory_lock": ToolMeta(
        name="memory_lock",
        category="shared_memory",
        summary="Acquire a timed mutex lock on a resource to coordinate multi-agent actions without collisions.",
        parameters_summary={
            "resource_key": "string (required)",
            "agent_id": "string (required)",
            "timeout_sec": "integer (default: 60)",
        },
        tags=["memory", "lock", "mutex", "concurrency", "multi_agent"],
    ),
    "memory_consolidate": ToolMeta(
        name="memory_consolidate",
        category="shared_memory",
        summary="Consolidate and synthesize scattered memory checkpoints into high-level architectural insights (learned from Google Always-On Memory Agent).",
        parameters_summary={
            "scope": "session | project | global (default: session)",
            "target_key": "string (default: project_architectural_insights)",
            "prune_transient": "boolean (default: false)",
        },
        tags=["memory", "consolidate", "synthesis", "insights", "prune"],
        recommended_followups=["memory_get", "memory_search"],
        prerequisites=["memory_put"],
    ),
    "sample_summarize": ToolMeta(
        name="sample_summarize",
        category="sampling_inference",
        summary="Hardware-aware context compressor/summarizer: compresses large outputs into concise JSON.",
        parameters_summary={
            "text": "string (required)",
            "intent": "string (optional)",
            "max_tokens": "integer (default: 512)",
            "target_symbols": "array of strings (optional)",
        },
        tags=["sampling", "compress", "summarize", "llm", "nested"],
        recommended_followups=["memory_put"],
    ),
}

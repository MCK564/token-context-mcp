from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from token_context_mcp.client_profile import apply_schema_profile

ADMIN_TOOLS: frozenset[str] = frozenset({"agent_control", "audit_logs"})

MUTATING_TOOLS: frozenset[str] = frozenset({
    "memory_put",
    "memory_lock",
    "memory_unlock",
    "memory_consolidate",
    "sample_summarize",
    "agent_control",
})

EXTENSION_TOOLS: frozenset[str] = frozenset({
    "list_available_tools",
    "search_tools",
    "get_tool_schema",
    "memory_put",
    "memory_get",
    "memory_search",
    "memory_lock",
    "memory_unlock",
    "memory_consolidate",
    "sample_summarize",
    "agent_control",
    "audit_logs",
})


@dataclass(frozen=True)
class ToolSpec:
    """Canonical Single-Source-of-Truth definition for an MCP tool.
    
    Eliminates duplicated metadata across discovery/catalog.py, server.py,
    and schema profiles conforming to DeepSeek Harness Plugin Specification.
    """
    name: str
    title: str
    description: str
    category: str
    is_mutating: bool = False
    requires_admin: bool = False
    requires_extensions: bool = False
    input_schema: dict[str, Any] = field(default_factory=dict)
    handler: Callable[..., Any] = field(default=lambda **kw: {})


class ToolRegistry:
    """Thread-safe registry of all available ToolSpecs in the system."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list_specs(
        self,
        enable_extensions: bool = False,
        enable_admin: bool = False,
    ) -> list[ToolSpec]:
        """Return registered ToolSpecs matching active capability flags."""
        result = []
        for spec in self._tools.values():
            if spec.requires_extensions and not enable_extensions:
                continue
            if spec.requires_admin and not (enable_extensions and enable_admin):
                continue
            result.append(spec)
        return result

    def get_profiled_schemas(
        self,
        schema_profile: str = "default",
        enable_extensions: bool = False,
        enable_admin: bool = False,
    ) -> dict[str, dict[str, Any]]:
        """Return name-to-input_schema mapping rewritten for the active client profile."""
        specs = self.list_specs(enable_extensions=enable_extensions, enable_admin=enable_admin)
        result = {}
        for spec in specs:
            schema = spec.input_schema
            if schema_profile != "default":
                schema = apply_schema_profile(schema, schema_profile, spec.name)
            result[spec.name] = schema
        return result


def build_default_registry(catalog: dict[str, Any] | None = None) -> ToolRegistry:
    """Instantiate and populate the canonical ToolRegistry from TOOL_CATALOG."""
    from token_context_mcp.discovery.catalog import TOOL_CATALOG

    active_catalog = catalog if catalog is not None else TOOL_CATALOG
    registry = ToolRegistry()

    for name, meta in active_catalog.items():
        spec = ToolSpec(
            name=name,
            title=getattr(meta, "name", name).replace("_", " ").title(),
            description=getattr(meta, "summary", ""),
            category=getattr(meta, "category", "general"),
            is_mutating=name in MUTATING_TOOLS,
            requires_admin=name in ADMIN_TOOLS,
            requires_extensions=name in EXTENSION_TOOLS,
        )
        registry.register(spec)

    return registry

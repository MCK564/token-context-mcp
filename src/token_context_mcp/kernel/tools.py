from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from token_context_mcp.client_profile import apply_schema_profile


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

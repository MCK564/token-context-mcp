"""Single import point for MCP SDK result types (M9.1).

The 2.x SDK defines its wire types in the ``mcp-types`` distribution and re-exports them from ``mcp.types``.
Both names resolve to the same classes today; importing from here keeps the server and the result finalizer
on one spelling, so a future SDK split cannot leave them constructing and returning different classes.
"""
from __future__ import annotations

from mcp_types import CallToolResult, TextContent, Tool

__all__ = ["CallToolResult", "TextContent", "Tool"]

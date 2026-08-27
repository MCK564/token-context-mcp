from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

from token_context_mcp.server import build_server


def test_server_exports_only_read_tools(indexed_config: Path) -> None:
    server = build_server(indexed_config)
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == {
        "get_repo_map",
        "find_symbols",
        "get_file_skeleton",
        "get_symbol_context",
        "get_impact_slice",
        "get_index_status",
    }
    result = asyncio.run(server.call_tool("get_index_status", {"repo_id": "demo"}))
    assert result.structured_content["repo_id"] == "demo"
    skeleton = asyncio.run(server.call_tool("get_file_skeleton", {"repo_id": "demo", "path": ".env"}))
    assert skeleton.structured_content["error"]["code"] == "invalid_request"
    assert "canary" not in str(skeleton.structured_content)
    for tool in tools:
        assert "command" not in tool.input_schema.get("properties", {})
        assert "write" not in tool.input_schema.get("properties", {})


def test_stdio_server_round_trip(indexed_config: Path) -> None:
    async def run() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "token_context_mcp", "serve", "--config", str(indexed_config)],
        )
        async with Client(stdio_client(parameters)) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools.tools} >= {"get_repo_map", "get_index_status"}
            result = await client.call_tool("get_index_status", {"repo_id": "demo"})
            assert result.structured_content["repo_id"] == "demo"

    asyncio.run(run())

"""Contract tests for MCP ``outputSchema`` advertising and runtime validation across all 23 tools."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from mcp import Client
from mcp_types import Implementation

from token_context_mcp.output_schemas import TOOL_OUTPUT_SCHEMAS
from token_context_mcp.server import build_server


def test_all_output_schemas_are_valid_draft_2020_12() -> None:
    assert len(TOOL_OUTPUT_SCHEMAS) == 23
    for name, schema in TOOL_OUTPUT_SCHEMAS.items():
        assert schema.get("type") == "object", f"{name} outputSchema root must be object"
        Draft202012Validator.check_schema(schema)


def test_output_schema_advertised_by_output_mode_and_client(indexed_config: Path) -> None:
    async def run() -> None:
        # 1. Default structured mode (e.g. Glama / standard MCP clients): all 23 tools have outputSchema
        srv_struct = build_server(indexed_config, enable_extensions=True, enable_admin_tools=True)
        async with Client(srv_struct, client_info=Implementation(name="glama-inspector", version="1.0")) as client:
            tools = (await client.list_tools()).tools
            assert len(tools) == 23
            for t in tools:
                assert t.output_schema is not None, f"{t.name} missing outputSchema in structured mode"
                assert t.annotations is not None, f"{t.name} missing ToolAnnotations"
                assert 0 < len(t.description or "") <= 200, f"{t.name} description length out of range"
                for prop_name, prop_schema in t.input_schema.get("properties", {}).items():
                    assert prop_schema.get("description"), f"{t.name}.{prop_name} missing description"

        # 2. Text / compact_text mode / Gemini auto mode: outputSchema omitted so ClientSession never expects structured_content
        for mode, cname in (("text", "claude-code"), ("compact_text", "claude-code"), ("auto", "Antigravity-IDE")):
            srv_text = build_server(
                indexed_config,
                enable_extensions=True,
                enable_admin_tools=True,
                output_mode=mode,
            )
            async with Client(srv_text, client_info=Implementation(name=cname, version="1.0")) as client:
                tools = (await client.list_tools()).tools
                assert len(tools) == 23
                assert all(t.output_schema is None for t in tools)
                res = await client.call_tool("get_index_status", {"repo_id": "demo"})
                assert res.structured_content is None

    asyncio.run(run())


def test_all_23_tools_validate_against_output_schema_over_mcp_client(indexed_config: Path) -> None:
    async def run() -> None:
        server = build_server(indexed_config, enable_extensions=True, enable_admin_tools=True)
        async with Client(server, client_info=Implementation(name="claude-code", version="1.0")) as client:
            listed = await client.list_tools()
            assert len(listed.tools) == 23

            # Calling via ClientSession automatically runs validate_tool_result against each tool's outputSchema.
            await client.call_tool("list_repositories", {})
            await client.call_tool("get_index_status", {"repo_id": "demo"})
            await client.call_tool("get_repo_map", {"repo_id": "demo", "budget_tokens": 512})
            find_res = await client.call_tool("find_symbols", {"repo_id": "demo", "pattern": "alpha"})
            alpha_id = find_res.structured_content["data"]["symbols"][0]["symbol_id"]
            await client.call_tool("search_source", {"repo_id": "demo", "query": "beta"})
            await client.call_tool("get_file_skeleton", {"repo_id": "demo", "path": "app.py"})
            await client.call_tool("get_module_dependents", {"repo_id": "demo", "path": "app.py"})
            await client.call_tool("get_symbol_context", {"repo_id": "demo", "symbol_id": alpha_id})
            await client.call_tool("get_impact_slice", {"repo_id": "demo", "symbol_id": alpha_id})
            await client.call_tool("inspect_symbol", {"repo_id": "demo", "query": "alpha", "view": "full"})

            # Smart discovery
            await client.call_tool("list_available_tools", {})
            await client.call_tool("search_tools", {"query": "impact slice"})
            await client.call_tool("get_tool_schema", {"tool_name": "get_impact_slice"})
            await client.call_tool("get_tool_schema", {"tool_name": "nonexistent_tool"})

            # Memory & locks
            await client.call_tool("memory_put", {"key": "k1", "value": {"a": 1}, "scope": "session"})
            await client.call_tool("memory_get", {"key": "k1", "scope": "session"})
            await client.call_tool("memory_get", {"key": "missing", "scope": "session"})
            await client.call_tool("memory_search", {"query": "k1"})
            await client.call_tool("memory_lock", {"resource_key": "r1", "agent_id": "worker-1"})
            await client.call_tool("memory_lock", {"resource_key": "r1", "agent_id": "worker-2"})
            await client.call_tool("memory_unlock", {"resource_key": "r1", "agent_id": "worker-1"})
            await client.call_tool("memory_consolidate", {"scope": "session"})

            # Sampling & ledger
            await client.call_tool("sample_summarize", {"text": "def alpha(x):\n    return x\n"})
            await client.call_tool(
                "trajectory_record",
                {"repo_id": "demo", "query": "how does alpha work", "answers": [f"{alpha_id}@4"]},
            )

            # Admin tools
            await client.call_tool("agent_control", {"action": "status"})
            await client.call_tool("audit_logs", {"limit": 5})

            # Structured error payloads must also validate cleanly against outputSchema
            err_repo = await client.call_tool("get_index_status", {"repo_id": "unknown-repo"})
            assert err_repo.structured_content["error"]["code"] == "unknown_repo_id"
            err_mod = await client.call_tool("get_module_dependents", {"repo_id": "demo"})
            assert "error" in err_mod.structured_content
            err_admin = await client.call_tool("agent_control", {"action": "pause", "agent_id": "worker-1"})
            assert err_admin.structured_content["error"]["code"] == "permission_revoked"

    asyncio.run(run())

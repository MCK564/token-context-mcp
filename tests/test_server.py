from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

from token_context_mcp.config import load_config
from token_context_mcp.server import build_server


def test_server_exports_only_read_tools(indexed_config: Path) -> None:
    server = build_server(indexed_config)
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == {
        "list_repositories",
        "get_repo_map",
        "find_symbols",
        "get_module_dependents",
        "search_source",
        "get_file_skeleton",
        "get_symbol_context",
        "get_impact_slice",
        "get_index_status",
    }
    result = asyncio.run(server.call_tool("get_index_status", {"repo_id": "demo"}))
    assert result.structured_content["repo_id"] == "demo"
    assert len(result.content) == 1
    assert result.content[0].text.startswith("repo_id=demo freshness=fresh")
    assert "index_run_id" not in result.content[0].text
    repositories = asyncio.run(server.call_tool("list_repositories", {}))
    assert repositories.structured_content["repo_ids"] == ["demo"]
    assert str(load_config(indexed_config).repositories["demo"].root) not in str(repositories.structured_content)
    skeleton = asyncio.run(server.call_tool("get_file_skeleton", {"repo_id": "demo", "path": ".env"}))
    assert skeleton.structured_content["error"]["code"] == "policy_rejected"
    assert "canary" not in str(skeleton.structured_content)
    unknown = asyncio.run(server.call_tool("get_index_status", {"repo_id": "D:\\AI\\bench\\invoice-scanner"}))
    assert unknown.structured_content["error"]["code"] == "unknown_repo_id"
    assert "list_repositories" in unknown.structured_content["error"]["message"]
    budget = asyncio.run(server.call_tool("get_repo_map", {"repo_id": "demo", "budget_tokens": 9999}))
    assert budget.structured_content["error"] == {
        "code": "budget_out_of_range",
        "message": "budget_tokens must be between 32 and 8192 tokens",
        "details": {"minimum_tokens": 32, "maximum_tokens": 8192},
    }
    alpha = asyncio.run(server.call_tool("find_symbols", {"repo_id": "demo", "pattern": "alpha"}))
    symbol_id = alpha.structured_content["data"]["symbols"][0]["symbol_id"]
    depth = asyncio.run(
        server.call_tool("get_impact_slice", {"repo_id": "demo", "symbol_id": symbol_id, "depth": 4})
    )
    assert depth.structured_content["error"] == {
        "code": "argument_out_of_range",
        "message": "depth must be between 0 and 3",
        "details": {"field": "depth", "minimum": 0, "maximum": 3},
    }
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
            assert len(result.content) == 1
            assert result.content[0].text.startswith("repo_id=demo freshness=fresh")
            assert "index_run_id" not in result.content[0].text

    asyncio.run(run())


def test_tool_result_keeps_structured_payload_out_of_content(indexed_config: Path) -> None:
    server = build_server(indexed_config)
    result = asyncio.run(server.call_tool("get_repo_map", {"repo_id": "demo", "budget_tokens": 1024}))
    assert result.structured_content["data"]["symbols"]
    summary = result.content[0].text
    assert len(summary) < 200
    assert '"symbols"' not in summary
    assert '"structured_content"' not in summary


def test_cli_module_entrypoint_executes_command(tmp_path: Path, sample_repo: Path) -> None:
    config_path = tmp_path / "repos.toml"
    project_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(project_root / "src")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "token_context_mcp.cli",
            "register",
            "--repo-id",
            "demo",
            "--root",
            str(sample_repo),
            "--config",
            str(config_path),
        ],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

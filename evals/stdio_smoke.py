"""Clean-room smoke test for the installed token-context console script."""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client


def _console_script() -> str:
    command = shutil.which("token-context")
    if command:
        return command
    environment = Path(sys.executable).parent
    candidates = (
        environment / "token-context.exe",
        environment / "token-context",
    )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise RuntimeError("installed token-context console script was not found")


CORE_TOOLS = {
    "list_repositories",
    "get_repo_map",
    "find_symbols",
    "get_module_dependents",
    "search_source",
    "get_file_skeleton",
    "get_symbol_context",
    "get_impact_slice",
    "get_index_status",
    "inspect_symbol",
}

EXTENDED_TOOLS = CORE_TOOLS | {
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
}


async def _run() -> None:
    command = _console_script()
    with tempfile.TemporaryDirectory(prefix="token-context-smoke-") as directory:
        config = Path(directory) / "repos.toml"
        parameters = StdioServerParameters(
            command=command,
            args=["serve", "--transport", "stdio", "--config", str(config)],
        )
        async with Client(stdio_client(parameters)) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            if names not in (CORE_TOOLS, EXTENDED_TOOLS):
                raise AssertionError(
                    f"expected 10 core tools or 20 extended tools, got {len(names)}: {sorted(names)}"
                )

    # F0: Verify search_source via real stdio server with query 1
    params_default = StdioServerParameters(
        command=command,
        args=["serve", "--transport", "stdio"],
    )
    async with Client(stdio_client(params_default)) as client:
        res = await client.call_tool(
            "search_source",
            {"repo_id": "token-context", "query": "sqlite read behind key value lookup tool"},
        )
        if res.is_error:
            raise AssertionError(f"search_source returned error: {res.content}")
        payload = getattr(res, "structured_content", None)
        if not payload and res.content and hasattr(res.content[0], "text"):
            try:
                payload = json.loads(res.content[0].text)
            except Exception:
                pass
        if not isinstance(payload, dict):
            raise AssertionError("search_source did not return structured payload")
        matches = payload.get("data", {}).get("matches", [])
        if len(matches) < 1:
            raise AssertionError(f"expected >= 1 match for search_source, got {len(matches)}")
        sids = [m["symbol_id"] for m in matches if m.get("symbol_id")]
        if len(sids) != len(set(sids)):
            raise AssertionError(f"duplicate symbol_id detected in search_source results: {sids}")
        for idx, m in enumerate(matches):
            if "lines" not in m or not isinstance(m["lines"], list):
                raise AssertionError(f"match {idx} missing 'lines' list: {m}")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()

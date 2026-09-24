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
                    f"expected 10 core tools or 19 extended tools, got {len(names)}: {sorted(names)}"
                )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()

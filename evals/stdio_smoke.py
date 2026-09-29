"""Clean-room smoke test for the installed token-context console script."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
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


async def _run(output_mode: str) -> None:
    command = _console_script()
    with tempfile.TemporaryDirectory(prefix="token-context-smoke-") as directory:
        config = Path(directory) / "repos.toml"
        parameters = StdioServerParameters(
            command=command,
            args=["serve", "--transport", "stdio", "--config", str(config), "--output-mode", output_mode],
        )
        async with Client(stdio_client(parameters)) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            if names not in (CORE_TOOLS, EXTENDED_TOOLS):
                raise AssertionError(
                    f"expected 10 core tools or 20 extended tools, got {len(names)}: {sorted(names)}"
                )

        # F0 / M5: exercise search_source end-to-end through the real stdio server on a clean-room
        # repo. Query words never co-occur in one symbol, so this passes only when the OR top-up,
        # one-entry-per-symbol and `lines` contract are live in the server process.
        root = Path(directory) / "smoke-repo"
        root.mkdir()
        (root / "store.py").write_text(
            "def read_row(key):\n    return lookup_value(key)\n\n\n"
            "def lookup_value(key):\n    return {'value': key}\n\n\n"
            "def write_row(key, value):\n    return (key, value)\n",
            encoding="utf-8",
        )
        config.write_text(
            "[server]\nmax_result_tokens = 8192\n\n[repos.smoke]\n"
            f"root = {json.dumps(str(root.resolve()))}\n",
            encoding="utf-8",
        )
        subprocess.run(
            [command, "index", "--repo-id", "smoke", "--config", str(config)],
            check=True,
            capture_output=True,
        )
        async with Client(stdio_client(parameters)) as client:
            for expand in ("none", "graph"):
                res = await client.call_tool(
                    "search_source",
                    {"repo_id": "smoke", "query": "sqlite read behind key value lookup tool", "expand": expand},
                )
                if res.is_error:
                    raise AssertionError(f"search_source returned error: {res.content}")
                payload = getattr(res, "structured_content", None)
                if (payload is not None) != (output_mode == "structured"):
                    raise AssertionError(f"output_mode={output_mode}: unexpected structured_content={payload is not None}")
                if not payload and res.content and hasattr(res.content[0], "text"):
                    try:
                        payload = json.loads(res.content[0].text)
                    except ValueError:
                        payload = None
                if not isinstance(payload, dict):
                    raise AssertionError("search_source did not return a structured payload")
                data = payload.get("data", {})
                matches = data.get("matches", [])
                if len(matches) < 1:
                    raise AssertionError(f"expected >= 1 match for search_source, got {len(matches)}")
                sids = [m["symbol_id"] for m in matches if m.get("symbol_id")]
                if len(sids) != len(set(sids)):
                    raise AssertionError(f"duplicate symbol_id in search_source results: {sids}")
                for idx, m in enumerate(matches):
                    if not isinstance(m.get("lines"), list):
                        raise AssertionError(f"match {idx} missing 'lines' list: {m}")
                if expand == "graph" and "neighbors" not in data:
                    raise AssertionError("expand='graph' response has no 'neighbors' field")
                if expand == "none" and "neighbors" in data:
                    raise AssertionError("expand='none' response must not carry 'neighbors'")


def main() -> None:
    # M9.2: the payload must arrive whether the server sends it as structuredContent or as JSON text.
    for output_mode in ("structured", "text"):
        asyncio.run(_run(output_mode))
        print(f"stdio_smoke ok: output_mode={output_mode}")


if __name__ == "__main__":
    main()

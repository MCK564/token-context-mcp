"""Measure token cost of MCP Tool Schemas and Instructions (P0)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from token_context_mcp.config import default_config_path
from token_context_mcp.retrieve.token_budget import estimate_tokens
from token_context_mcp.server import build_server


def measure_schema_cost(config_path: Path | None = None) -> dict[str, Any]:
    cfg_p = config_path or default_config_path()
    server = build_server(cfg_p)

    tools = asyncio.run(server.list_tools())

    tool_metrics = []
    total_schema_chars = 0
    total_schema_tokens = 0

    for tool in tools:
        t_dict = tool.model_dump(mode="json", by_alias=True)
        serialized = json.dumps(t_dict, indent=2, ensure_ascii=False)
        t_tokens = estimate_tokens(serialized)
        t_chars = len(serialized)

        total_schema_chars += t_chars
        total_schema_tokens += t_tokens

        tool_metrics.append({
            "name": tool.name,
            "description_chars": len(tool.description or ""),
            "schema_chars": t_chars,
            "schema_tokens": t_tokens,
        })

    # Measure server instructions
    instructions_text = getattr(server, "instructions", "") or ""
    instructions_tokens = estimate_tokens(instructions_text)

    grand_total_tokens = total_schema_tokens + instructions_tokens

    return {
        "tool_count": len(tools),
        "instructions_chars": len(instructions_text),
        "instructions_tokens": instructions_tokens,
        "total_tool_schema_tokens": total_schema_tokens,
        "grand_total_tokens": grand_total_tokens,
        "tools": tool_metrics,
    }


def main() -> None:
    metrics = measure_schema_cost()
    print("=== MCP Tool Schema Cost Benchmark ===")
    print(f"Total Tools: {metrics['tool_count']}")
    print(f"Instructions: {metrics['instructions_tokens']} tokens ({metrics['instructions_chars']} chars)")
    print(f"Tool Schemas Total: {metrics['total_tool_schema_tokens']} tokens")
    print(f"Grand Total Schema Overhead: {metrics['grand_total_tokens']} tokens\n")
    print(f"{'Tool Name':<26} {'Desc Chars':<12} {'Schema Tokens':<14}")
    print("-" * 54)
    for t in metrics["tools"]:
        print(f"{t['name']:<26} {t['description_chars']:<12} {t['schema_tokens']:<14}")


if __name__ == "__main__":
    main()

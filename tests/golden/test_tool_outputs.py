from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from token_context_mcp.server import build_server


def _sanitize(val: Any) -> Any:
    if isinstance(val, dict):
        cleaned = {}
        for k, v in val.items():
            if k in ("index_run_id", "run_id"):
                cleaned[k] = "<RUN_ID>"
            elif k in ("timestamp", "created_at", "last_indexed"):
                cleaned[k] = "<TIMESTAMP>"
            elif k == "root" and isinstance(v, str):
                cleaned[k] = "<REPO_ROOT>"
            else:
                cleaned[k] = _sanitize(v)
        return cleaned
    elif isinstance(val, list):
        return [_sanitize(x) for x in val]
    return val


def test_golden_core_tool_outputs(indexed_config: Path) -> None:
    server = build_server(indexed_config)

    # 1. list_repositories
    res = asyncio.run(server.call_tool("list_repositories", {}))
    sc = _sanitize(res.structured_content)
    assert sc["repo_ids"] == ["demo"]
    assert "budget_profiles" in sc
    assert sc["truncated"] is False

    # 2. get_index_status
    res = asyncio.run(server.call_tool("get_index_status", {"repo_id": "demo"}))
    sc = _sanitize(res.structured_content)
    assert sc["repo_id"] == "demo"
    assert sc["freshness"] == "fresh"
    assert "basis" in sc["completeness"]
    assert sc["index_run_id"] == "<RUN_ID>"

    # 3. get_repo_map
    res = asyncio.run(server.call_tool("get_repo_map", {"repo_id": "demo", "budget_tokens": 1024, "format": "compact"}))
    sc = _sanitize(res.structured_content)
    assert sc["repo_id"] == "demo"
    assert "data" in sc and "symbols" in sc["data"]
    symbols = sc["data"]["symbols"]
    assert len(symbols) >= 2
    symbol_names = [s.get("name") for s in symbols if isinstance(s, dict)]
    assert "alpha" in symbol_names or any("alpha" in str(s) for s in symbols)

    # 4. find_symbols
    res = asyncio.run(server.call_tool("find_symbols", {"repo_id": "demo", "pattern": "alpha"}))
    sc = _sanitize(res.structured_content)
    assert sc["repo_id"] == "demo"
    found = sc["data"]["symbols"]
    assert len(found) >= 1
    alpha_symbol = found[0]
    alpha_id = alpha_symbol["symbol_id"]
    assert alpha_symbol["name"] == "alpha"

    # 5. get_file_skeleton
    res = asyncio.run(server.call_tool("get_file_skeleton", {"repo_id": "demo", "path": "app.py"}))
    sc = _sanitize(res.structured_content)
    assert sc["repo_id"] == "demo"
    skeleton_items = sc["data"]["skeleton"]
    assert any(item.get("kind") == "function" for item in skeleton_items)

    # 6. search_source
    res = asyncio.run(server.call_tool("search_source", {"repo_id": "demo", "query": "beta"}))
    sc = _sanitize(res.structured_content)
    assert sc["repo_id"] == "demo"
    assert len(sc["data"]["matches"]) >= 1

    # 7. get_module_dependents
    res = asyncio.run(server.call_tool("get_module_dependents", {"repo_id": "demo", "path": "helpers.py"}))
    sc = _sanitize(res.structured_content)
    assert sc["repo_id"] == "demo"
    assert "imported_by" in sc["data"]
    assert "app.py" in sc["data"]["imported_by"]

    # 8. get_symbol_context
    res = asyncio.run(server.call_tool("get_symbol_context", {"repo_id": "demo", "symbol_id": alpha_id}))
    sc = _sanitize(res.structured_content)
    assert sc["repo_id"] == "demo"
    assert "symbols" in sc["data"]
    assert sc["data"]["root_symbol_id"] == alpha_id

    # 9. get_impact_slice
    res = asyncio.run(server.call_tool("get_impact_slice", {"repo_id": "demo", "symbol_id": alpha_id, "depth": 1}))
    sc = _sanitize(res.structured_content)
    assert sc["repo_id"] == "demo"
    assert "symbols" in sc["data"]
    assert "edges" in sc["data"]

    # 10. inspect_symbol
    res = asyncio.run(server.call_tool("inspect_symbol", {"repo_id": "demo", "query": "alpha"}))
    sc = _sanitize(res.structured_content)
    assert sc["repo_id"] == "demo"
    assert "budget" in sc
    assert "data" in sc

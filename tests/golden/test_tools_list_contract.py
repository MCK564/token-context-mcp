from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from mcp_types import Implementation

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.schema_compat import check_schema_node
from token_context_mcp.server import build_server

FIXTURE_DEFAULT_SCHEMAS = REPO_ROOT / "tests" / "fixtures" / "tool_schemas_default.json"


async def _client_tools(server: Any, client_name: str | None = None) -> list[Any]:
    info = Implementation(name=client_name or "claude-code", version="1.0")
    async with Client(server, client_info=info) as client:
        result = await client.list_tools()
        return result.tools


def _issues(schemas: dict[str, Any]) -> list[Any]:
    found = []
    for name, schema in schemas.items():
        found.extend(check_schema_node(schema, "mcp_tool", name))
    return found


@pytest.mark.parametrize(
    ("enable_ext", "enable_admin", "expected_count"),
    [
        (False, False, 10),
        (True, False, 20),
        (False, True, 10),
        (True, True, 22),
    ],
)
def test_tools_list_count_by_configuration(
    indexed_config: Path, enable_ext: bool, enable_admin: bool, expected_count: int
) -> None:
    server = build_server(
        indexed_config,
        enable_extensions=enable_ext,
        enable_admin_tools=enable_admin,
    )
    tools = asyncio.run(_client_tools(server))
    assert len(tools) == expected_count


def test_tools_list_default_schemas_match_golden_snapshot(indexed_config: Path) -> None:
    server = build_server(
        indexed_config,
        enable_extensions=True,
        enable_admin_tools=True,
        schema_profile="default",
    )
    tools = asyncio.run(_client_tools(server, client_name="claude-code"))
    golden = json.loads(FIXTURE_DEFAULT_SCHEMAS.read_text(encoding="utf-8"))

    tool_schemas = {t.name: t.input_schema for t in tools}
    assert set(tool_schemas.keys()) == set(golden.keys())

    for name, schema in golden.items():
        assert tool_schemas[name] == schema, f"Schema mismatch for tool {name}"


def test_tools_list_gemini_safe_profile_conformance(indexed_config: Path) -> None:
    server = build_server(
        indexed_config,
        enable_extensions=True,
        enable_admin_tools=True,
        schema_profile="gemini_safe",
    )
    tools = asyncio.run(_client_tools(server, client_name="Antigravity-IDE"))
    assert len(tools) == 22

    schemas = {t.name: t.input_schema for t in tools}
    issues = _issues(schemas)
    assert issues == [], f"Gemini safe profile has schema issues: {issues}"

    for t in tools:
        assert 0 < len(t.description) <= 200, f"Description length out of range for {t.name}"

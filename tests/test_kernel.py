from __future__ import annotations

import time
from typing import Any

import pytest

from token_context_mcp.kernel.context import (
    EffectRecord,
    InvocationContext,
    get_current_context,
    reset_current_context,
    set_current_context,
)
from token_context_mcp.kernel.pipeline import (
    AuthMiddleware,
    ExecutionMiddleware,
    GovernanceMiddleware,
    InvocationPipeline,
    format_error,
)
from token_context_mcp.kernel.tools import ToolRegistry, ToolSpec
from token_context_mcp.security.access_control import AccessControlManager, PolicyProfile


def test_invocation_context_and_effects() -> None:
    ctx = InvocationContext(tool_name="test_tool", raw_agent_id="agent-1")
    assert ctx.effective_agent_id == "anonymous"
    assert ctx.elapsed_ms >= 0

    reverted_items: list[str] = []

    ctx.record_effect("db_write", "users_table", {"id": 1}, revert_fn=lambda: reverted_items.append("effect-1"))
    ctx.record_effect("cache_write", "mem_cache", {"key": "k"}, revert_fn=lambda: reverted_items.append("effect-2"))

    assert len(ctx.effects) == 2
    ctx.rollback_effects()
    # Rollback must happen in reverse order (LIFO)
    assert reverted_items == ["effect-2", "effect-1"]


def test_context_var_propagation() -> None:
    assert get_current_context() is None
    ctx = InvocationContext(tool_name="ctx_tool")
    token = set_current_context(ctx)
    try:
        assert get_current_context() is ctx
    finally:
        reset_current_context(token)
    assert get_current_context() is None


def test_pipeline_waterfall_execution() -> None:
    access_mgr = AccessControlManager()
    access_mgr.register_agent("alice", policy=PolicyProfile.READ_ONLY)

    pipeline = InvocationPipeline(
        [
            AuthMiddleware(),
            GovernanceMiddleware(access_control=access_mgr),
            ExecutionMiddleware(callback=lambda: {"status": "ok"}),
        ]
    )

    # 1. Allowed call under READ_ONLY
    ctx1 = InvocationContext(tool_name="list_repositories", raw_agent_id="alice")
    res1 = pipeline.execute(ctx1)
    assert res1 == {"status": "ok"}
    assert ctx1.effective_agent_id == "alice"

    # 2. Denied call under READ_ONLY
    ctx2 = InvocationContext(tool_name="memory_put", raw_agent_id="alice")
    res2 = pipeline.execute(ctx2)
    assert "error" in res2
    assert res2["error"]["code"] == "permission_revoked"


def test_tool_registry_and_specs() -> None:
    registry = ToolRegistry()
    spec_core = ToolSpec(
        name="core_tool",
        title="Core Tool",
        description="Core functionality",
        category="retrieval",
        input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
    )
    spec_ext = ToolSpec(
        name="ext_tool",
        title="Ext Tool",
        description="Extension functionality",
        category="memory",
        requires_extensions=True,
        input_schema={"type": "object", "properties": {"val": {"type": "string"}}},
    )
    spec_admin = ToolSpec(
        name="admin_tool",
        title="Admin Tool",
        description="Admin functionality",
        category="admin",
        requires_admin=True,
        requires_extensions=True,
        input_schema={"type": "object", "properties": {"token": {"type": "string"}}},
    )

    registry.register(spec_core)
    registry.register(spec_ext)
    registry.register(spec_admin)

    # Core only
    core_specs = registry.list_specs(enable_extensions=False, enable_admin=False)
    assert [s.name for s in core_specs] == ["core_tool"]

    # Extensions only
    ext_specs = registry.list_specs(enable_extensions=True, enable_admin=False)
    assert {s.name for s in ext_specs} == {"core_tool", "ext_tool"}

    # Extensions + Admin
    all_specs = registry.list_specs(enable_extensions=True, enable_admin=True)
    assert {s.name for s in all_specs} == {"core_tool", "ext_tool", "admin_tool"}

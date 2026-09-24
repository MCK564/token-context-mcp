from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Literal

from mcp.server import MCPServer
from mcp_types import CallToolResult, TextContent

from token_context_mcp import __version__
from token_context_mcp.config import ConfigError, UnknownRepositoryError, load_config
from token_context_mcp.retrieve.serialization import ResultFinalizer, summarize_payload
from token_context_mcp.retrieve.service import (
    ArgumentOutOfRangeError,
    BudgetOutOfRangeError,
    RetrievalError,
    RetrievalService,
)
from token_context_mcp.memory.service import MemoryService
from token_context_mcp.retrieve.workflows import CompositeWorkflowEngine
from token_context_mcp.sampling.router import SamplingRouter
from token_context_mcp.security.access_control import AccessControlManager, PolicyProfile
from token_context_mcp.security.audit import AuditLogger
from token_context_mcp.security.path_policy import PathPolicyError

logger = logging.getLogger("token_context_mcp")


def build_server(config_path: Path, enable_extensions: bool | None = None) -> MCPServer:
    config = load_config(config_path)
    service = RetrievalService(config, config_path)
    workflow_engine = CompositeWorkflowEngine(service)
    finalizer = ResultFinalizer(output_mode=config.server.output_mode)
    extensions_enabled = (
        enable_extensions if enable_extensions is not None else getattr(config.server, "enable_extensions", False)
    )
    if extensions_enabled:
        memory_service = MemoryService(config_path.parent / "memory.sqlite")
        sampling_router = SamplingRouter()
    else:
        memory_service = None
        sampling_router = None

    access_control = AccessControlManager()
    audit_logger = AuditLogger(config_path.parent / "audit.sqlite")

    def _wrap(payload: dict[str, Any]) -> CallToolResult:
        return finalizer.finalize(payload)

    def _invoke(callback: Any, tool_name: str = "tool_call", agent_id: str | None = None) -> dict[str, Any]:
        return _dispatch_invoke(
            callback,
            tool_name=tool_name,
            agent_id=agent_id,
            access_control=access_control,
            audit_logger=audit_logger,
        )

    server = MCPServer(
        "token-context",
        version=__version__,
        title="Token Context",
        description="Read-only, source-hashed code-context retrieval for registered repositories.",
        instructions=(
            "Use repo_id from list_repositories; never pass a filesystem path. "
            f"budget_tokens or max_tokens range: 32 through {config.server.max_result_tokens}; graph depth: 0 through 3. "
            "get_repo_map returns compact [id, path:line, kind/name]; use id for follow-up context/impact calls. "
            "Budget profiles: locate, orient, impact, read. "
            "Respect freshness, ambiguity and truncation warnings. Lexical edges are not complete semantic analysis."
        ),
    )
    server.access_control = access_control  # type: ignore[attr-defined]
    server.audit_logger = audit_logger      # type: ignore[attr-defined]
    server.memory_service = memory_service  # type: ignore[attr-defined]

    @server.tool(
        title="Registered repositories",
        description="List registered repository IDs. Call this first; roots are never exposed.",
    )
    def list_repositories() -> CallToolResult:
        return _wrap(_invoke(service.list_repositories, tool_name="list_repositories"))

    @server.tool(
        title="Repository map",
        description="Ranked definitions for a repo_id within budget. Compact entries are [id, path:line, kind/name]; format='full' adds signatures and evidence. For orientation, not proof of full coverage.",
    )
    def get_repo_map(
        repo_id: str,
        query: str | None = None,
        budget_tokens: int | None = None,
        include_tests: bool = False,
        include_omitted_ids: bool = False,
        format: Literal["compact", "full"] | None = None,
        profile: str | None = None,
    ) -> CallToolResult:
        return _wrap(
            _invoke(
                lambda: service.repo_map(
                    repo_id,
                    query=query,
                    budget_tokens=budget_tokens,
                    include_tests=include_tests,
                    include_omitted_ids=include_omitted_ids,
                    format=format,
                    profile=profile,
                )
            )
        )

    @server.tool(
        title="Find symbols",
        description="Find source-backed symbols by name or qualified-name pattern. Returns IDs and spans, never arbitrary files.",
    )
    def find_symbols(
        repo_id: str,
        pattern: str,
        kind: str | None = None,
        limit: int | None = None,
        max_tokens: int | None = None,
        profile: str | None = None,
    ) -> CallToolResult:
        return _wrap(
            _invoke(
                lambda: service.find_symbols(
                    repo_id,
                    pattern=pattern,
                    kind=kind,
                    limit=limit,
                    max_tokens=max_tokens,
                    profile=profile,
                )
            )
        )

    @server.tool(
        title="Module dependents",
        description="Lexical import relationships for indexed path or module. Dynamic imports flagged. Not semantic resolution.",
    )
    def get_module_dependents(
        repo_id: str,
        path: str | None = None,
        module: str | None = None,
        max_tokens: int | None = None,
        profile: str | None = None,
    ) -> CallToolResult:
        return _wrap(
            _invoke(
                lambda: service.module_dependents(
                    repo_id, path=path, module=module, max_tokens=max_tokens, profile=profile
                )
            )
        )

    @server.tool(
        title="Search source bodies",
        description="Search indexed symbol bodies with FTS5 and return bounded snippets, symbol IDs and line evidence.",
    )
    def search_source(
        repo_id: str,
        query: str,
        limit: int | None = None,
        max_tokens: int | None = None,
        profile: str | None = None,
    ) -> CallToolResult:
        return _wrap(
            _invoke(
                lambda: service.search_source(
                    repo_id, query=query, limit=limit, max_tokens=max_tokens, profile=profile
                )
            )
        )

    @server.tool(
        title="File skeleton",
        description="Imports and source-backed headers from one file. Function bodies elided by default.",
    )
    def get_file_skeleton(
        repo_id: str,
        path: str,
        include_private: bool = False,
        max_tokens: int | None = None,
        profile: str | None = None,
    ) -> CallToolResult:
        return _wrap(
            _invoke(
                lambda: service.file_skeleton(
                    repo_id,
                    path=path,
                    include_private=include_private,
                    max_tokens=max_tokens,
                    profile=profile,
                )
            )
        )

    @server.tool(
        title="Symbol context",
        description="Bounded source packet for indexed symbol and observed edges. Check freshness and ambiguity warnings.",
    )
    def get_symbol_context(
        repo_id: str,
        symbol_id: str,
        depth: int = 1,
        include_body: bool | None = None,
        max_tokens: int | None = None,
        include_omitted_ids: bool = False,
        profile: str | None = None,
    ) -> CallToolResult:
        return _wrap(
            _invoke(
                lambda: service.symbol_context(
                    repo_id,
                    symbol_id=symbol_id,
                    depth=depth,
                    include_body=include_body,
                    max_tokens=max_tokens,
                    include_omitted_ids=include_omitted_ids,
                    profile=profile,
                )
            )
        )

    @server.tool(
        title="Impact candidate slice",
        description="Traverse observed caller/callee edges from a symbol. Candidate impact slice, not complete blast radius.",
    )
    def get_impact_slice(
        repo_id: str,
        symbol_id: str,
        direction: Literal["callers", "callees", "both"] = "both",
        depth: int | None = None,
        max_nodes: int | None = None,
        max_tokens: int | None = None,
        profile: str | None = None,
        min_confidence: float | None = None,
        filter_ambiguous: bool = True,
    ) -> CallToolResult:
        return _wrap(
            _invoke(
                lambda: service.impact_slice(
                    repo_id,
                    symbol_id=symbol_id,
                    direction=direction,
                    depth=depth,
                    max_nodes=max_nodes,
                    max_tokens=max_tokens,
                    profile=profile,
                    min_confidence=min_confidence,
                    filter_ambiguous=filter_ambiguous,
                )
            )
        )

    @server.tool(
        title="Index status",
        description="Active snapshot metadata and paths changed since indexing. Run before relying on graph results.",
    )
    def get_index_status(repo_id: str) -> CallToolResult:
        return _wrap(_invoke(lambda: service.status(repo_id)))

    @server.tool(
        title="Inspect symbol (composite)",
        description="Single-turn symbol resolution, context, and immediate impact graph.",
    )
    def inspect_symbol(
        repo_id: str,
        query: str,
        view: Literal["minimal", "normal", "full"] = "normal",
        budget_tokens: int = 2048,
    ) -> CallToolResult:
        return _wrap(
            _invoke(
                lambda: workflow_engine.inspect_symbol(
                    repo_id=repo_id,
                    query=query,
                    view=view,
                    budget_tokens=budget_tokens,
                )
            )
        )

    if extensions_enabled and memory_service and sampling_router:
        # --- Smart Tool Discovery ---

        @server.tool(
            title="List available tools",
            description="Compact catalog of available tools grouped by category (minimal tokens).",
        )
        def list_available_tools(category: str | None = None) -> CallToolResult:
            from token_context_mcp.discovery.tools import list_available_tools as _list_tools
            return _wrap(_invoke(lambda: _list_tools(category=category)))

        @server.tool(
            title="Search tools",
            description="Smart semantic/intent search over tool capabilities to find the right tool for an intent.",
        )
        def search_tools(query: str, limit: int = 3) -> CallToolResult:
            from token_context_mcp.discovery.tools import search_tools as _search_tools
            return _wrap(_invoke(lambda: _search_tools(query=query, limit=limit)))

        @server.tool(
            title="Get tool schema",
            description="Retrieve detailed parameter schema for a specific tool on demand.",
        )
        def get_tool_schema(tool_name: str) -> CallToolResult:
            from token_context_mcp.discovery.tools import get_tool_schema as _get_schema
            return _wrap(_invoke(lambda: _get_schema(tool_name=tool_name)))

        # --- Shared State & Long-term Memory ---

        @server.tool(
            title="Store memory",
            description="Store execution state, checkpoint, or cross-agent artifact in shared persistent memory.",
        )
        def memory_put(
            key: str,
            value: Any,
            scope: str = "session",
            ttl: int | None = 86400,
            session_id: str | None = None,
        ) -> CallToolResult:
            return _wrap(
                _invoke(
                    lambda: memory_service.memory_put(key=key, value=value, scope=scope, ttl=ttl, session_id=session_id),
                    tool_name="memory_put",
                    agent_id=session_id,
                )
            )

        @server.tool(
            title="Retrieve memory",
            description="Retrieve a stored value or execution checkpoint from shared memory without prompt bloat.",
        )
        def memory_get(key: str, scope: str = "session") -> CallToolResult:
            return _wrap(_invoke(lambda: memory_service.memory_get(key=key, scope=scope)))

        @server.tool(
            title="Search memory",
            description="Full-text search over shared memory entries and stored artifacts.",
        )
        def memory_search(query: str, scope: str | None = None, limit: int = 5) -> CallToolResult:
            return _wrap(_invoke(lambda: memory_service.memory_search(query=query, scope=scope, limit=limit)))

        @server.tool(
            title="Acquire memory lock",
            description="Acquire a timed mutex lock on a resource to coordinate multi-agent actions without collisions.",
        )
        def memory_lock(resource_key: str, agent_id: str, timeout_sec: int = 60) -> CallToolResult:
            return _wrap(
                _invoke(
                    lambda: memory_service.memory_lock(resource_key=resource_key, agent_id=agent_id, timeout_sec=timeout_sec),
                    tool_name="memory_lock",
                    agent_id=agent_id,
                )
            )

        @server.tool(
            title="Consolidate memory",
            description="Consolidate and synthesize scattered memory checkpoints into high-level architectural insights (learned from Google Always-On Memory Agent).",
        )
        def memory_consolidate(
            scope: str = "session",
            target_key: str = "project_architectural_insights",
            prune_transient: bool = False,
        ) -> CallToolResult:
            return _wrap(
                _invoke(
                    lambda: memory_service.memory_consolidate(
                        scope=scope,
                        target_key=target_key,
                        prune_transient=prune_transient,
                    ),
                    tool_name="memory_consolidate",
                )
            )

        # --- Hardware-Aware Sampling ---

        @server.tool(
            title="Sample and summarize",
            description="Hardware-aware context compressor/summarizer: compresses large outputs into concise JSON.",
        )
        def sample_summarize(
            text: str,
            intent: str = "general_code_summary",
            max_tokens: int = 512,
            target_symbols: list[str] | None = None,
        ) -> CallToolResult:
            return _wrap(
                _invoke(
                    lambda: sampling_router.summarize(
                        text=text,
                        intent=intent,
                        max_tokens=max_tokens,
                        target_symbols=target_symbols,
                    ),
                    tool_name="sample_summarize",
                )
            )

        # --- Security & Agent Governance ---

        @server.tool(
            title="Agent access control",
            description="Manage agent execution state, revoke locks, or trigger emergency stops.",
        )
        def agent_control(
            action: Literal["status", "pause", "resume", "block", "unblock", "revoke_locks", "emergency_halt", "emergency_resume"],
            agent_id: str | None = None,
            reason: str = "",
            policy: Literal["FULL_ACCESS", "READ_ONLY", "CUSTOM"] | None = None,
        ) -> CallToolResult:
            def _action() -> dict[str, Any]:
                if action == "status":
                    return {
                        "emergency_halt": access_control.is_emergency_halted,
                        "emergency_reason": access_control.emergency_reason,
                        "agents": access_control.list_agents(),
                        "active_locks": memory_service.list_active_locks(),
                    }
                elif action == "pause":
                    if not agent_id:
                        raise ValueError("agent_id is required to pause")
                    access_control.pause_agent(agent_id, reason=reason or "Paused via agent_control tool")
                    return {"action": "pause", "agent_id": agent_id, "status": "PAUSED"}
                elif action == "resume":
                    if not agent_id:
                        raise ValueError("agent_id is required to resume")
                    access_control.resume_agent(agent_id)
                    return {"action": "resume", "agent_id": agent_id, "status": "ACTIVE"}
                elif action == "block":
                    if not agent_id:
                        raise ValueError("agent_id is required to block")
                    access_control.block_agent(agent_id, reason=reason or "Blocked via agent_control tool")
                    return {"action": "block", "agent_id": agent_id, "status": "BLOCKED"}
                elif action == "unblock":
                    if not agent_id:
                        raise ValueError("agent_id is required to unblock")
                    access_control.unblock_agent(agent_id)
                    return {"action": "unblock", "agent_id": agent_id, "status": "ACTIVE"}
                elif action == "revoke_locks":
                    if agent_id:
                        count = memory_service.revoke_agent_locks(agent_id)
                        return {"action": "revoke_locks", "agent_id": agent_id, "revoked_count": count}
                    else:
                        count = memory_service.revoke_all_locks()
                        return {"action": "revoke_locks", "agent_id": "*", "revoked_count": count}
                elif action == "emergency_halt":
                    access_control.emergency_halt(reason=reason or "Emergency halt invoked via tool")
                    return {"action": "emergency_halt", "status": "HALTED", "reason": access_control.emergency_reason}
                elif action == "emergency_resume":
                    access_control.emergency_resume()
                    return {"action": "emergency_resume", "status": "RESUMED"}
                raise ValueError(f"Unknown action: {action}")

            return _wrap(_invoke(_action, tool_name="agent_control", agent_id="admin"))

        @server.tool(
            title="Audit logs query",
            description="Query recent tool execution and security audit logs.",
        )
        def audit_logs(
            limit: int = 50,
            agent_id: str | None = None,
            status: Literal["SUCCESS", "DENIED", "ERROR"] | None = None,
        ) -> CallToolResult:
            return _wrap(
                _invoke(
                    lambda: {"logs": audit_logger.query_logs(limit=limit, agent_id=agent_id, status=status)},
                    tool_name="audit_logs",
                    agent_id=agent_id,
                )
            )

    return server


def run_stdio(config_path: Path) -> None:
    logging.basicConfig(level=logging.INFO)
    build_server(config_path).run(transport="stdio")


def _dispatch_invoke(
    callback: Any,
    tool_name: str = "tool_call",
    agent_id: str | None = None,
    access_control: AccessControlManager | None = None,
    audit_logger: AuditLogger | None = None,
) -> dict[str, Any]:
    start = time.perf_counter()
    if access_control is not None:
        allowed, reason = access_control.check_access(tool_name, agent_id)
        if not allowed:
            duration_ms = (time.perf_counter() - start) * 1000
            if audit_logger is not None:
                audit_logger.log(tool_name, agent_id, "DENIED", duration_ms, {"reason": reason})
            return _error("permission_revoked", reason or "Operation denied by access control policy", agent_id=agent_id)

    try:
        result = callback()
        duration_ms = (time.perf_counter() - start) * 1000
        if audit_logger is not None:
            audit_logger.log(tool_name, agent_id, "SUCCESS", duration_ms)
        return result
    except UnknownRepositoryError:
        duration_ms = (time.perf_counter() - start) * 1000
        if audit_logger is not None:
            audit_logger.log(tool_name, agent_id, "ERROR", duration_ms, {"code": "unknown_repo_id"})
        logger.warning("tool request rejected: unknown repo_id")
        return _error(
            "unknown_repo_id",
            "repo_id is not registered; call list_repositories and use one returned ID",
        )
    except BudgetOutOfRangeError as error:
        duration_ms = (time.perf_counter() - start) * 1000
        if audit_logger is not None:
            audit_logger.log(tool_name, agent_id, "ERROR", duration_ms, {"code": "budget_out_of_range"})
        logger.warning("tool request rejected: budget out of range")
        return _error(
            "budget_out_of_range",
            str(error),
            minimum_tokens=error.minimum,
            maximum_tokens=error.maximum,
        )
    except ArgumentOutOfRangeError as error:
        duration_ms = (time.perf_counter() - start) * 1000
        if audit_logger is not None:
            audit_logger.log(tool_name, agent_id, "ERROR", duration_ms, {"code": "argument_out_of_range"})
        logger.warning("tool request rejected: %s out of range", error.field_name)
        return _error(
            "argument_out_of_range",
            str(error),
            field=error.field_name,
            minimum=error.minimum,
            maximum=error.maximum,
        )
    except PathPolicyError:
        duration_ms = (time.perf_counter() - start) * 1000
        if audit_logger is not None:
            audit_logger.log(tool_name, agent_id, "ERROR", duration_ms, {"code": "policy_rejected"})
        logger.warning("tool request rejected by repository path policy")
        return _error("policy_rejected", "request rejected by read-only repository policy")
    except (ConfigError, RetrievalError, ValueError) as error:
        duration_ms = (time.perf_counter() - start) * 1000
        if audit_logger is not None:
            audit_logger.log(tool_name, agent_id, "ERROR", duration_ms, {"code": "invalid_request", "type": type(error).__name__})
        logger.warning("tool request rejected: %s", type(error).__name__)
        return _error("invalid_request", "request violates the read-only retrieval contract")
    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000
        if audit_logger is not None:
            audit_logger.log(tool_name, agent_id, "ERROR", duration_ms, {"code": "internal_error", "error": str(exc)})
        logger.exception("tool request failed")
        return _error("internal_error", "context service could not complete the request")


def _invoke(callback: Any) -> dict[str, Any]:
    return _dispatch_invoke(callback)


def _error(code: str, message: str, **details: object) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"schema_version": "1.0", "error": error}


_default_finalizer = ResultFinalizer()


def _result(payload: dict[str, Any], finalizer: ResultFinalizer | None = None) -> CallToolResult:
    active = finalizer or _default_finalizer
    return active.finalize(payload)


def _summarize(payload: dict[str, Any]) -> str:
    return summarize_payload(payload)

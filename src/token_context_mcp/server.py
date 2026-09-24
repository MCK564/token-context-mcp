from __future__ import annotations

import json
import logging
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

    def _wrap(payload: dict[str, Any]) -> CallToolResult:
        return finalizer.finalize(payload)

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

    @server.tool(
        title="Registered repositories",
        description="List registered repository IDs. Call this first; roots are never exposed.",
    )
    def list_repositories() -> CallToolResult:
        return _wrap(_invoke(service.list_repositories))

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
            return _wrap(_invoke(lambda: memory_service.memory_put(key=key, value=value, scope=scope, ttl=ttl, session_id=session_id)))

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
            return _wrap(_invoke(lambda: memory_service.memory_lock(resource_key=resource_key, agent_id=agent_id, timeout_sec=timeout_sec)))

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
                    )
                )
            )

    return server


def run_stdio(config_path: Path) -> None:
    logging.basicConfig(level=logging.INFO)
    build_server(config_path).run(transport="stdio")


def _invoke(callback: Any) -> dict[str, Any]:
    try:
        return callback()
    except UnknownRepositoryError:
        logger.warning("tool request rejected: unknown repo_id")
        return _error(
            "unknown_repo_id",
            "repo_id is not registered; call list_repositories and use one returned ID",
        )
    except BudgetOutOfRangeError as error:
        logger.warning("tool request rejected: budget out of range")
        return _error(
            "budget_out_of_range",
            str(error),
            minimum_tokens=error.minimum,
            maximum_tokens=error.maximum,
        )
    except ArgumentOutOfRangeError as error:
        logger.warning("tool request rejected: %s out of range", error.field_name)
        return _error(
            "argument_out_of_range",
            str(error),
            field=error.field_name,
            minimum=error.minimum,
            maximum=error.maximum,
        )
    except PathPolicyError:
        logger.warning("tool request rejected by repository path policy")
        return _error("policy_rejected", "request rejected by read-only repository policy")
    except (ConfigError, RetrievalError, ValueError) as error:
        logger.warning("tool request rejected: %s", type(error).__name__)
        return _error("invalid_request", "request violates the read-only retrieval contract")
    except Exception:
        logger.exception("tool request failed")
        return _error("internal_error", "context service could not complete the request")


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

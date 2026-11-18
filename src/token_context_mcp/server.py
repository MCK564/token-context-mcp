from __future__ import annotations

import hmac
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from token_context_mcp import __version__
from token_context_mcp.client_profile import (
    ClientState,
    apply_schema_profile,
    coerce_memory_value,
    resolve_output_mode,
    resolve_schema_profile,
)
from token_context_mcp.mcp_compat import CallToolResult
from token_context_mcp.config import ConfigError, UnknownRepositoryError, load_config
from token_context_mcp.retrieve.serialization import ResultFinalizer, summarize_payload
from token_context_mcp.retrieve.service import (
    ArgumentOutOfRangeError,
    BudgetOutOfRangeError,
    RetrievalError,
    RetrievalService,
)
from token_context_mcp.memory.service import MemoryService
from token_context_mcp.ledger.service import LedgerService
from token_context_mcp.retrieve.workflows import CompositeWorkflowEngine
from token_context_mcp.sampling.router import SamplingRouter
from token_context_mcp.security.access_control import (
    AccessControlManager,
    PolicyProfile,
    resolve_effective_agent_id,
)
from token_context_mcp.security.audit import AuditLogger
from token_context_mcp.security.governance_store import GovernanceStore
from token_context_mcp.security.path_policy import PathPolicyError
from token_context_mcp.kernel import (
    AuthMiddleware,
    ExecutionMiddleware,
    GovernanceMiddleware,
    InvocationContext,
    InvocationPipeline,
    build_default_registry,
    format_error,
)

logger = logging.getLogger("token_context_mcp")

_READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
_MUTATING_IDEMPOTENT_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
_MUTATING_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
_ADMIN_DESTRUCTIVE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)


def _env_flag(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def build_server(
    config_path: Path,
    enable_extensions: bool | None = None,
    enable_admin_tools: bool | None = None,
    output_mode: str | None = None,
    schema_profile: str = "auto",
) -> MCPServer:
    config = load_config(config_path)
    service = RetrievalService(config, config_path)
    workflow_engine = CompositeWorkflowEngine(service)
    requested_output_mode = output_mode or config.server.output_mode
    client_state = ClientState()
    finalizer = ResultFinalizer(output_mode=requested_output_mode, client_name=lambda: client_state.name)  # type: ignore[arg-type]

    def _schema_profile() -> str:
        return resolve_schema_profile(schema_profile, client_state.name)
    env_ext = _env_flag("TOKEN_CONTEXT_ENABLE_EXTENSIONS")
    env_adm = _env_flag("TOKEN_CONTEXT_ENABLE_ADMIN_TOOLS")
    extensions_enabled = (
        enable_extensions
        if enable_extensions is not None
        else (env_ext if env_ext is not None else getattr(config.server, "enable_extensions", False))
    )
    admin_tools_enabled = (
        enable_admin_tools
        if enable_admin_tools is not None
        else (env_adm if env_adm is not None else getattr(config.server, "enable_admin_tools", False))
    )
    if extensions_enabled:
        sampling_router = SamplingRouter()
        memory_service = MemoryService(config_path.parent / "memory.sqlite", router=sampling_router)
        ledger_service = LedgerService(config, config_path)
    else:
        memory_service = None
        sampling_router = None
        ledger_service = LedgerService(config, config_path) if config.ledger.enabled else None

    gov_store = GovernanceStore(config_path.parent / "governance.sqlite")
    access_control = AccessControlManager(store=gov_store)
    audit_logger = AuditLogger(config_path.parent / "audit.sqlite")

    server_id = f"server-{os.getpid()}-{int(time.time())}"
    server_run_id = f"run_{uuid.uuid4().hex[:12]}"
    last_heartbeat_time = [time.monotonic()]

    def _heartbeat() -> None:
        gov_store.record_heartbeat(
            server_id,
            os.getpid(),
            client_name=client_state.name,
            client_version=client_state.version,
            output_mode=finalizer.effective_mode,
            schema_profile=_schema_profile(),
        )

    _heartbeat()
    logger.info(
        "token-context serve: output_mode=%s (requested %s) schema_profile=%s (requested %s)",
        finalizer.effective_mode, requested_output_mode, _schema_profile(), schema_profile,
    )

    registered_tool_names: set[str] = {
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
    if extensions_enabled:
        registered_tool_names.update({
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
            "trajectory_record",
        })
    if extensions_enabled and admin_tools_enabled:
        registered_tool_names.update({
            "agent_control",
            "audit_logs",
        })

    def _profile_tools_list(result: Any, profile: str) -> Any:
        if profile == "default":
            return result
        if isinstance(result, dict):
            tools = [
                {**t, "inputSchema": apply_schema_profile(t["inputSchema"], profile, t.get("name", ""))}
                if isinstance(t, dict) and "inputSchema" in t else t
                for t in result.get("tools", [])
            ]
            return {**result, "tools": tools}
        tools = [
            t.model_copy(update={"input_schema": apply_schema_profile(t.input_schema, profile, t.name)})
            for t in result.tools
        ]
        return result.model_copy(update={"tools": tools})

    def _wrap(payload: dict[str, Any]) -> CallToolResult:
        return finalizer.finalize(payload)

    def _invoke(
        callback: Any,
        tool_name: str = "tool_call",
        agent_id: str | None = None,
        bypass_halt: bool = False,
        trusted_identity: bool = False,
    ) -> dict[str, Any]:
        now_mono = time.monotonic()
        if now_mono - last_heartbeat_time[0] >= 15.0:
            _heartbeat()
            last_heartbeat_time[0] = now_mono

        return _dispatch_invoke(
            callback,
            tool_name=tool_name,
            agent_id=agent_id,
            run_id=server_run_id,
            access_control=access_control,
            audit_logger=audit_logger,
            bypass_halt=bypass_halt,
            trusted_identity=trusted_identity,
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
            "Evidence Ledger (default enabled): inspect prior_evidence returned by get_repo_map, find_symbols, or search_source BEFORE running broad searches; follow valid anchors directly via inspect_symbol/get_symbol_context, and re-verify from recheck_from when VERIFY_FAILED is reported. "
            "When trajectory_record is available, record verified answers, multi-hop steps, and rejected decoys after completing a query so follow-up turns reuse verified paths. "
            "Respect freshness, ambiguity and truncation warnings. Lexical edges are not complete semantic analysis."
        ),
    )
    server.client_state = client_state      # type: ignore[attr-defined]
    server.finalizer = finalizer            # type: ignore[attr-defined]
    server.governance_store = gov_store     # type: ignore[attr-defined]
    server.access_control = access_control  # type: ignore[attr-defined]
    server.audit_logger = audit_logger      # type: ignore[attr-defined]
    server.memory_service = memory_service  # type: ignore[attr-defined]
    server.sampling_router = sampling_router  # type: ignore[attr-defined]
    server.tool_registry = build_default_registry()  # type: ignore[attr-defined]

    class _ClientMiddleware:
        """Learns the client's name/version and rewrites ``tools/list`` for the active schema profile."""

        async def __call__(self, ctx: Any, call_next: Any) -> Any:
            first_time = client_state.name is None
            params = getattr(ctx.session, "client_params", None)
            info = getattr(params, "client_info", None)
            if info is not None:
                client_state.update(getattr(info, "name", None), getattr(info, "version", None))
                if first_time and client_state.name:
                    try:
                        _heartbeat()
                    except Exception:  # pragma: no cover - governance DB must never break a request
                        logger.exception("heartbeat update failed")
            result = await call_next(ctx)
            if ctx.method == "tools/list":
                result = _profile_tools_list(result, _schema_profile())
            return result

    server.middleware.append(_ClientMiddleware())

    @server.tool(
        title="Registered repositories",
        description=(
            "List registered repo_id values (filesystem roots stay hidden). "
            "Call first before any repo tool; use get_index_status next to check snapshot freshness."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def list_repositories() -> CallToolResult:
        return _wrap(_invoke(service.list_repositories, tool_name="list_repositories"))

    @server.tool(
        title="Repository map",
        description=(
            "Ranked symbol overview [id, path:line, kind/name] within token budget (format='full' adds signatures). "
            "Use for broad repo orientation, not exact lookup (use find_symbols)."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def get_repo_map(
        repo_id: Annotated[str, Field(description="Registered repository ID from list_repositories (never a filesystem path).")],
        query: Annotated[str | None, Field(description="Optional focus query or symbol terms to bias personalized graph ranking.")] = None,
        budget_tokens: Annotated[int | None, Field(description="Maximum token budget for the returned map (32 to max_result_tokens; defaults to profile budget).")] = None,
        include_tests: Annotated[bool, Field(description="Include test files and test symbols in the ranked map when True.")] = False,
        include_omitted_ids: Annotated[bool, Field(description="Include IDs of symbols omitted due to token budget truncation.")] = False,
        format: Annotated[Literal["compact", "full"] | None, Field(description="Output detail level: 'compact' ([id, path:line, kind/name]) or 'full' (adds signatures and evidence).")] = None,
        profile: Annotated[str | None, Field(description="Named budget profile ('locate', 'orient', 'impact', 'read'); defaults to 'orient'.")] = None,
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
                ),
                tool_name="get_repo_map",
            )
        )

    @server.tool(
        title="Find symbols",
        description=(
            "Match symbol definitions by exact or wildcard (*, ?) name pattern to get symbol_id and spans. "
            "Does not return bodies or edges; use inspect_symbol for 1-turn body+graph."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def find_symbols(
        repo_id: Annotated[str, Field(description="Registered repository ID from list_repositories (never a filesystem path).")],
        pattern: Annotated[str, Field(description="Symbol name or qualified-name pattern to match (supports '*' and '?' wildcards).")],
        kind: Annotated[str | None, Field(description="Optional symbol kind filter (e.g. 'function', 'class', 'method', 'interface').")] = None,
        limit: Annotated[int | None, Field(description="Maximum number of matching symbols to return (1 to max_symbol_results).")] = None,
        max_tokens: Annotated[int | None, Field(description="Maximum token budget for the response (32 to max_result_tokens).")] = None,
        profile: Annotated[str | None, Field(description="Named budget profile ('locate', 'orient', 'impact', 'read'); defaults to 'locate'.")] = None,
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
                ),
                tool_name="find_symbols",
            )
        )

    @server.tool(
        title="Module dependents",
        description=(
            "File/module-level lexical import graph (importers and imports) for a path or module. "
            "Dynamic imports flagged. For symbol caller/callee edges, use get_impact_slice instead."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def get_module_dependents(
        repo_id: Annotated[str, Field(description="Registered repository ID from list_repositories (never a filesystem path).")],
        path: Annotated[str | None, Field(description="Repository-relative file path to inspect imports for (provide path or module).")] = None,
        module: Annotated[str | None, Field(description="Module or package identifier to find importers and imports for (provide module or path).")] = None,
        max_tokens: Annotated[int | None, Field(description="Maximum token budget for the response (32 to max_result_tokens).")] = None,
        profile: Annotated[str | None, Field(description="Named budget profile ('locate', 'orient', 'impact', 'read'); defaults to 'impact'.")] = None,
    ) -> CallToolResult:
        return _wrap(
            _invoke(
                lambda: service.module_dependents(
                    repo_id, path=path, module=module, max_tokens=max_tokens, profile=profile
                ),
                tool_name="get_module_dependents",
            )
        )

    @server.tool(
        title="Search source",
        description=(
            "FTS5 keyword search over source bodies ranked by symbol. expand='graph' adds 1-hop callers/callees "
            "of top hits. Use for text search; use get_impact_slice for multi-hop graphs."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def search_source(
        repo_id: Annotated[str, Field(description="Registered repository ID from list_repositories (never a filesystem path).")],
        query: Annotated[str, Field(description="Full-text FTS5 search keywords or code tokens to match across indexed symbols.")],
        limit: Annotated[int | None, Field(description="Maximum number of search hits to return (1 to 100).")] = None,
        max_tokens: Annotated[int | None, Field(description="Maximum token budget for the response (32 to max_result_tokens).")] = None,
        profile: Annotated[str | None, Field(description="Named budget profile ('locate', 'orient', 'impact', 'read'); defaults to 'locate'.")] = None,
        expand: Annotated[Literal["auto", "none", "graph"], Field(description="Neighbor expansion mode: 'auto' (graph for locate profile), 'none', or 'graph' (add callers/callees).")] = "auto",
        expand_k: Annotated[int, Field(description="Number of top search hits to expand with graph neighbors (1 to 8).")] = 3,
        expand_hops: Annotated[int, Field(description="Graph traversal hops for neighbor expansion (1 or 2).")] = 1,
        min_confidence: Annotated[float, Field(description="Minimum edge confidence threshold (0.0 to 1.0) for expanded graph neighbors.")] = 0.6,
    ) -> CallToolResult:
        return _wrap(
            _invoke(
                lambda: service.search_source(
                    repo_id,
                    query=query,
                    limit=limit,
                    max_tokens=max_tokens,
                    profile=profile,
                    expand=expand,
                    expand_k=expand_k,
                    expand_hops=expand_hops,
                    min_confidence=min_confidence,
                ),
                tool_name="search_source",
            )
        )

    @server.tool(
        title="File skeleton",
        description=(
            "Read imports and declaration signatures from one file path with function bodies elided. "
            "Use to outline a known file; use get_symbol_context to read a specific symbol body."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def get_file_skeleton(
        repo_id: Annotated[str, Field(description="Registered repository ID from list_repositories (never a filesystem path).")],
        path: Annotated[str, Field(description="Repository-relative file path to extract imports and declaration headers from.")],
        include_private: Annotated[bool, Field(description="Include private/internal symbols (leading underscore or non-exported) when True.")] = False,
        max_tokens: Annotated[int | None, Field(description="Maximum token budget for the skeleton response (32 to max_result_tokens).")] = None,
        profile: Annotated[str | None, Field(description="Named budget profile ('locate', 'orient', 'impact', 'read'); defaults to 'read'.")] = None,
    ) -> CallToolResult:
        return _wrap(
            _invoke(
                lambda: service.file_skeleton(
                    repo_id,
                    path=path,
                    include_private=include_private,
                    max_tokens=max_tokens,
                    profile=profile,
                ),
                tool_name="get_file_skeleton",
            )
        )

    @server.tool(
        title="Symbol context",
        description=(
            "Fetch bounded source body and 0-3 hop edges for a known symbol_id (use body_offset_line to page long bodies). "
            "If you only have a symbol name, call inspect_symbol instead."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def get_symbol_context(
        repo_id: Annotated[str, Field(description="Registered repository ID from list_repositories (never a filesystem path).")],
        symbol_id: Annotated[str, Field(description="Exact symbol_id obtained from find_symbols, get_repo_map, or search_source.")],
        depth: Annotated[int, Field(description="Caller/callee neighborhood traversal depth around the symbol (0 to 3).")] = 1,
        include_body: Annotated[bool | None, Field(description="Include the source code body of the target symbol (defaults to True for 'read' profile).")] = None,
        max_tokens: Annotated[int | None, Field(description="Maximum token budget for the context packet (32 to max_result_tokens).")] = None,
        include_omitted_ids: Annotated[bool, Field(description="Include symbol IDs omitted when neighbors exceed the token budget.")] = False,
        profile: Annotated[str | None, Field(description="Named budget profile ('locate', 'orient', 'impact', 'read'); defaults to 'read'.")] = None,
        body_offset_line: Annotated[int | None, Field(description="1-based relative line offset within the symbol body to page through large functions.")] = None,
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
                    body_offset_line=body_offset_line,
                    body_paging_hint=True,
                ),
                tool_name="get_symbol_context",
            )
        )

    @server.tool(
        title="Impact candidate slice",
        description=(
            "Traverse 1-3 hop AST caller/callee edges from a known symbol_id with confidence filtering. "
            "Candidate call slice only; for file/module imports use get_module_dependents."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def get_impact_slice(
        repo_id: Annotated[str, Field(description="Registered repository ID from list_repositories (never a filesystem path).")],
        symbol_id: Annotated[str, Field(description="Exact starting symbol_id obtained from find_symbols, get_repo_map, or search_source.")],
        direction: Annotated[Literal["callers", "callees", "both"], Field(description="Call-graph traversal direction: 'callers' (who calls this), 'callees' (what this calls), or 'both'.")] = "both",
        depth: Annotated[int | None, Field(description="Maximum AST call-graph traversal hops (0 to 3; defaults to 2 in 'impact' profile).")] = None,
        max_nodes: Annotated[int | None, Field(description="Maximum number of graph nodes to visit before truncating (1 to max_graph_nodes).")] = None,
        max_tokens: Annotated[int | None, Field(description="Maximum token budget for the impact slice (32 to max_result_tokens).")] = None,
        profile: Annotated[str | None, Field(description="Named budget profile ('locate', 'orient', 'impact', 'read'); defaults to 'impact'.")] = None,
        min_confidence: Annotated[float | None, Field(description="Minimum edge resolution confidence (0.0 to 1.0) required to include an edge.")] = None,
        filter_ambiguous: Annotated[bool, Field(description="Exclude ambiguous lexical edges that match multiple candidate targets when True.")] = True,
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
                ),
                tool_name="get_impact_slice",
            )
        )

    @server.tool(
        title="Index status",
        description=(
            "Return active index snapshot metadata, freshness state, symbol/edge counts, and modified paths "
            "for a repo_id. Call before trusting graph or symbol results."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def get_index_status(
        repo_id: Annotated[str, Field(description="Registered repository ID from list_repositories (never a filesystem path).")],
    ) -> CallToolResult:
        return _wrap(_invoke(lambda: service.status(repo_id), tool_name="get_index_status"))

    @server.tool(
        title="Inspect symbol (composite)",
        description=(
            "1-turn composite lookup by name query when symbol_id is unknown: resolves symbol and 1-hop graph; "
            "view='full' returns a context packet (body, signatures, tests)."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def inspect_symbol(
        repo_id: Annotated[str, Field(description="Registered repository ID from list_repositories (never a filesystem path).")],
        query: Annotated[str, Field(description="Symbol name, qualified name, or keyword query to resolve and inspect in one turn.")],
        view: Annotated[Literal["minimal", "normal", "full"], Field(description="Projection detail: 'minimal' (signatures+edges), 'normal' (adds body), or 'full' (context packet with tests).")] = "normal",
        budget_tokens: Annotated[int, Field(description="Maximum token budget for the composite inspection response (32 to max_result_tokens).")] = 2048,
    ) -> CallToolResult:
        return _wrap(
            _invoke(
                lambda: workflow_engine.inspect_symbol(
                    repo_id=repo_id,
                    query=query,
                    view=view,
                    budget_tokens=budget_tokens,
                ),
                tool_name="inspect_symbol",
            )
        )

    if extensions_enabled and memory_service and sampling_router:
        # --- Smart Tool Discovery ---

        @server.tool(
            title="List available tools",
            description=(
                "Return a compact catalog of enabled MCP tools grouped by category. "
                "Use to browse capabilities; use search_tools for keyword matching or get_tool_schema for full arguments."
            ),
            annotations=_READ_ONLY_ANNOTATIONS,
        )
        def list_available_tools(
            category: Annotated[str | None, Field(description="Optional category filter (e.g. 'code_navigation', 'impact_analysis', 'shared_memory', 'tool_discovery', 'security_governance').")] = None,
        ) -> CallToolResult:
            from token_context_mcp.discovery.tools import list_available_tools as _list_tools
            return _wrap(_invoke(lambda: _list_tools(category=category, enabled=registered_tool_names), tool_name="list_available_tools"))

        @server.tool(
            title="Search tools",
            description=(
                "Keyword and token-overlap search over enabled tool metadata, prerequisites, and follow-ups. "
                "Call get_tool_schema on a matched tool name to inspect its full JSON schema."
            ),
            annotations=_READ_ONLY_ANNOTATIONS,
        )
        def search_tools(
            query: Annotated[str, Field(description="Keywords describing the task or capability to match against tool metadata.")],
            limit: Annotated[int, Field(description="Maximum number of matching tools to return (default 3).")] = 3,
        ) -> CallToolResult:
            from token_context_mcp.discovery.tools import search_tools as _search_tools
            return _wrap(_invoke(lambda: _search_tools(query=query, limit=limit, enabled=registered_tool_names), tool_name="search_tools"))

        @server.tool(
            title="Get tool schema",
            description=(
                "Fetch the full input JSON Schema, parameter summary, prerequisites, and follow-up tools "
                "for one enabled tool_name. Call after list_available_tools or search_tools."
            ),
            annotations=_READ_ONLY_ANNOTATIONS,
        )
        async def get_tool_schema(
            tool_name: Annotated[str, Field(description="Exact name of the enabled MCP tool to retrieve the full JSON Schema for.")],
        ) -> CallToolResult:
            from token_context_mcp.discovery.tools import get_tool_schema as _get_schema

            profile = _schema_profile()
            schemas = {
                tool.name: apply_schema_profile(tool.input_schema, profile, tool.name)
                for tool in await server.list_tools()
            }
            return _wrap(
                _invoke(
                    lambda: _get_schema(tool_name=tool_name, schema_dict=schemas, enabled=registered_tool_names),
                    tool_name="get_tool_schema",
                )
            )

        # --- Shared State & Long-term Memory ---

        @server.tool(
            title="Store memory",
            description=(
                "Upsert a key-value checkpoint or artifact in persistent SQLite memory scoped by scope and namespace "
                "with optional TTL. Pair with memory_get or memory_search to retrieve."
            ),
            annotations=_MUTATING_IDEMPOTENT_ANNOTATIONS,
        )
        def memory_put(
            key: Annotated[str, Field(description="Unique identifier key for the memory entry within the given scope and namespace.")],
            value: Annotated[Any, Field(description="Value to store (JSON-serializable object, array, number, or string).")],
            scope: Annotated[str, Field(description="Persistence tier: 'session' (transient), 'project' (repo-wide), or 'global' (cross-project).")] = "session",
            namespace: Annotated[str, Field(description="Optional namespace string to isolate entries per agent, task, or workflow.")] = "",
            ttl: Annotated[int | None, Field(description="Time-to-live in seconds before automatic expiration (default 86400; None for no expiry).")] = 86400,
            session_id: Annotated[str | None, Field(description="Optional explicit session identifier when using 'session' scope.")] = None,
        ) -> CallToolResult:
            return _wrap(
                _invoke(
                    lambda: memory_service.memory_put(key=key, value=coerce_memory_value(value, _schema_profile()), scope=scope, namespace=namespace, ttl=ttl, session_id=session_id),
                    tool_name="memory_put",
                )
            )

        @server.tool(
            title="Retrieve memory",
            description=(
                "Fetch one stored value by exact key, scope, and namespace from persistent memory. "
                "Returns not_found if missing or expired; use memory_search for keyword search across keys."
            ),
            annotations=_READ_ONLY_ANNOTATIONS,
        )
        def memory_get(
            key: Annotated[str, Field(description="Exact key of the memory entry to retrieve.")],
            scope: Annotated[str, Field(description="Persistence tier matching the stored entry ('session', 'project', or 'global').")] = "session",
            namespace: Annotated[str, Field(description="Namespace string matching the namespace used in memory_put (default '').")] = "",
            session_id: Annotated[str | None, Field(description="Optional explicit session identifier when reading from 'session' scope.")] = None,
        ) -> CallToolResult:
            return _wrap(
                _invoke(
                    lambda: memory_service.memory_get(key=key, scope=scope, namespace=namespace, session_id=session_id),
                    tool_name="memory_get",
                )
            )

        @server.tool(
            title="Search memory",
            description=(
                "Full-text keyword search across persistent memory keys and values, optionally filtered by scope "
                "and namespace. For exact key lookup, use memory_get instead."
            ),
            annotations=_READ_ONLY_ANNOTATIONS,
        )
        def memory_search(
            query: Annotated[str, Field(description="Full-text search keywords to match against stored memory keys and values.")],
            scope: Annotated[str | None, Field(description="Optional scope filter ('session', 'project', or 'global'); omit to search all scopes.")] = None,
            namespace: Annotated[str | None, Field(description="Optional namespace filter; omit to search across all namespaces.")] = None,
            limit: Annotated[int, Field(description="Maximum number of matching memory entries to return (default 5).")] = 5,
        ) -> CallToolResult:
            return _wrap(_invoke(lambda: memory_service.memory_search(query=query, scope=scope, namespace=namespace, limit=limit), tool_name="memory_search"))

        @server.tool(
            title="Acquire memory lock",
            description=(
                "Acquire an atomic timed mutex lock on resource_key for agent_id to prevent multi-agent write "
                "collisions. Always release with memory_unlock when critical work finishes."
            ),
            annotations=_MUTATING_ANNOTATIONS,
        )
        def memory_lock(
            resource_key: Annotated[str, Field(description="Identifier of the shared resource or file path to lock exclusively.")],
            agent_id: Annotated[str, Field(description="Unique caller agent identifier acquiring and owning the mutex lock.")],
            timeout_sec: Annotated[int, Field(description="Lock lease duration in seconds before automatic expiration (default 60).")] = 60,
        ) -> CallToolResult:
            # "" when the identity is rejected; _invoke refuses and audits that before the callback runs.
            effective_id = resolve_effective_agent_id(agent_id)[0]
            return _wrap(
                _invoke(
                    lambda: memory_service.memory_lock(resource_key=resource_key, agent_id=effective_id, timeout_sec=timeout_sec),
                    tool_name="memory_lock",
                    agent_id=agent_id,
                )
            )

        @server.tool(
            title="Release distributed lock",
            description=(
                "Release a mutex lock previously acquired via memory_lock on resource_key for the owning agent_id. "
                "Safe to call after completing a coordinated multi-agent task."
            ),
            annotations=_MUTATING_IDEMPOTENT_ANNOTATIONS,
        )
        def memory_unlock(
            resource_key: Annotated[str, Field(description="Identifier of the locked resource previously acquired via memory_lock.")],
            agent_id: Annotated[str | None, Field(description="Agent identifier that owns the lock being released.")] = None,
        ) -> CallToolResult:
            effective_id = resolve_effective_agent_id(agent_id)[0]
            return _wrap(
                _invoke(
                    lambda: memory_service.memory_unlock(resource_key=resource_key, agent_id=effective_id),
                    tool_name="memory_unlock",
                    agent_id=agent_id,
                )
            )

        @server.tool(
            title="Consolidate memory",
            description=(
                "Synthesize scattered memory entries in a scope/namespace into one summary under target_key; "
                "set prune_transient=True to delete source session entries after consolidation."
            ),
            annotations=_MUTATING_ANNOTATIONS,
        )
        def memory_consolidate(
            scope: Annotated[str, Field(description="Memory scope to consolidate entries from ('session', 'project', or 'global').")] = "session",
            target_key: Annotated[str, Field(description="Destination memory key where the consolidated summary will be stored.")] = "project_architectural_insights",
            prune_transient: Annotated[bool, Field(description="Delete transient source entries in the selected scope/namespace after consolidation when True.")] = False,
            namespace: Annotated[str | None, Field(description="Optional namespace to restrict consolidation and pruning to.")] = None,
        ) -> CallToolResult:
            return _wrap(
                _invoke(
                    lambda: memory_service.memory_consolidate(
                        scope=scope,
                        target_key=target_key,
                        prune_transient=prune_transient,
                        namespace=namespace,
                    ),
                    tool_name="memory_consolidate",
                )
            )

        # --- Hardware-Aware Sampling ---

        @server.tool(
            title="Sample and summarize",
            description=(
                "Compress large code or tool output into structured JSON using a local LLM when available, "
                "falling back to deterministic extraction. Use before storing in memory_put."
            ),
            annotations=_READ_ONLY_ANNOTATIONS,
        )
        def sample_summarize(
            text: Annotated[str, Field(description="Raw source code or large tool output text to compress into concise JSON.")],
            intent: Annotated[str, Field(description="Summarization goal or focus (e.g. 'general_code_summary', 'call_flow', 'error_analysis').")] = "general_code_summary",
            max_tokens: Annotated[int, Field(description="Maximum token budget for the compressed summary output (default 512).")] = 512,
            target_symbols: Annotated[list[str] | None, Field(description="Optional list of symbol names to preserve verbatim during compression.")] = None,
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

        @server.tool(
            title="Record trajectory evidence",
            description=(
                "Record source-verified symbol citations (answers, multi-hop steps, rejected decoys) into the repo "
                "evidence ledger so future get_repo_map/search_source calls reuse them."
            ),
            annotations=_MUTATING_ANNOTATIONS,
        )
        def trajectory_record(
            repo_id: Annotated[str, Field(description="Registered repository ID from list_repositories (never a filesystem path).")],
            query: Annotated[str, Field(description="Natural-language or technical question answered by the verified symbol trajectory.")],
            answers: Annotated[list[str], Field(description="List of source-verified answer anchors formatted as '<symbol_id>@<line>'.")],
            steps: Annotated[list[str] | None, Field(description="Optional list of verified call/reference hops formatted as '<from_id>><to_id>@<line>'.")] = None,
            decoys: Annotated[list[str] | None, Field(description="Optional list of rejected false-positive symbols formatted as '<symbol_id>!<reason_code>'.")] = None,
            agent_id: Annotated[str | None, Field(description="Optional identifier of the agent recording the verified trajectory.")] = None,
        ) -> CallToolResult:
            assert ledger_service is not None
            return _wrap(
                _invoke(
                    lambda: ledger_service.trajectory_record(
                        repo_id=repo_id,
                        query=query,
                        answers=answers,
                        steps=steps,
                        decoys=decoys,
                        agent_id=agent_id,
                    ),
                    tool_name="trajectory_record",
                    agent_id=agent_id,
                )
            )

        if admin_tools_enabled:
            # --- Security & Agent Governance ---

            @server.tool(
                title="Agent access control",
                description=(
                    "Inspect or enforce multi-agent governance: status (read-only), or pause/resume/block/set_policy/"
                    "revoke_locks/emergency_halt (requires TOKEN_CONTEXT_ADMIN_TOKEN)."
                ),
                annotations=_ADMIN_DESTRUCTIVE_ANNOTATIONS,
            )
            def agent_control(
                action: Annotated[Literal["status", "pause", "resume", "block", "unblock", "set_policy", "revoke_locks", "emergency_halt", "emergency_resume"], Field(description="Governance operation: 'status' (read-only), 'pause', 'resume', 'block', 'unblock', 'set_policy', 'revoke_locks', 'emergency_halt', or 'emergency_resume'.")],
                admin_token: Annotated[str, Field(description="Secret token matching TOKEN_CONTEXT_ADMIN_TOKEN env var (required for all mutating actions, omit for 'status').")] = "",
                agent_id: Annotated[str | None, Field(description="Target agent identifier for pause, resume, block, unblock, set_policy, or revoke_locks.")] = None,
                reason: Annotated[str, Field(description="Audit log reason explaining why the governance action or emergency halt was taken.")] = "",
                policy: Annotated[Literal["FULL_ACCESS", "READ_ONLY", "CUSTOM"] | None, Field(description="Access policy profile for action='set_policy': 'FULL_ACCESS', 'READ_ONLY', or 'CUSTOM'.")] = None,
                custom_tools: Annotated[list[str] | None, Field(description="Allowed tool names when action='set_policy' and policy='CUSTOM'.")] = None,
            ) -> CallToolResult:
                if action != "status":
                    expected_token = os.environ.get("TOKEN_CONTEXT_ADMIN_TOKEN")
                    if not expected_token:
                        start_denied = time.perf_counter()
                        duration_ms = (time.perf_counter() - start_denied) * 1000
                        audit_logger.log("agent_control", agent_id, "DENIED", duration_ms, {"reason": "admin_token_not_configured"})
                        return _wrap(_error("permission_revoked", "Admin tools enabled but TOKEN_CONTEXT_ADMIN_TOKEN environment variable is not set", agent_id=agent_id))

                    if not admin_token or not hmac.compare_digest(admin_token.encode("utf-8"), expected_token.encode("utf-8")):
                        start_denied = time.perf_counter()
                        duration_ms = (time.perf_counter() - start_denied) * 1000
                        audit_logger.log("agent_control", agent_id, "DENIED", duration_ms, {"reason": "invalid_admin_token"})
                        return _wrap(_error("permission_revoked", "Invalid admin token", agent_id=agent_id))

                if action in {"pause", "block", "set_policy"} and agent_id == "admin":
                    start_denied = time.perf_counter()
                    duration_ms = (time.perf_counter() - start_denied) * 1000
                    audit_logger.log("agent_control", agent_id, "DENIED", duration_ms, {"reason": "cannot_pause_admin"})
                    return _wrap(_error("permission_revoked", "Cannot pause or block admin agent", agent_id=agent_id))

                bypass_halt = action in {"status", "emergency_resume"}

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
                    elif action == "set_policy":
                        if not agent_id:
                            raise ValueError("agent_id is required to set_policy")
                        if policy is None:
                            raise ValueError("policy is required to set_policy")
                        profile = PolicyProfile(policy)
                        if profile == PolicyProfile.CUSTOM and not custom_tools:
                            raise ValueError("custom_tools is required (non-empty) when policy is CUSTOM")
                        access_control.set_agent_policy(
                            agent_id,
                            profile,
                            custom_tools=set(custom_tools) if profile == PolicyProfile.CUSTOM else set(),
                        )
                        return {"action": "set_policy", "agent_id": agent_id, "policy": profile.value}
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
                        return {"action": "emergency_resume", "status": "ACTIVE", "emergency_halt": False}
                    raise ValueError(f"Unknown action: {action}")

                return _wrap(_invoke(_action, tool_name="agent_control", agent_id="admin", bypass_halt=bypass_halt, trusted_identity=True))

            @server.tool(
                title="Audit logs query",
                description=(
                    "Query recent tool invocation and security governance audit records from audit.sqlite, "
                    "filtered by agent_id or execution status (SUCCESS, DENIED, ERROR)."
                ),
                annotations=_READ_ONLY_ANNOTATIONS,
            )
            def audit_logs(
                limit: Annotated[int, Field(description="Maximum number of recent audit log entries to return (1 to 500, default 50).")] = 50,
                agent_id: Annotated[str | None, Field(description="Optional agent identifier to filter audit records by caller.")] = None,
                status: Annotated[Literal["SUCCESS", "DENIED", "ERROR"] | None, Field(description="Optional execution outcome filter: 'SUCCESS', 'DENIED', or 'ERROR'.")] = None,
            ) -> CallToolResult:
                return _wrap(
                    _invoke(
                        lambda: {"logs": audit_logger.query_logs(limit=limit, agent_id=agent_id, status=status)},
                        tool_name="audit_logs",
                    )
                )

    return server


def run_stdio(
    config_path: Path,
    enable_extensions: bool | None = None,
    enable_admin_tools: bool | None = None,
    output_mode: str | None = None,
    schema_profile: str = "auto",
) -> None:
    logging.basicConfig(level=logging.INFO)
    build_server(
        config_path,
        enable_extensions=enable_extensions,
        enable_admin_tools=enable_admin_tools,
        output_mode=output_mode,
        schema_profile=schema_profile,
    ).run(transport="stdio")


def _dispatch_invoke(
    callback: Any,
    tool_name: str = "tool_call",
    agent_id: str | None = None,
    run_id: str | None = None,
    access_control: AccessControlManager | None = None,
    audit_logger: AuditLogger | None = None,
    bypass_halt: bool = False,
    trusted_identity: bool = False,
) -> dict[str, Any]:
    ctx = InvocationContext(
        tool_name=tool_name,
        raw_agent_id=agent_id,
        run_id=run_id,
        bypass_halt=bypass_halt,
        trusted_identity=trusted_identity,
    )
    pipeline = InvocationPipeline(
        [
            AuthMiddleware(audit_logger=audit_logger),
            GovernanceMiddleware(access_control=access_control, audit_logger=audit_logger),
            ExecutionMiddleware(callback=callback, audit_logger=audit_logger),
        ]
    )
    return pipeline.execute(ctx)


def _invoke(callback: Any) -> dict[str, Any]:
    return _dispatch_invoke(callback)


def _error(code: str, message: str, **details: object) -> dict[str, Any]:
    return format_error(code, message, **details)


_default_finalizer = ResultFinalizer()


def _result(payload: dict[str, Any], finalizer: ResultFinalizer | None = None) -> CallToolResult:
    active = finalizer or _default_finalizer
    return active.finalize(payload)


def _summarize(payload: dict[str, Any]) -> str:
    return summarize_payload(payload)

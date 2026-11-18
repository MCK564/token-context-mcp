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
from token_context_mcp.output_schemas import TOOL_OUTPUT_SCHEMAS
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
_DESTRUCTIVE_MUTATING_ANNOTATIONS = ToolAnnotations(
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

    def _profile_tools_list(result: Any, profile: str, *, include_output_schema: bool = False) -> Any:
        if profile == "default" and not include_output_schema:
            return result
        if isinstance(result, dict):
            tools = []
            for t in result.get("tools", []):
                if not isinstance(t, dict):
                    tools.append(t)
                    continue
                updated = dict(t)
                name = updated.get("name", "")
                if profile != "default" and "inputSchema" in updated:
                    updated["inputSchema"] = apply_schema_profile(updated["inputSchema"], profile, name)
                if include_output_schema and name in TOOL_OUTPUT_SCHEMAS:
                    updated["outputSchema"] = TOOL_OUTPUT_SCHEMAS[name]
                tools.append(updated)
            return {**result, "tools": tools}
        tools = []
        for t in result.tools:
            updates: dict[str, Any] = {}
            if profile != "default":
                updates["input_schema"] = apply_schema_profile(t.input_schema, profile, t.name)
            if include_output_schema and t.name in TOOL_OUTPUT_SCHEMAS:
                updates["output_schema"] = TOOL_OUTPUT_SCHEMAS[t.name]
            tools.append(t.model_copy(update=updates) if updates else t)
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
                result = _profile_tools_list(
                    result,
                    _schema_profile(),
                    include_output_schema=(finalizer.effective_mode != "text"),
                )
            return result

    server.middleware.append(_ClientMiddleware())

    @server.tool(
        title="Registered repositories",
        description=(
            "List registered repo_ids and budget_profiles (empty list if none; roots hidden). "
            "Call first before any repo tool; call get_index_status next to verify snapshot freshness."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def list_repositories() -> CallToolResult:
        return _wrap(_invoke(service.list_repositories, tool_name="list_repositories"))

    @server.tool(
        title="Repository map",
        description=(
            "Ranked symbol map [id, path:line, kind/name] within budget (format='full' adds signatures; "
            "omitted_count tracks cuts). query biases graph rank; use find_symbols for exact names."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def get_repo_map(
        repo_id: Annotated[str, Field(description="Registered repository ID from list_repositories (never a filesystem path; errors with unknown_repo_id if unregistered).")],
        query: Annotated[str | None, Field(description="Optional symbol/topic terms that switch rank_mode from global centrality to seed-biased personalized graph ranking.")] = None,
        budget_tokens: Annotated[int | None, Field(description="Token cap for the response (32 to max_result_tokens); defaults to 'orient' profile (4096) and sets truncated=true if symbols are omitted.")] = None,
        include_tests: Annotated[bool, Field(description="Include test files and test symbols in ranking when True; defaults to False to prioritize production code.")] = False,
        include_omitted_ids: Annotated[bool, Field(description="Include up to 10 truncated symbol IDs in omitted_symbol_ids for targeted follow-ups.")] = False,
        format: Annotated[Literal["compact", "full"] | None, Field(description="Entry detail: 'compact' returns [id, path:line, kind/name] tuples; 'full' returns full symbol objects, signatures, and evidence.")] = None,
        profile: Annotated[str | None, Field(description="Named budget profile preset ('locate', 'orient', 'impact', 'read'); explicit args override profile defaults (defaults to 'orient').")] = None,
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
            "Match declaration names by exact or wildcard (*, ?) pattern (exact first; no bodies/edges; "
            "truncated=true if capped). Use search_source for code text or inspect_symbol for body+edges."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def find_symbols(
        repo_id: Annotated[str, Field(description="Registered repository ID from list_repositories (never a filesystem path).")],
        pattern: Annotated[str, Field(description="Symbol name or qualified-name pattern (supports '*' and '?' wildcards; exact matches rank first).")],
        kind: Annotated[str | None, Field(description="Optional declaration kind filter (e.g. 'function', 'class', 'method', 'interface').")] = None,
        limit: Annotated[int | None, Field(description="Maximum matches to return (1 to max_symbol_results; defaults to 'locate' profile or server cap, reporting excess in omitted_count).")] = None,
        max_tokens: Annotated[int | None, Field(description="Token cap for the response (32 to max_result_tokens); defaults to 'locate' profile budget.")] = None,
        profile: Annotated[str | None, Field(description="Named budget profile preset ('locate', 'orient', 'impact', 'read'); defaults to 'locate'.")] = None,
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
            "File/module lexical import graph (imports & imported_by) for one path or module; flags dynamic imports. "
            "Fails if unindexed. For symbol call edges, use get_impact_slice instead."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def get_module_dependents(
        repo_id: Annotated[str, Field(description="Registered repository ID from list_repositories (never a filesystem path).")],
        path: Annotated[str | None, Field(description="Indexed repository-relative file path; pass exactly one of path or module (providing both or neither errors).")] = None,
        module: Annotated[str | None, Field(description="Module/package name (1-200 safe chars); pass exactly one of path or module (providing both or neither errors).")] = None,
        max_tokens: Annotated[int | None, Field(description="Token cap for the response (32 to max_result_tokens); defaults to 'impact' profile budget and reports omissions in omitted_count.")] = None,
        profile: Annotated[str | None, Field(description="Named budget profile preset ('locate', 'orient', 'impact', 'read'); defaults to 'impact'.")] = None,
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
            "Full-text FTS5 body search returning line snippets (omitted_count on budget cap). "
            "For symbol name patterns use find_symbols; for multi-hop call graphs use get_impact_slice."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def search_source(
        repo_id: Annotated[str, Field(description="Registered repository ID from list_repositories (never a filesystem path).")],
        query: Annotated[str, Field(description="Space-separated FTS5 keywords or code identifiers (runs AND query first, topped up with OR if sparse).")],
        limit: Annotated[int | None, Field(description="Maximum symbol hits to return before token packing (1 to 100; defaults to 'locate' profile limit).")] = None,
        max_tokens: Annotated[int | None, Field(description="Token cap for hits plus expanded neighbors (32 to max_result_tokens; defaults to 'locate' profile budget).")] = None,
        profile: Annotated[str | None, Field(description="Budget profile ('locate', 'orient', 'impact', 'read'); 'locate' defaults expand='graph', others default expand='none'.")] = None,
        expand: Annotated[Literal["auto", "none", "graph"], Field(description="Neighbor expansion: 'auto' (graph under 'locate' profile, none otherwise), 'none', or 'graph' (adds top-k callers/callees).")] = "auto",
        expand_k: Annotated[int, Field(description="Number of top search hits used as seeds for graph neighbor expansion (1 to 8).")] = 3,
        expand_hops: Annotated[int, Field(description="Call-graph traversal hops from each expanded seed hit (1 or 2).")] = 1,
        min_confidence: Annotated[float, Field(description="Minimum AST/lexical edge confidence (0.0 to 1.0) required to include an expanded neighbor.")] = 0.6,
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
            "Extract ordered imports and public/private declaration headers for one indexed file with bodies elided "
            "(content=null if stale; omits tail over budget). Use get_symbol_context for bodies."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def get_file_skeleton(
        repo_id: Annotated[str, Field(description="Registered repository ID from list_repositories (never a filesystem path).")],
        path: Annotated[str, Field(description="Indexed repository-relative file path (rejects denied secrets/paths and returns error if unindexed).")],
        include_private: Annotated[bool, Field(description="Include private/internal symbols (leading underscore or non-exported) when True; defaults to public declarations only.")] = False,
        max_tokens: Annotated[int | None, Field(description="Token cap for skeleton entries (32 to max_result_tokens; defaults to 'read' profile budget, truncating tail entries).")] = None,
        profile: Annotated[str | None, Field(description="Named budget profile preset ('locate', 'orient', 'impact', 'read'); defaults to 'read'.")] = None,
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
            "Fetch bounded body and 0-3 hop edges for a known symbol_id (use body_offset_line to page long bodies; "
            "omits body if over max_tokens). If symbol_id is unknown, call inspect_symbol."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def get_symbol_context(
        repo_id: Annotated[str, Field(description="Registered repository ID from list_repositories (never a filesystem path).")],
        symbol_id: Annotated[str, Field(description="Canonical or compact 8-char symbol_id from get_repo_map, find_symbols, or search_source.")],
        depth: Annotated[int, Field(description="Neighborhood traversal depth around the target symbol (0 for target only, up to 3 hops).")] = 1,
        include_body: Annotated[bool | None, Field(description="Include target symbol body; defaults to True in 'read' profile. If body exceeds budget, emits root_body_hint.")] = None,
        max_tokens: Annotated[int | None, Field(description="Token cap for packet and neighbors (32 to max_result_tokens; defaults to 'read' profile budget).")] = None,
        include_omitted_ids: Annotated[bool, Field(description="Include up to 10 truncated neighbor IDs in omitted_symbol_ids when neighbors exceed max_tokens.")] = False,
        profile: Annotated[str | None, Field(description="Named budget profile preset ('locate', 'orient', 'impact', 'read'); defaults to 'read'.")] = None,
        body_offset_line: Annotated[int | None, Field(description="1-based line offset inside the symbol body to read oversized functions in pages via body_window.next_offset.")] = None,
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
            "Traverse 0-3 hop AST caller/callee edges from a known symbol_id; candidate slice only "
            "(truncated=true if capped by max_nodes/max_tokens). For imports use get_module_dependents."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def get_impact_slice(
        repo_id: Annotated[str, Field(description="Registered repository ID from list_repositories (never a filesystem path).")],
        symbol_id: Annotated[str, Field(description="Canonical or compact 8-char starting symbol_id from get_repo_map, find_symbols, or search_source.")],
        direction: Annotated[Literal["callers", "callees", "both"], Field(description="Traversal direction: 'callers' (incoming references), 'callees' (outgoing calls), or 'both'.")] = "both",
        depth: Annotated[int | None, Field(description="Maximum AST call-graph hops (0 to 3; defaults to 2 under 'impact' profile; out-of-range errors).")] = None,
        max_nodes: Annotated[int | None, Field(description="Hard cap on visited graph nodes before setting node_limit_reached=true (1 to max_graph_nodes).")] = None,
        max_tokens: Annotated[int | None, Field(description="Token cap for serialized slice (32 to max_result_tokens; defaults to 'impact' profile budget).")] = None,
        profile: Annotated[str | None, Field(description="Named budget profile preset ('locate', 'orient', 'impact', 'read'); defaults to 'impact'.")] = None,
        min_confidence: Annotated[float | None, Field(description="Optional edge confidence floor (0.0 to 1.0) filtering out weaker lexical call guesses.")] = None,
        filter_ambiguous: Annotated[bool, Field(description="Exclude edges with status='ambiguous' (multiple matching targets) when True; set False to inspect uncertain candidates.")] = True,
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
            "Check snapshot freshness ('fresh', 'stale', 'pending', 'unknown'), counts, and pending_paths "
            "after list_repositories. Run before trusting get_repo_map or graph edges; treat stale spans cautiously."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def get_index_status(
        repo_id: Annotated[str, Field(description="Registered repository ID from list_repositories (never a filesystem path; returns unknown_repo_id if unregistered).")],
    ) -> CallToolResult:
        return _wrap(_invoke(lambda: service.status(repo_id), tool_name="get_index_status"))

    @server.tool(
        title="Inspect symbol (composite)",
        description=(
            "1-turn lookup by exact/wildcard name when symbol_id is unknown (use find_symbols for bulk lists, "
            "get_symbol_context by ID); returns status='not_found', 'ambiguous', or view='full' packet."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def inspect_symbol(
        repo_id: Annotated[str, Field(description="Registered repository ID from list_repositories (never a filesystem path).")],
        query: Annotated[str, Field(description="Exact or wildcard symbol name to resolve (prefers unique exact match; returns up to 5 candidates if ambiguous).")],
        view: Annotated[Literal["minimal", "normal", "full"], Field(description="Detail level: 'minimal' (signature + 3-tuple edges), 'normal' (adds body + edge dicts), 'full' (context packet with callers/callees/tests).")] = "normal",
        budget_tokens: Annotated[int, Field(description="Total token cap (clamped to 256..8192); splits budget between body and relationships and sets retry_hint if body is clipped.")] = 2048,
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
                "List enabled tools grouped by category with summaries, prerequisites, and follow-ups. "
                "Use to browse capabilities; use search_tools for keyword matching or get_tool_schema for JSON schema."
            ),
            annotations=_READ_ONLY_ANNOTATIONS,
        )
        def list_available_tools(
            category: Annotated[str | None, Field(description="Optional category filter ('repository_admin', 'code_navigation', 'impact_analysis', 'tool_discovery', 'shared_memory', 'sampling_inference', 'memory_state', 'security_governance').")] = None,
        ) -> CallToolResult:
            from token_context_mcp.discovery.tools import list_available_tools as _list_tools
            return _wrap(_invoke(lambda: _list_tools(category=category, enabled=registered_tool_names), tool_name="list_available_tools"))

        @server.tool(
            title="Search tools",
            description=(
                "Rank enabled tools by keyword/tag overlap (returns relevance_score, summary, prerequisites); "
                "unlike list_available_tools, filters by query. Call get_tool_schema next for full JSON schema."
            ),
            annotations=_READ_ONLY_ANNOTATIONS,
        )
        def search_tools(
            query: Annotated[str, Field(description="Task or capability keywords matched against enabled tool names, tags, and summaries.")],
            limit: Annotated[int, Field(description="Maximum ranked tools to return (ordered by descending relevance_score, default 3).")] = 3,
        ) -> CallToolResult:
            from token_context_mcp.discovery.tools import search_tools as _search_tools
            return _wrap(_invoke(lambda: _search_tools(query=query, limit=limit, enabled=registered_tool_names), tool_name="search_tools"))

        @server.tool(
            title="Get tool schema",
            description=(
                "Fetch input JSON Schema, parameter summary, prerequisites, and follow-ups for one enabled tool_name "
                "(returns status='not_found' with available_tools if disabled/unknown). Call after search_tools."
            ),
            annotations=_READ_ONLY_ANNOTATIONS,
        )
        async def get_tool_schema(
            tool_name: Annotated[str, Field(description="Exact name of an enabled MCP tool (disabled or unknown names return status='not_found' plus available_tools).")],
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
                "Upsert (overwrites matching key) a checkpoint in SQLite memory with optional TTL; secret-redacted "
                "on write. Use memory_lock for mutual exclusion, memory_consolidate to synthesize entries."
            ),
            annotations=_MUTATING_IDEMPOTENT_ANNOTATIONS,
        )
        def memory_put(
            key: Annotated[str, Field(description="Non-empty key (<= 256 UTF-8 bytes) identifying the entry; overwrites any existing entry with the same (scope, namespace, key).")],
            value: Annotated[Any, Field(description="JSON-serializable value (<= 1 MB serialized; common secret tokens are automatically redacted before storage).")],
            scope: Annotated[str, Field(description="Persistence tier: 'session' (isolated by namespace/session_id), 'project' (repo-level), or 'global' (shared across projects).")] = "session",
            namespace: Annotated[str, Field(description="Isolation bucket (e.g. agent or task ID); defaults to session_id or '' under 'session' scope and must match on memory_get.")] = "",
            ttl: Annotated[int | None, Field(description="Lifetime in seconds before expiry (default 86400; pass None or <= 0 to persist indefinitely until overwritten/pruned).")] = 86400,
            session_id: Annotated[str | None, Field(description="Optional session tag; used as fallback namespace when scope='session' and namespace is empty.")] = None,
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
                "Fetch one memory entry by exact key, scope, and namespace. Returns status='found' with value, "
                "'not_found', or 'expired' when TTL elapsed; use memory_search for keyword queries."
            ),
            annotations=_READ_ONLY_ANNOTATIONS,
        )
        def memory_get(
            key: Annotated[str, Field(description="Exact key previously written with memory_put (non-empty).")],
            scope: Annotated[str, Field(description="Persistence tier where the entry was stored ('session', 'project', or 'global').")] = "session",
            namespace: Annotated[str, Field(description="Exact namespace used at write time; returns status='not_found' if mismatched.")] = "",
            session_id: Annotated[str | None, Field(description="Optional session tag used as fallback namespace when scope='session' and namespace is empty.")] = None,
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
                "FTS5 keyword search across active memory entries ordered by BM25 relevance (skips expired entries; "
                "returns warnings=['invalid_query'] on bad syntax). Use memory_get for exact key lookup."
            ),
            annotations=_READ_ONLY_ANNOTATIONS,
        )
        def memory_search(
            query: Annotated[str, Field(description="Non-empty FTS5 keywords matched across stored keys and serialized values (invalid syntax safely yields 0 matches + warning).")],
            scope: Annotated[str | None, Field(description="Restrict results to 'session', 'project', or 'global'; omit to search across all scopes.")] = None,
            namespace: Annotated[str | None, Field(description="Restrict results to one namespace; omit to search across all namespaces.")] = None,
            limit: Annotated[int, Field(description="Maximum active entries to return after BM25 ranking (default 5).")] = 5,
        ) -> CallToolResult:
            return _wrap(_invoke(lambda: memory_service.memory_search(query=query, scope=scope, namespace=namespace, limit=limit), tool_name="memory_search"))

        @server.tool(
            title="Acquire memory lock",
            description=(
                "Acquire an atomic timed lease on resource_key for agent_id; if held by another agent, "
                "returns status='locked' (acquired=false, held_by, remaining_sec) without blocking. Release via memory_unlock."
            ),
            annotations=_MUTATING_ANNOTATIONS,
        )
        def memory_lock(
            resource_key: Annotated[str, Field(description="Non-empty resource or file key to lock exclusively; re-entrant/renewable when already held by the same agent_id.")],
            agent_id: Annotated[str, Field(description="Validated caller agent identifier owning the lease (non-empty; rejected identities fail governance check).")],
            timeout_sec: Annotated[int, Field(description="Lease TTL in seconds after which another agent can acquire the lock automatically (default 60).")] = 60,
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
                "Release a lease held by agent_id on resource_key; returns status='released' on success or "
                "'not_locked' (no-op) if missing, expired, or owned by another agent. Pair with memory_lock."
            ),
            annotations=_MUTATING_IDEMPOTENT_ANNOTATIONS,
        )
        def memory_unlock(
            resource_key: Annotated[str, Field(description="Resource identifier previously passed to memory_lock.")],
            agent_id: Annotated[str | None, Field(description="Owner agent_id; release succeeds only if it matches the active lock holder, otherwise returns status='not_locked'.")] = None,
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
                "Synthesize up to 500 entries in scope/namespace into one global target_key summary (returns 'noop' if empty). "
                "Prefer over memory_put for rollout; prune_transient=True deletes source keys."
            ),
            annotations=_DESTRUCTIVE_MUTATING_ANNOTATIONS,
        )
        def memory_consolidate(
            scope: Annotated[str, Field(description="Source scope to read up to 500 oldest active entries from ('session', 'project', or 'global').")] = "session",
            target_key: Annotated[str, Field(description="Destination key in 'global' scope (ttl=None); overwrites existing summary and excludes itself from source entries.")] = "project_architectural_insights",
            prune_transient: Annotated[bool, Field(description="When True, permanently deletes consolidated source entries from their origin scope/namespace; defaults to False (non-destructive).")] = False,
            namespace: Annotated[str | None, Field(description="Optional namespace to scope both synthesis and pruning; omit (None) to consolidate every namespace in scope.")] = None,
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
                "Compress large text into structured JSON (intent_alignment, analyzed_symbols, caveats) via local Ollama or "
                "AST fallback. Do not use for exact code lookup (use get_symbol_context); save via memory_put."
            ),
            annotations=_READ_ONLY_ANNOTATIONS,
        )
        def sample_summarize(
            text: Annotated[str, Field(description="Raw code or verbose tool output to compress (first 3000 chars prioritized in hybrid context extraction).")],
            intent: Annotated[str, Field(description="Compression focus guiding extraction and symbol retention (e.g. 'general_code_summary', 'call_flow', 'error_analysis').")] = "general_code_summary",
            max_tokens: Annotated[int, Field(description="Generation token budget passed to local Ollama when active (default 512).")] = 512,
            target_symbols: Annotated[list[str] | None, Field(description="Symbol names that must be preserved verbatim and tracked in symbol_coverage_rate.")] = None,
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
                "Validate and save verified symbol citations to the repo ledger (status='rejected' if source check fails); "
                "do not record unverified guesses. Reused by get_repo_map/search_source."
            ),
            annotations=_MUTATING_ANNOTATIONS,
        )
        def trajectory_record(
            repo_id: Annotated[str, Field(description="Registered repository ID with an existing index snapshot (errors with index_missing if unindexed).")],
            query: Annotated[str, Field(description="Task or question whose indexable terms build the lookup signature (errors with empty_signature if no tokens remain).")],
            answers: Annotated[list[str], Field(description="Source-verified symbol citations formatted as '<symbol_id>@<line>'; at least one must pass verification or card is rejected.")],
            steps: Annotated[list[str] | None, Field(description="Optional verified multi-hop edges formatted as '<from_id>><to_id>@<line>' linking traversal paths.")] = None,
            decoys: Annotated[list[str] | None, Field(description="Optional false-positive symbols formatted as '<symbol_id>!<reason_code>' to down-rank in future searches.")] = None,
            agent_id: Annotated[str | None, Field(description="Optional recording agent ID stored for attribution and per-agent write rate limits.")] = None,
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
                    "Inspect governance ('status', no token) or enforce reversible pause/block/set_policy/emergency_halt "
                    "(halts all agents until emergency_resume) & irreversible revoke_locks (requires admin_token)."
                ),
                annotations=_DESTRUCTIVE_MUTATING_ANNOTATIONS,
            )
            def agent_control(
                action: Annotated[Literal["status", "pause", "resume", "block", "unblock", "set_policy", "revoke_locks", "emergency_halt", "emergency_resume"], Field(description="Operation: 'status' (read-only), reversible agent controls ('pause'/'resume', 'block'/'unblock', 'set_policy', 'emergency_halt'/'emergency_resume'), or 'revoke_locks' (irreversibly drops locks).")],
                admin_token: Annotated[str, Field(description="Secret matching TOKEN_CONTEXT_ADMIN_TOKEN env var; required for every action except 'status' (denied if unset or mismatched).")] = "",
                agent_id: Annotated[str | None, Field(description="Target agent ID (required for pause/resume/block/unblock/set_policy; optional for revoke_locks where None revokes all locks; cannot pause/block 'admin').")] = None,
                reason: Annotated[str, Field(description="Human-readable justification persisted in governance state and audit_logs for mutating actions.")] = "",
                policy: Annotated[Literal["FULL_ACCESS", "READ_ONLY", "CUSTOM"] | None, Field(description="Required when action='set_policy': 'FULL_ACCESS', 'READ_ONLY', or 'CUSTOM' (with non-empty custom_tools).")] = None,
                custom_tools: Annotated[list[str] | None, Field(description="Non-empty list of permitted tool names required when action='set_policy' and policy='CUSTOM'.")] = None,
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
                    "Read-only query of security audit records (timestamp, tool_name, agent_id, status, duration_ms) "
                    "from audit.sqlite, ordered newest-first. Use agent_control(action='status') for live lock/halt state."
                ),
                annotations=_READ_ONLY_ANNOTATIONS,
            )
            def audit_logs(
                limit: Annotated[int, Field(description="Maximum audit records returned newest-first from audit.sqlite (default 50).")] = 50,
                agent_id: Annotated[str | None, Field(description="Exact caller agent_id filter (e.g. 'anonymous' or worker ID); omit to return logs across all agents.")] = None,
                status: Annotated[Literal["SUCCESS", "DENIED", "ERROR"] | None, Field(description="Outcome filter: 'SUCCESS', 'DENIED' (policy/token rejection), or 'ERROR'; omit to include all outcomes.")] = None,
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

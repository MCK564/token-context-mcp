"""JSON Schema (Draft 2020-12) definitions for MCP ``outputSchema`` on all 23 tools.

Every schema uses ``type: "object"`` at the root with ``additionalProperties: True``
and omits strict top-level ``required`` constraints so both normal responses and
structured error envelopes (``{"error": {"code": ..., "message": ...}}``) validate
cleanly under ``ClientSession.validate_tool_result``.
"""
from __future__ import annotations

from typing import Any

_ERROR_PROP: dict[str, Any] = {
    "type": ["object", "string"],
    "description": "Present when the tool call fails (either a structured {code, message, details} object or a diagnostic string).",
    "properties": {
        "code": {"type": "string", "description": "Machine-readable error code."},
        "message": {"type": "string", "description": "Human-readable error explanation."},
        "details": {"type": "object", "description": "Optional structured metadata for the error."},
    },
    "additionalProperties": True,
}

_BUDGET_PROP: dict[str, Any] = {
    "type": "object",
    "description": "Token budget accounting for this response.",
    "properties": {
        "requested_tokens": {"type": "integer", "description": "Requested or profile-default token budget."},
        "estimated_tokens": {"type": "integer", "description": "Estimated serialized response tokens."},
        "envelope_reserve": {"type": "integer", "description": "Wire-framing token reserve when budget >= 512."},
    },
    "additionalProperties": True,
}

_EVIDENCE_PROP: dict[str, Any] = {
    "type": "array",
    "description": "Source-verified file line spans and SHA-256 hashes backing the response.",
    "items": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Repository-relative file path."},
            "start_line": {"type": "integer", "description": "1-based start line in source."},
            "end_line": {"type": "integer", "description": "1-based end line in source."},
            "sha256": {"type": "string", "description": "12-character hex prefix of indexed file SHA-256."},
        },
        "additionalProperties": True,
    },
}

_SYMBOL_RECORD_PROP: dict[str, Any] = {
    "type": "object",
    "description": "Indexed symbol definition metadata.",
    "properties": {
        "symbol_id": {"type": "string", "description": "Canonical repository-scoped symbol identifier."},
        "name": {"type": "string", "description": "Short symbol name."},
        "qualified_name": {"type": "string", "description": "Qualified symbol name."},
        "kind": {"type": "string", "description": "Symbol kind (function, class, method, interface, etc.)."},
        "path": {"type": "string", "description": "Repository-relative file path."},
        "signature": {"type": "string", "description": "Declaration signature header."},
        "start_line": {"type": "integer", "description": "1-based declaration start line."},
        "end_line": {"type": "integer", "description": "1-based declaration end line."},
        "roles": {"type": "array", "items": {"type": "string"}, "description": "Detected semantic/architectural roles."},
    },
    "additionalProperties": True,
}

_EDGE_RECORD_PROP: dict[str, Any] = {
    "type": "object",
    "description": "Observed AST/lexical call or reference edge between symbols.",
    "properties": {
        "source_symbol_id": {"type": "string", "description": "Caller or source symbol ID."},
        "target_symbol_id": {"type": ["string", "null"], "description": "Resolved target symbol ID, or null if external/unresolved."},
        "target_name": {"type": "string", "description": "Target symbol name at call site."},
        "edge_kind": {"type": "string", "description": "Relationship kind (e.g. calls, instantiates, inherits)."},
        "status": {"type": "string", "description": "Resolution status ('resolved', 'ambiguous', or 'unresolved')."},
        "backend": {"type": "string", "description": "Extractor backend producing this edge."},
        "confidence": {"type": ["number", "null"], "description": "Edge resolution confidence in [0.0, 1.0]."},
        "source_path": {"type": "string", "description": "File path where the edge occurs."},
        "source_line": {"type": "integer", "description": "1-based line number of the edge."},
    },
    "additionalProperties": True,
}

_PRIOR_EVIDENCE_PROP: dict[str, Any] = {
    "type": "object",
    "description": "Matching verified evidence card from the repo ledger when available.",
    "properties": {
        "card_id": {"type": "integer", "description": "Ledger card identifier."},
        "status": {"type": "string", "description": "Ledger verification status ('confirmed', 'valid', or 'VERIFY_FAILED')."},
        "recheck_from": {"type": "array", "items": {"type": "string"}, "description": "Stale anchor paths requiring re-verification when VERIFY_FAILED."},
    },
    "additionalProperties": True,
}


def _repo_envelope(data_schema: dict[str, Any], *, include_edge_precision: bool = False) -> dict[str, Any]:
    props: dict[str, Any] = {
        "schema_version": {"type": "string", "description": "Envelope schema version ('1.0')."},
        "repo_id": {"type": "string", "description": "Registered repository identifier."},
        "index_run_id": {"type": ["string", "null"], "description": "Identifier of the active index snapshot run."},
        "freshness": {"type": "string", "description": "Index freshness state ('fresh', 'pending', 'stale', or 'unknown')."},
        "budget": _BUDGET_PROP,
        "truncated": {"type": "boolean", "description": "True if items were omitted due to budget or node limits."},
        "completeness": {
            "type": "object",
            "description": "Coverage/resolution completeness indicator.",
            "properties": {
                "value": {"type": ["number", "null"], "description": "Completeness ratio in [0.0, 1.0], or null if N/A."},
                "basis": {"type": "string", "description": "How completeness was computed."},
            },
            "additionalProperties": True,
        },
        "warnings": {"type": "array", "items": {"type": "string"}, "description": "Freshness, ambiguity, redaction, or security warnings."},
        "evidence": _EVIDENCE_PROP,
        "untrusted_repository_content": {"type": "boolean", "description": "True when payload embeds raw repository text."},
        "ledger_rev": {"type": "integer", "description": "Current evidence ledger revision for repo_id."},
        "data": data_schema,
        "error": _ERROR_PROP,
    }
    if include_edge_precision:
        props["edge_precision"] = {
            "type": "object",
            "description": "Resolved vs. ambiguous edge ratio summary.",
            "properties": {
                "ambiguous_rate": {"type": ["number", "null"], "description": "Fraction of edges marked ambiguous."},
                "resolved_rate": {"type": ["number", "null"], "description": "Fraction of edges resolved unambiguously."},
                "basis": {"type": "string", "description": "Measurement basis."},
            },
            "additionalProperties": True,
        }
    return {"type": "object", "properties": props, "additionalProperties": True}


def _plain_object(props: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {**props, "error": _ERROR_PROP},
        "additionalProperties": True,
    }


TOOL_OUTPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "list_repositories": _plain_object({
        "schema_version": {"type": "string", "description": "Envelope schema version ('1.0')."},
        "repo_ids": {"type": "array", "items": {"type": "string"}, "description": "Sorted list of registered repo_id values (empty if none registered)."},
        "budget_profiles": {"type": "object", "description": "Configured retrieval budget profiles ('locate', 'orient', 'impact', 'read').", "additionalProperties": True},
        "truncated": {"type": "boolean", "description": "True if repo_ids were truncated to stay under max_result_tokens."},
    }),
    "get_index_status": _repo_envelope(
        {
            "type": "object",
            "description": "Snapshot metadata, counts, role breakdown, and paths modified since indexing.",
            "properties": {
                "commit_sha": {"type": ["string", "null"], "description": "Git HEAD commit SHA recorded when snapshot was built."},
                "head_changed_since_index": {"type": ["boolean", "null"], "description": "True if repository HEAD moved after indexing."},
                "generated_at": {"type": ["string", "null"], "description": "ISO timestamp when snapshot was built."},
                "files_indexed": {"type": ["integer", "null"], "description": "Total indexed source files."},
                "symbols_indexed": {"type": ["integer", "null"], "description": "Total indexed symbols."},
                "edges_indexed": {"type": ["integer", "null"], "description": "Total extracted call/reference edges."},
                "index_schema_version": {"type": ["string", "null"], "description": "SQLite index schema version."},
                "symbols_with_roles": {"type": "integer", "description": "Count of symbols assigned architectural roles."},
                "role_counts": {"type": "object", "description": "Symbol count grouped by role name.", "additionalProperties": {"type": "integer"}},
                "entry_points": {"type": "array", "items": {"type": "string"}, "description": "Detected entry-point symbol IDs or paths."},
                "imports": {"type": "integer", "description": "Total recorded lexical import edges."},
                "imported_by": {"type": "integer", "description": "Total distinct imported module targets."},
                "pending_paths": {"type": "array", "items": {"type": "string"}, "description": "Up to 100 indexed paths modified on disk since indexing."},
                "pending_path_count": {"type": "integer", "description": "Total number of modified indexed paths."},
                "added_paths": {"type": "array", "items": {"type": "string"}, "description": "Up to 100 new untracked/unindexed paths detected on disk."},
                "changed_non_indexed": {"type": "array", "items": {"type": "string"}, "description": "Up to 100 modified non-indexed paths."},
                "index_warnings": {"type": "array", "items": {"type": "string"}, "description": "Warnings recorded during snapshot build."},
                "network_policy_status": {"type": ["string", "null"], "description": "Declared network policy status."},
            },
            "additionalProperties": True,
        },
        include_edge_precision=True,
    ),
    "get_repo_map": _repo_envelope({
        "type": "object",
        "description": "Ranked symbol map and omission statistics.",
        "properties": {
            "query": {"type": ["string", "null"], "description": "Seed bias query if provided."},
            "rank_mode": {"type": "string", "description": "'seed_biased' when query is provided, otherwise 'global'."},
            "format": {"type": "string", "description": "Effective output format ('compact' or 'full')."},
            "symbols": {
                "type": "array",
                "description": "Ranked entries: compact tuple [id, path:line, kind/name] or full symbol object.",
                "items": {},
            },
            "file_digests": {"type": "object", "description": "Map of file path to 12-char SHA-256 prefix in compact mode.", "additionalProperties": {"type": "string"}},
            "omitted_symbol_ids": {"type": "array", "items": {"type": "string"}, "description": "Up to 10 omitted symbol IDs when include_omitted_ids=True."},
            "omitted_count": {"type": "integer", "description": "Number of ranked symbols omitted due to budget."},
            "prior_evidence": _PRIOR_EVIDENCE_PROP,
            "estimator_version": {"type": "string", "description": "Token estimator version."},
        },
        "additionalProperties": True,
    }),
    "find_symbols": _repo_envelope({
        "type": "object",
        "description": "Matched symbol records without bodies or graph edges.",
        "properties": {
            "symbols": {"type": "array", "items": _SYMBOL_RECORD_PROP, "description": "Matched symbol definitions."},
            "total_matches": {"type": "integer", "description": "Total matches before limit/budget truncation."},
            "omitted_count": {"type": "integer", "description": "Number of matches omitted due to limit or budget."},
        },
        "additionalProperties": True,
    }),
    "get_module_dependents": _repo_envelope({
        "type": "object",
        "description": "Lexical import and importer relationships for the requested path or module.",
        "properties": {
            "query": {"type": "object", "description": "Normalized lookup key ({'path': ...} or {'module': ...}).", "additionalProperties": {"type": "string"}},
            "matched_paths": {"type": "array", "items": {"type": "string"}, "description": "Indexed file paths matching the query."},
            "imports": {"type": "array", "items": {"type": "string"}, "description": "Modules imported by matched_paths."},
            "imported_by": {"type": "array", "items": {"type": "string"}, "description": "Indexed paths that lexically import this path/module."},
            "basis": {"type": "string", "description": "Extraction basis ('lexical_import_statements')."},
            "omitted_count": {"type": "integer", "description": "Count of import entries omitted due to budget."},
            "estimator_version": {"type": "string", "description": "Token estimator version."},
        },
        "additionalProperties": True,
    }),
    "search_source": _repo_envelope({
        "type": "object",
        "description": "Ranked source hits and optional 1-2 hop graph neighbors.",
        "properties": {
            "query": {"type": "string", "description": "Search query string."},
            "matches": {
                "type": "array",
                "description": "Matched symbol snippets ordered by FTS5 relevance.",
                "items": {
                    "type": "object",
                    "properties": {
                        "symbol_id": {"type": ["string", "null"], "description": "Enclosing symbol ID, or null for module-level hits."},
                        "path": {"type": "string", "description": "Repository-relative file path."},
                        "start_line": {"type": "integer", "description": "1-based line number of the match."},
                        "end_line": {"type": "integer", "description": "1-based end line of the match."},
                        "snippet": {"type": "string", "description": "Matched source line (secret-redacted)."},
                        "lines": {"type": "array", "description": "Pairs of [line_number, text].", "items": {"type": "array"}},
                        "redacted_lines": {"type": "integer", "description": "Number of redacted lines if secrets were masked."},
                    },
                    "additionalProperties": True,
                },
            },
            "neighbors": {"type": "array", "description": "Expanded caller/callee neighbor tuples when expand='graph'.", "items": {"type": "array"}},
            "retrieval": {
                "type": "object",
                "description": "Graph expansion diagnostics when expand='graph'.",
                "properties": {
                    "expand_effective": {"type": "string", "description": "Effective expansion mode used."},
                    "profile_effective": {"type": ["string", "null"], "description": "Active budget profile."},
                    "anchors": {"type": "integer", "description": "Number of anchor symbols expanded."},
                    "neighbors": {"type": "integer", "description": "Number of neighbor rows returned."},
                    "expand_k": {"type": "integer", "description": "Top-k anchors limit applied."},
                    "expand_hops": {"type": "integer", "description": "Graph traversal depth applied."},
                    "min_confidence": {"type": "number", "description": "Minimum edge confidence filter applied."},
                },
                "additionalProperties": True,
            },
            "omitted_count": {"type": "integer", "description": "Number of search matches omitted due to limit or budget."},
            "prior_evidence": _PRIOR_EVIDENCE_PROP,
            "estimator_version": {"type": "string", "description": "Token estimator version."},
        },
        "additionalProperties": True,
    }),
    "get_file_skeleton": _repo_envelope({
        "type": "object",
        "description": "File import count, dependents count, and ordered skeleton declarations.",
        "properties": {
            "path": {"type": "string", "description": "Canonical repository-relative file path."},
            "source_sha256": {"type": "string", "description": "12-character hex prefix of indexed file SHA-256."},
            "imports": {"type": "integer", "description": "Number of imported modules detected in file."},
            "imported_by": {"type": "integer", "description": "Number of indexed files importing this module."},
            "skeleton": {
                "type": "array",
                "description": "Ordered imports and declaration headers (bodies elided).",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "description": "Entry kind ('import', 'function', 'class', 'method', etc.)."},
                        "symbol_id": {"type": "string", "description": "Symbol ID for non-import declarations."},
                        "start_line": {"type": "integer", "description": "1-based start line."},
                        "end_line": {"type": "integer", "description": "1-based end line."},
                        "content": {"type": ["string", "null"], "description": "Redacted declaration header, or null if file is stale."},
                        "redacted_lines": {"type": "integer", "description": "Count of secret-redacted lines."},
                        "body_elided": {"type": "boolean", "description": "True when function/method body was elided."},
                    },
                    "additionalProperties": True,
                },
            },
            "omitted_count": {"type": "integer", "description": "Number of skeleton items omitted due to budget."},
            "estimator_version": {"type": "string", "description": "Token estimator version."},
        },
        "additionalProperties": True,
    }),
    "get_symbol_context": _repo_envelope(
        {
            "type": "object",
            "description": "Target symbol packet (with optional windowed body) and neighborhood edges.",
            "properties": {
                "root_symbol_id": {"type": "string", "description": "Canonical symbol_id of the target symbol."},
                "symbols": {
                    "type": "array",
                    "description": "Root and neighbor symbol packets.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "symbol": _SYMBOL_RECORD_PROP,
                            "content": {"type": ["string", "null"], "description": "Source code body or signature header (null if stale)."},
                            "body_included": {"type": "boolean", "description": "True if full/windowed body is included."},
                            "body_window": {
                                "type": "object",
                                "description": "Paging window metadata when body_offset_line is used.",
                                "properties": {
                                    "start_line": {"type": "integer", "description": "1-based first line in this window."},
                                    "end_line": {"type": "integer", "description": "1-based last line in this window."},
                                    "total_lines": {"type": "integer", "description": "Total lines in symbol body."},
                                    "next_offset": {"type": ["integer", "null"], "description": "Next body_offset_line to read, or null at EOF."},
                                },
                                "additionalProperties": True,
                            },
                            "redacted_lines": {"type": "integer", "description": "Number of secret-redacted lines."},
                            "warnings": {"type": "array", "items": {"type": "string"}, "description": "Per-symbol warnings."},
                        },
                        "additionalProperties": True,
                    },
                },
                "edges": {"type": "array", "items": _EDGE_RECORD_PROP, "description": "Observed caller/callee edges within depth."},
                "external_stubs": {"type": "object", "description": "External library stub metadata for cross-package calls.", "additionalProperties": True},
                "omitted_symbol_ids": {"type": "array", "items": {"type": "string"}, "description": "Up to 10 omitted neighbor symbol IDs when include_omitted_ids=True."},
                "omitted_count": {"type": "integer", "description": "Count of neighbor symbols omitted due to budget."},
                "omitted_edge_count": {"type": "integer", "description": "Count of edges omitted due to budget."},
                "root_body_tokens_needed": {"type": "integer", "description": "Estimated tokens needed if body was omitted due to budget."},
                "root_body_lines": {"type": "integer", "description": "Line count of target symbol when body was omitted."},
                "root_body_hint": {"type": "string", "description": "Paging instruction when body exceeds max_tokens."},
                "estimator_version": {"type": "string", "description": "Token estimator version."},
            },
            "additionalProperties": True,
        },
        include_edge_precision=True,
    ),
    "get_impact_slice": _repo_envelope(
        {
            "type": "object",
            "description": "Candidate caller/callee traversal slice and truncation diagnostics.",
            "properties": {
                "root_symbol_id": {"type": "string", "description": "Canonical starting symbol_id."},
                "direction": {"type": "string", "description": "Traversal direction applied ('callers', 'callees', or 'both')."},
                "depth": {"type": "integer", "description": "Traversal depth applied (0-3)."},
                "symbols": {"type": "array", "items": _SYMBOL_RECORD_PROP, "description": "Visited symbols fitting within token budget."},
                "edges": {"type": "array", "items": _EDGE_RECORD_PROP, "description": "Filtered caller/callee edges fitting within token budget."},
                "nodes_visited": {"type": "integer", "description": "Total graph nodes visited during traversal."},
                "node_limit_reached": {"type": "boolean", "description": "True if traversal stopped at max_nodes."},
                "omitted_count": {"type": "integer", "description": "Count of visited symbols omitted due to budget."},
                "omitted_edge_count": {"type": "integer", "description": "Count of edges omitted due to budget."},
                "note": {"type": "string", "description": "Reminder that lexical edges form a candidate impact slice."},
            },
            "additionalProperties": True,
        },
        include_edge_precision=True,
    ),
    "inspect_symbol": _repo_envelope({
        "type": "object",
        "description": "Composite resolution status, target symbol metadata, optional body/packet, and direct relationships.",
        "properties": {
            "status": {"type": "string", "description": "Resolution outcome: 'resolved', 'ambiguous', or 'not_found'."},
            "query": {"type": "string", "description": "Original symbol name or pattern query."},
            "target_symbol_id": {"type": "string", "description": "Resolved canonical symbol_id (when status='resolved')."},
            "symbol": _SYMBOL_RECORD_PROP,
            "content": {"type": ["string", "null"], "description": "Target symbol body in view='normal' (null if omitted/stale)."},
            "packet": {"type": "object", "description": "Full context packet with target body, callers/callees, and tests when view='full'.", "additionalProperties": True},
            "relationships": {"type": "array", "description": "Direct 1-hop caller/callee entries (tuples in minimal, dicts in normal).", "items": {}},
            "relationship_count": {"type": "integer", "description": "Number of relationships included."},
            "relationships_filtered": {"type": "integer", "description": "Count of low-confidence or ambiguous edges excluded."},
            "relationships_omitted": {"type": "integer", "description": "Count of relationships omitted due to budget."},
            "candidate_count": {"type": "integer", "description": "Number of matching candidates when status='ambiguous'."},
            "candidates": {"type": "array", "description": "Up to 5 disambiguation candidates when status='ambiguous'.", "items": {"type": "object", "additionalProperties": True}},
            "retry_hint": {"type": "object", "description": "Follow-up get_symbol_context call parameters if body was clipped.", "additionalProperties": True},
            "message": {"type": "string", "description": "Guidance message when status is 'not_found' or 'ambiguous'."},
        },
        "additionalProperties": True,
    }),
    "list_available_tools": _plain_object({
        "status": {"type": "string", "description": "Execution status ('success')."},
        "category_filter": {"type": ["string", "null"], "description": "Applied category filter, or null if unfiltered."},
        "total_tools": {"type": "integer", "description": "Total number of enabled tools returned."},
        "categories": {
            "type": "object",
            "description": "Map of category name to compact tool summary records.",
            "additionalProperties": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Tool name."},
                        "summary": {"type": "string", "description": "Concise capability summary."},
                        "parameters": {"type": "object", "description": "Parameter name-to-type summary.", "additionalProperties": {"type": "string"}},
                        "recommended_followups": {"type": "array", "items": {"type": "string"}, "description": "Suggested next tools."},
                        "prerequisites": {"type": "array", "items": {"type": "string"}, "description": "Tools to call beforehand."},
                    },
                    "additionalProperties": True,
                },
            },
        },
    }),
    "search_tools": _plain_object({
        "query": {"type": "string", "description": "Search keywords evaluated."},
        "matches_found": {"type": "integer", "description": "Number of matching tools returned (up to limit)."},
        "tools": {
            "type": "array",
            "description": "Ranked tool matches ordered by descending relevance_score.",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Tool name."},
                    "category": {"type": "string", "description": "Tool category."},
                    "relevance_score": {"type": "number", "description": "Weighted keyword/tag overlap score."},
                    "summary": {"type": "string", "description": "Concise capability summary."},
                    "quick_parameters": {"type": "object", "description": "Parameter name-to-type summary.", "additionalProperties": {"type": "string"}},
                    "recommended_followups": {"type": "array", "items": {"type": "string"}, "description": "Suggested next tools."},
                    "prerequisites": {"type": "array", "items": {"type": "string"}, "description": "Tools to call beforehand."},
                },
                "additionalProperties": True,
            },
        },
    }),
    "get_tool_schema": _plain_object({
        "status": {"type": "string", "description": "'success' if tool is enabled, or 'not_found' if unknown/disabled."},
        "tool_name": {"type": "string", "description": "Requested tool name (present on success)."},
        "category": {"type": "string", "description": "Tool category (present on success)."},
        "summary": {"type": "string", "description": "Tool summary (present on success)."},
        "parameters_summary": {"type": "object", "description": "Compact parameter summary map.", "additionalProperties": {"type": "string"}},
        "recommended_followups": {"type": "array", "items": {"type": "string"}, "description": "Suggested follow-up tools."},
        "prerequisites": {"type": "array", "items": {"type": "string"}, "description": "Suggested prerequisite tools."},
        "schema": {"type": "object", "description": "Full input JSON Schema profiled for the active client.", "additionalProperties": True},
        "available_tools": {"type": "array", "items": {"type": "string"}, "description": "List of enabled tool names returned when status='not_found'."},
    }),
    "memory_put": _plain_object({
        "status": {"type": "string", "description": "'stored' on success, or 'error' if store migration failed."},
        "scope": {"type": "string", "description": "Persistence scope ('session', 'project', or 'global')."},
        "namespace": {"type": "string", "description": "Effective namespace isolating the entry."},
        "key": {"type": "string", "description": "Stored entry key."},
        "ttl": {"type": ["integer", "null"], "description": "Requested TTL in seconds, or null if persistent."},
        "expires_at": {"type": ["number", "null"], "description": "Unix epoch expiration timestamp, or null."},
    }),
    "memory_get": _plain_object({
        "status": {"type": "string", "description": "'found', 'not_found', 'expired', or 'error'."},
        "scope": {"type": "string", "description": "Queried persistence scope."},
        "namespace": {"type": "string", "description": "Effective namespace queried."},
        "key": {"type": "string", "description": "Queried entry key."},
        "value": {"description": "Stored JSON value when status='found', otherwise null."},
        "session_id": {"type": ["string", "null"], "description": "Session identifier attached at write time."},
        "created_at": {"type": "number", "description": "Unix epoch creation/update timestamp when found."},
        "expires_at": {"type": ["number", "null"], "description": "Unix epoch expiration timestamp, or null."},
    }),
    "memory_search": _plain_object({
        "query": {"type": "string", "description": "FTS5 search query evaluated."},
        "matches_count": {"type": "integer", "description": "Number of active matching entries returned."},
        "matches": {
            "type": "array",
            "description": "Active memory entries ordered by BM25 relevance.",
            "items": {
                "type": "object",
                "properties": {
                    "scope": {"type": "string", "description": "Entry scope."},
                    "namespace": {"type": "string", "description": "Entry namespace."},
                    "key": {"type": "string", "description": "Entry key."},
                    "value": {"description": "Decoded JSON value."},
                    "created_at": {"type": "number", "description": "Unix epoch timestamp."},
                },
                "additionalProperties": True,
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}, "description": "Warnings such as 'invalid_query' on malformed FTS5 syntax."},
    }),
    "memory_lock": _plain_object({
        "status": {"type": "string", "description": "'acquired' if granted/renewed, or 'locked' if held by another agent."},
        "acquired": {"type": "boolean", "description": "True if caller owns the lock, False if contended."},
        "resource_key": {"type": "string", "description": "Locked resource identifier."},
        "agent_id": {"type": "string", "description": "Owning agent ID (present when acquired=True)."},
        "expires_in_sec": {"type": "integer", "description": "Lease duration in seconds (present when acquired=True)."},
        "held_by": {"type": "string", "description": "Current lock holder agent ID (present when acquired=False)."},
        "remaining_sec": {"type": "number", "description": "Seconds until current lease expires (present when acquired=False)."},
    }),
    "memory_unlock": _plain_object({
        "status": {"type": "string", "description": "'released' if lock was deleted, or 'not_locked' if absent/held elsewhere."},
        "resource_key": {"type": "string", "description": "Target resource key."},
        "message": {"type": "string", "description": "Explanation when status='not_locked'."},
    }),
    "memory_consolidate": _plain_object({
        "status": {"type": "string", "description": "'consolidated' on synthesis, or 'noop' if no source entries exist."},
        "target_key": {"type": "string", "description": "Destination global key holding the consolidated summary."},
        "target_scope": {"type": "string", "description": "Destination scope ('global')."},
        "source_entries_count": {"type": "integer", "description": "Number of source entries synthesized."},
        "pruned_keys": {"type": "array", "items": {"type": "string"}, "description": "Source keys deleted when prune_transient=True."},
        "insights": {"type": "object", "description": "Synthesized architectural insight payload.", "additionalProperties": True},
        "message": {"type": "string", "description": "Diagnostic message when status='noop'."},
    }),
    "sample_summarize": _plain_object({
        "backend": {"type": "string", "description": "Backend used ('ollama_gpu', 'ollama_cpu', or 'heuristic_fallback')."},
        "engine": {"type": "string", "description": "Model name or 'deterministic_ast_extractor'."},
        "status": {"type": "string", "description": "Execution status ('success')."},
        "latency_ms": {"type": "integer", "description": "Elapsed processing time in milliseconds."},
        "symbol_coverage_rate": {"type": "number", "description": "Fraction of verified symbols retained in output [0.0, 1.0]."},
        "context_retention_rate": {"type": "number", "description": "Context retention score [0.0, 1.0]."},
        "data": {"type": "object", "description": "Compact guarded summary dictionary.", "additionalProperties": True},
        "payload": {
            "type": "object",
            "description": "Structured summary payload.",
            "properties": {
                "intent_alignment": {"type": "string", "description": "High-level summary aligned with intent."},
                "analyzed_symbols": {"type": "array", "description": "Symbol-level responsibilities, constraints, and external calls.", "items": {"type": "object", "additionalProperties": True}},
                "technical_caveats": {"type": "array", "items": {"type": "string"}, "description": "Compression caveats and line count notes."},
            },
            "additionalProperties": True,
        },
    }),
    "trajectory_record": _plain_object({
        "schema_version": {"type": "string", "description": "Envelope schema version ('1.0')."},
        "repo_id": {"type": "string", "description": "Target repository identifier."},
        "data": {
            "type": "object",
            "description": "Verification and persistence outcome from the evidence ledger.",
            "properties": {
                "card_id": {"type": ["integer", "null"], "description": "Assigned ledger card ID, or null if status='rejected'."},
                "sig_hash": {"type": "string", "description": "Normalized query signature hash."},
                "status": {"type": "string", "description": "Card status ('active', 'confirmed', or 'rejected')."},
                "ledger_rev": {"type": "integer", "description": "Updated ledger revision counter."},
                "verified_count": {"type": "integer", "description": "Total citations passing source verification."},
                "answers": {"type": "array", "description": "Per-answer verification results.", "items": {"type": "object", "additionalProperties": True}},
                "steps": {"type": "array", "description": "Per-step verification results.", "items": {"type": "object", "additionalProperties": True}},
                "decoys": {"type": "array", "description": "Per-decoy verification results.", "items": {"type": "object", "additionalProperties": True}},
            },
            "additionalProperties": True,
        },
    }),
    "agent_control": _plain_object({
        "action": {"type": "string", "description": "Executed governance operation (for mutating actions)."},
        "agent_id": {"type": "string", "description": "Target agent ID or '*' (for mutating actions)."},
        "status": {"type": "string", "description": "Resulting agent/system state ('ACTIVE', 'PAUSED', 'BLOCKED', 'HALTED')."},
        "policy": {"type": "string", "description": "Applied policy profile (when action='set_policy')."},
        "revoked_count": {"type": "integer", "description": "Number of locks released (when action='revoke_locks')."},
        "emergency_halt": {"type": "boolean", "description": "Whether global emergency halt is currently active."},
        "emergency_reason": {"type": ["string", "null"], "description": "Recorded reason for active emergency halt."},
        "reason": {"type": ["string", "null"], "description": "Reason recorded on emergency_halt."},
        "agents": {"type": "array", "description": "Registered agent governance records (when action='status').", "items": {"type": "object", "additionalProperties": True}},
        "active_locks": {"type": "array", "description": "Currently active resource locks (when action='status').", "items": {"type": "object", "additionalProperties": True}},
    }),
    "audit_logs": _plain_object({
        "logs": {
            "type": "array",
            "description": "Audit records ordered newest-first.",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "Auto-incremented audit row ID."},
                    "timestamp": {"type": "number", "description": "Unix epoch timestamp of the tool invocation."},
                    "agent_id": {"type": "string", "description": "Effective caller agent ID ('anonymous' if unspecified)."},
                    "tool_name": {"type": "string", "description": "Invoked MCP tool name."},
                    "status": {"type": "string", "description": "Outcome ('SUCCESS', 'DENIED', or 'ERROR')."},
                    "duration_ms": {"type": "number", "description": "Execution duration in milliseconds."},
                    "details": {"type": "object", "description": "Structured audit details (secrets redacted).", "additionalProperties": True},
                },
                "additionalProperties": True,
            },
        },
    }),
}

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, TypeVar

from token_context_mcp.config import (
    DEFAULT_BUDGET_PROFILES,
    AppConfig,
    get_repository,
    index_directory,
)
from token_context_mcp.constants import (
    DEFAULT_MAX_GRAPH_NODES,
    ENVELOPE_RESERVE_TOKENS,
    SCHEMA_VERSION,
)
from token_context_mcp.index.hashing import sha256_file
from token_context_mcp.index.runner import current_pointer_path, database_path
from token_context_mcp.index.sqlite_store import SQLiteStore, StoreError
from token_context_mcp.models import (
    EdgeRecord,
    Evidence,
    FileRecord,
    SymbolRecord,
    edge_as_dict,
    symbol_as_dict,
)
from token_context_mcp.retrieve.freshness import FreshnessCache
from token_context_mcp.retrieve.ranking import rank_symbols
from token_context_mcp.retrieve.token_budget import (
    ESTIMATOR_VERSION,
    estimate_tokens,
    pack_by_budget,
)
from token_context_mcp.security.content_policy import is_hard_denied, redact_text
from token_context_mcp.security.path_policy import (
    PathPolicyError,
    relative_posix,
    safe_relative_path,
)

Entry = TypeVar("Entry")


class RetrievalError(ValueError):
    """A read-only retrieval request cannot be fulfilled safely."""


class BudgetOutOfRangeError(RetrievalError):
    """A caller requested more context than the configured result ceiling."""

    def __init__(self, field_name: str, value: int, minimum: int, maximum: int) -> None:
        super().__init__(f"{field_name} must be between {minimum} and {maximum} tokens")
        self.field_name = field_name
        self.value = value
        self.minimum = minimum
        self.maximum = maximum


class ArgumentOutOfRangeError(RetrievalError):
    """A bounded request argument is outside its documented range."""

    def __init__(self, field_name: str, value: int, minimum: int, maximum: int) -> None:
        super().__init__(f"{field_name} must be between {minimum} and {maximum}")
        self.field_name = field_name
        self.value = value
        self.minimum = minimum
        self.maximum = maximum


class RetrievalService:
    def __init__(self, config: AppConfig, config_path: Path) -> None:
        self._cached_config = config
        self.config_path = config_path
        try:
            self._config_mtime = config_path.stat().st_mtime_ns
        except OSError:
            self._config_mtime = 0
        self.last_query_count = 0
        self._freshness_cache = FreshnessCache()
        self._pointer_cache: dict[str, tuple[float, Path, str | None]] = {}

    @property
    def config(self) -> AppConfig:
        try:
            mtime = self.config_path.stat().st_mtime_ns
        except OSError:
            mtime = 0
        if mtime != self._config_mtime:
            self._cached_config = load_config(self.config_path)
            self._config_mtime = mtime
        return self._cached_config

    @config.setter
    def config(self, value: AppConfig) -> None:
        self._cached_config = value

    def list_repositories(self) -> dict[str, Any]:
        """Return registered IDs without exposing their filesystem roots."""

        all_ids = sorted(self.config.repositories)
        profiles = _available_profiles(self.config)
        selected = list(all_ids)
        while selected and _payload_tokens(
            _repository_list_response(selected, profiles=profiles, truncated=len(selected) < len(all_ids))
        ) > self.config.server.max_result_tokens:
            selected.pop()
        response = _repository_list_response(
            selected, profiles=profiles, truncated=len(selected) < len(all_ids)
        )
        self._assert_under_server_cap(response)
        return response

    def status(self, repo_id: str) -> dict[str, Any]:
        self._validate_request_bytes(repo_id=repo_id)
        repository = get_repository(self.config, repo_id)
        store = self._store(repository.repo_id)
        metadata = store.metadata()
        files = store.files()
        symbols = store.symbols()
        role_counts: dict[str, int] = {}
        for symbol in symbols:
            for role in symbol.roles:
                role_counts[role] = role_counts.get(role, 0) + 1
        snapshot = self._freshness_cache.get_snapshot(
            repository.repo_id,
            str(metadata.get("index_run_id", "")),
            repository.root,
            files,
            metadata=metadata,
            allow_symlinks=repository.allow_symlinks,
        )
        pending = snapshot.stale_paths
        edge_precision = _edge_precision(store.edges())
        warnings: list[str] = []
        if metadata.get("network_policy"):
            warnings.append("network_policy_not_enforced_by_process")
        for w in snapshot.warnings:
            if w not in warnings:
                warnings.append(w)

        response = self._envelope(
            repo_id,
            metadata,
            requested_tokens=0,
            estimated_tokens=0,
            freshness=snapshot.status,
            warnings=warnings,
            truncated=len(pending) > 100,
            edge_precision=edge_precision,
            data={
                "commit_sha": metadata.get("commit_sha"),
                "generated_at": metadata.get("generated_at"),
                "files_indexed": metadata.get("files_indexed"),
                "symbols_indexed": metadata.get("symbols_indexed"),
                "edges_indexed": metadata.get("edges_indexed"),
                "index_schema_version": metadata.get("index_schema_version"),
                "symbols_with_roles": sum(bool(symbol.roles) for symbol in symbols),
                "role_counts": metadata.get("role_counts", role_counts),
                "entry_points": metadata.get("entry_points", []),
                **(
                    {"derived_defaults": metadata.get("derived_defaults", {})}
                    if self.config.server.max_result_tokens >= 512
                    else {}
                ),
                "imports": store.import_count(),
                "imported_by": store.importer_count(),
                "pending_paths": pending[:100],
                "pending_path_count": len(pending),
                "added_paths": snapshot.added_paths[:100],
                "changed_non_indexed": snapshot.changed_non_indexed[:100],
                "index_warnings": metadata.get("warnings", []),
                "network_policy_status": metadata.get("network_policy_status"),
            },
        )
        self._assert_under_server_cap(response)
        return response

    def repo_map(
        self,
        repo_id: str,
        *,
        query: str | None = None,
        budget_tokens: int | None = None,
        include_tests: bool = False,
        include_omitted_ids: bool = False,
        format: Literal["compact", "full"] | None = None,
        profile: str | None = None,
    ) -> dict[str, Any]:
        profile_settings = self._profile_settings(profile, "repo_map")
        if budget_tokens is None:
            budget_tokens = _profile_int(profile_settings, "budget_tokens", 1024)
        if format is None:
            format = _profile_str(profile_settings, "format", "compact")
        self._validate_request_bytes(
            repo_id=repo_id,
            query=query,
            budget_tokens=budget_tokens,
            include_tests=include_tests,
            include_omitted_ids=include_omitted_ids,
            format=format,
        )
        self._validate_budget(budget_tokens, field_name="budget_tokens")
        packing_budget = self._effective_budget(budget_tokens)
        if format not in {"compact", "full"}:
            raise RetrievalError("format must be compact or full")
        repository, store, metadata = self._repository_store(repo_id)
        store.reset_query_count()
        file_records = {item.path: item for item in store.files()}
        freshness = self._freshness(
            repository.root,
            list(file_records.values()),
            allow_symlinks=repository.allow_symlinks,
            metadata=metadata,
            repo_id=repository.repo_id,
        )
        symbols = store.symbols()
        if not include_tests:
            symbols = [symbol for symbol in symbols if not _looks_like_test_path(symbol.path)]
        symbol_ids = {symbol.symbol_id for symbol in symbols}
        edges = [edge for edge in store.edges() if edge.source_symbol_id in symbol_ids]
        body_matches: set[str] = set()
        if query:
            try:
                body_matches = store.body_match_ids(_fts_query(query))
            except StoreError:
                # Existing indexes created before R-P2 remain usable for all
                # other tools; only their body-based ranking is unavailable
                # until an administrative reindex.
                body_matches = set()
        ranked = rank_symbols(symbols, edges, query, body_matches=body_matches)
        if format == "compact":
            # A compact map also carries one digest per selected file. Keep
            # the highest-ranked orientation slice first, then fill the
            # remaining budget from those already-opened files so provenance
            # does not consume the breadth budget one path at a time.
            ranked = _compact_map_order(ranked)
        def build_response(
            selected_items: list[tuple[SymbolRecord, float, list[str]]],
            omitted_items: list[tuple[SymbolRecord, float, list[str]]],
            estimated: int,
        ) -> dict[str, Any]:
            selected = [
                self._repo_map_entry(
                    store,
                    (item[0], item[1]),
                    file_records=file_records,
                    output_format=format,
                    rank_basis=item[2],
                )
                for item in selected_items
            ]
            data: dict[str, Any] = {
                "query": query,
                "rank_mode": "seed_biased" if query else "global",
                "format": format,
                "symbols": selected,
            }
            if format == "compact":
                selected_paths = sorted({item[0].path for item in selected_items})
                data["file_digests"] = {
                    path: file_records[path].sha256[:12] for path in selected_paths if path in file_records
                }
            if include_omitted_ids:
                data["omitted_symbol_ids"] = [
                    _compact_symbol_ref(item[0].symbol_id) if format == "compact" else item[0].symbol_id
                    for item in omitted_items[:10]
                ]
            data.update(
                {
                    "omitted_count": len(omitted_items),
                    "estimator_version": ESTIMATOR_VERSION,
                }
            )
            return self._envelope(
                repo_id,
                metadata,
                requested_tokens=budget_tokens,
                estimated_tokens=estimated,
                freshness=freshness,
                warnings=[],
                truncated=bool(omitted_items),
                data=data,
            )

        chosen, omitted, used = self._pack_to_budget(
            ranked,
            lambda item: _json(
                self._repo_map_entry(
                    store,
                    (item[0], item[1]),
                    file_records=file_records,
                    output_format=format,
                    rank_basis=item[2],
                )
            ),
            packing_budget,
            build_response,
        )
        response = build_response(chosen, omitted, used)
        self.last_query_count = store.query_count
        self._assert_under_server_cap(response)
        return response

    def search_source(
        self,
        repo_id: str,
        *,
        query: str,
        limit: int | None = None,
        max_tokens: int | None = None,
        profile: str | None = None,
    ) -> dict[str, Any]:
        """Full-text search across indexed files with FTS5, returning best matching lines grouped by enclosing symbol."""
        profile_settings = self._profile_settings(profile, "search_source")
        if limit is None:
            limit = _profile_int(profile_settings, "limit", 20)
        if max_tokens is None and "budget_tokens" in profile_settings:
            max_tokens = _profile_int(profile_settings, "budget_tokens", 2048)
        effective_max_tokens = (
            min(2048, self.config.server.max_result_tokens) if max_tokens is None else max_tokens
        )
        self._validate_request_bytes(repo_id=repo_id, query=query, limit=limit, max_tokens=max_tokens)
        self._validate_budget(effective_max_tokens, field_name="max_tokens")
        packing_budget = self._effective_budget(effective_max_tokens)
        if not query or len(query) > 200:
            raise RetrievalError("query must contain 1-200 characters")
        if not 1 <= limit <= 100:
            raise ArgumentOutOfRangeError("limit", limit, 1, 100)
        repository, store, metadata = self._repository_store(repo_id)
        freshness = self._freshness(
            repository.root,
            store.files(),
            allow_symlinks=repository.allow_symlinks,
            metadata=metadata,
            repo_id=repository.repo_id,
        )
        match_query = _fts_query(query)
        try:
            total_matches = store.count_source_matches(match_query)
            rows = store.search_source_matches(match_query, limit=limit)
        except StoreError as error:
            raise RetrievalError(str(error)) from error
        entries: list[dict[str, Any]] = []
        stale_paths: list[str] = []
        unselected_matches_count = 0
        sorted_rows = sorted(
            rows,
            key=lambda r: (1 if r["path"].startswith(("tests/", "evals/")) else 0),
        )
        for row in sorted_rows:
            file_record = store.file(row["path"])
            if file_record is None:
                continue
            state, current_hash = self._freshness_cache.path_state(
                repository.root, file_record, allow_symlinks=repository.allow_symlinks
            )
            file_symbols = store.symbols(path=row["path"])
            if state != "fresh" or current_hash != file_record.sha256:
                stale_paths.append(row["path"])
                symbol = None
                line_number = 1
                entries.append(
                    {
                        "symbol_id": symbol.symbol_id if symbol else None,
                        "path": row["path"],
                        "start_line": line_number,
                        "end_line": line_number,
                        "snippet": None,
                        "evidence": (
                            self._evidence_for_symbol(store, symbol).as_dict()
                            if symbol
                            else Evidence(row["path"], line_number, line_number, file_record.sha256).as_dict()
                        ),
                        "warnings": ["stale_content_unavailable"],
                    }
                )
                continue
            file_path = safe_relative_path(repository.root, row["path"], allow_symlinks=repository.allow_symlinks)
            raw = file_path.read_bytes()
            source = raw.decode("utf-8", errors="replace")
            selected_lines, unselected = _score_and_select_file_matches(
                source, query, file_symbols, row["path"]
            )
            unselected_matches_count += unselected
            for line_number, symbol in selected_lines:
                snippet, redacted = redact_text(_source_snippet(source, line_number))
                entries.append(
                    {
                        "symbol_id": symbol.symbol_id if symbol else None,
                        "path": row["path"],
                        "start_line": line_number,
                        "end_line": line_number,
                        "snippet": snippet,
                        "evidence": (
                            self._evidence_for_symbol(store, symbol).as_dict()
                            if symbol
                            else Evidence(row["path"], line_number, line_number, file_record.sha256).as_dict()
                        ),
                        **({"redacted_lines": redacted} if redacted else {}),
                    }
                )
        source_limit_omitted = max(0, total_matches - len(rows))
        response_warnings: list[str] = []
        if any(item.get("redacted_lines", 0) for item in entries):
            response_warnings.append("potential_secrets_redacted")
        response_warnings.extend(f"stale_content_unavailable:{path}" for path in stale_paths)

        def build_response(
            selected_items: list[dict[str, Any]],
            omitted_items: list[dict[str, Any]],
            estimated: int,
        ) -> dict[str, Any]:
            omitted_count = source_limit_omitted + unselected_matches_count + len(omitted_items)
            return self._envelope(
                repo_id,
                metadata,
                requested_tokens=effective_max_tokens,
                estimated_tokens=estimated,
                freshness=freshness,
                warnings=response_warnings,
                truncated=omitted_count > 0,
                evidence=[],
                data={
                    "query": query,
                    "matches": selected_items,
                    "omitted_count": omitted_count,
                    "estimator_version": ESTIMATOR_VERSION,
                },
            )

        chosen, omitted, used = self._pack_to_budget(
            entries,
            _json,
            packing_budget,
            build_response,
        )
        response = build_response(chosen, omitted, used)
        self._assert_under_server_cap(response)
        return response

    def find_symbols(
        self,
        repo_id: str,
        *,
        pattern: str,
        kind: str | None = None,
        limit: int | None = None,
        max_tokens: int | None = None,
        profile: str | None = None,
    ) -> dict[str, Any]:
        explicit_budget = max_tokens is not None or profile is not None
        profile_settings = self._profile_settings(profile, "find_symbols")
        if limit is None:
            limit = _profile_int(profile_settings, "limit", 20)
        if max_tokens is None and "budget_tokens" in profile_settings:
            max_tokens = _profile_int(
                profile_settings, "budget_tokens", self.config.server.max_result_tokens
            )
        effective_max_tokens = self.config.server.max_result_tokens if max_tokens is None else max_tokens
        self._validate_request_bytes(
            repo_id=repo_id, pattern=pattern, kind=kind, limit=limit, max_tokens=max_tokens, profile=profile
        )
        if not pattern or len(pattern) > 200:
            raise RetrievalError("pattern must contain 1-200 characters")
        if not 1 <= limit <= 100:
            raise RetrievalError("limit must be between 1 and 100")
        if kind is not None and kind not in {"function", "class", "method", "interface"}:
            raise RetrievalError("kind must be function, class, method, or interface")
        if explicit_budget:
            self._validate_budget(effective_max_tokens, field_name="max_tokens")
        packing_budget = (
            self._effective_budget(effective_max_tokens)
            if explicit_budget
            else effective_max_tokens
        )
        repository, store, metadata = self._repository_store(repo_id)
        freshness = self._freshness(
            repository.root,
            store.files(),
            allow_symlinks=repository.allow_symlinks,
            metadata=metadata,
            repo_id=repository.repo_id,
        )
        derived_limit = _metadata_default(metadata, "limit_ceiling", 100)
        effective_limit = min(limit, self.config.server.max_symbol_results, derived_limit)
        available_count = store.count_symbols(pattern, kind=kind)
        symbols = store.find_symbols(pattern, kind=kind, limit=effective_limit)
        server_capped = effective_limit < limit and available_count > effective_limit
        warnings: list[str] = []
        if server_capped:
            warnings.append("symbol_limit_capped_by_server")
        elif limit < available_count:
            warnings.append("more_matches_available")

        entries = [
            (
                symbol,
                {
                    "symbol": symbol_as_dict(symbol),
                    "evidence": self._evidence_for_symbol(store, symbol).as_dict(),
                },
            )
            for symbol in symbols
        ]

        def build_response(
            selected_items: list[tuple[SymbolRecord, dict[str, Any]]],
            omitted_items: list[tuple[SymbolRecord, dict[str, Any]]],
            estimated: int,
        ) -> dict[str, Any]:
            resp_warnings = list(warnings)
            if omitted_items:
                resp_warnings.append("result_payload_capped_by_server")
            selected_symbols = [item[1]["symbol"] for item in selected_items]
            omitted_count = max(0, available_count - len(selected_symbols))
            return self._envelope(
                repo_id,
                metadata,
                requested_tokens=effective_max_tokens if explicit_budget else 0,
                estimated_tokens=estimated,
                freshness=freshness,
                warnings=resp_warnings,
                truncated=omitted_count > 0,
                evidence=[item[1]["evidence"] for item in selected_items],
                data={
                    "symbols": selected_symbols,
                    "total_matches": available_count,
                    "omitted_count": omitted_count,
                },
            )

        chosen, omitted, used = self._pack_to_budget(
            entries,
            lambda item: _json(item[1]),
            packing_budget,
            build_response,
        )
        return build_response(chosen, omitted, used)

    def file_skeleton(
        self,
        repo_id: str,
        *,
        path: str,
        include_private: bool = False,
        max_tokens: int | None = None,
        profile: str | None = None,
    ) -> dict[str, Any]:
        profile_settings = self._profile_settings(profile, "file_skeleton")
        if max_tokens is None:
            max_tokens = _profile_int(profile_settings, "budget_tokens", 1024)
        self._validate_request_bytes(repo_id=repo_id, path=path, include_private=include_private, max_tokens=max_tokens)
        self._validate_budget(max_tokens, field_name="max_tokens")
        packing_budget = self._effective_budget(max_tokens)
        repository, store, metadata = self._repository_store(repo_id)
        file_path = safe_relative_path(repository.root, path, allow_symlinks=repository.allow_symlinks)
        relative = relative_posix(repository.root, file_path)
        if is_hard_denied(relative):
            raise PathPolicyError("requested path is rejected by repository content policy")
        record = store.file(relative)
        if record is None:
            raise RetrievalError("path was not part of the active index")
        state, current_hash = self._freshness_cache.path_state(
            repository.root, record, allow_symlinks=repository.allow_symlinks
        )
        freshness = self._freshness(
            repository.root,
            store.files(),
            allow_symlinks=repository.allow_symlinks,
            metadata=metadata,
            repo_id=repository.repo_id,
        )
        stale = (state != "fresh") or (current_hash != record.sha256)
        if not stale:
            raw = file_path.read_bytes()
            source = raw.decode("utf-8", errors="replace")
        else:
            source = ""
        imports = [] if stale else _source_import_lines(source)
        symbols = store.symbols(path=relative)
        if not include_private:
            symbols = [symbol for symbol in symbols if not symbol.is_private]
        parts: list[dict[str, Any]] = []
        for line_number, line in imports:
            content, count = redact_text(line)
            parts.append({"kind": "import", "start_line": line_number, "end_line": line_number, "content": content.rstrip().replace("\r\n", "\n"), "redacted_lines": count})
        for symbol in symbols:
            if stale:
                content, count = None, 0
            else:
                header = _source_bytes(source, symbol.start_byte, symbol.body_start_byte or symbol.end_byte)
                content, count = redact_text(header)
            parts.append(
                {
                    "kind": symbol.kind,
                    "symbol_id": symbol.symbol_id,
                    "start_line": symbol.start_line,
                    "end_line": symbol.end_line,
                    "content": content.strip().replace("\r\n", "\n") if content is not None else None,
                    "redacted_lines": count,
                    "body_elided": symbol.body_start_byte is not None and not stale,
                }
            )
        warnings: list[str] = []
        if stale:
            warnings.append("indexed_hash_differs_from_current_file")
            warnings.append("stale_content_unavailable")
        if any(item["redacted_lines"] for item in parts):
            warnings.append("potential_secrets_redacted")
        imported_modules = store.imports_for_path(relative)
        imported_by = store.importers_for_modules(_module_candidates(relative))
        def build_response(selected_items: list[dict[str, Any]], omitted_items: list[dict[str, Any]], estimated: int) -> dict[str, Any]:
            return self._envelope(
                repo_id,
                metadata,
                requested_tokens=max_tokens,
                estimated_tokens=estimated,
                freshness=freshness,
                warnings=warnings,
                truncated=bool(omitted_items),
                evidence=[Evidence(relative, 1, max(1, source.count("\n") + 1), record.sha256).as_dict()],
                data={
                    "path": relative,
                    "source_sha256": record.sha256[:12],
                    "imports": len(imported_modules),
                    "imported_by": len(imported_by),
                    "skeleton": selected_items,
                    "omitted_count": len(omitted_items),
                    "estimator_version": ESTIMATOR_VERSION,
                },
            )

        chosen, omitted, used = self._pack_to_budget(parts, lambda item: _json(item), packing_budget, build_response)
        return build_response(chosen, omitted, used)

    def module_dependents(
        self,
        repo_id: str,
        *,
        path: str | None = None,
        module: str | None = None,
        max_tokens: int | None = None,
        profile: str | None = None,
    ) -> dict[str, Any]:
        profile_settings = self._profile_settings(profile, "get_module_dependents")
        if max_tokens is None and "budget_tokens" in profile_settings:
            max_tokens = _profile_int(
                profile_settings, "budget_tokens", self.config.server.max_result_tokens
            )
        if (path is None) == (module is None):
            raise RetrievalError("provide exactly one of path or module")
        effective_max_tokens = self.config.server.max_result_tokens if max_tokens is None else max_tokens
        self._validate_request_bytes(repo_id=repo_id, path=path, module=module, max_tokens=max_tokens)
        self._validate_budget(effective_max_tokens, field_name="max_tokens")
        packing_budget = self._effective_budget(effective_max_tokens)
        repository, store, metadata = self._repository_store(repo_id)

        matched_paths: list[str] = []
        if path is not None:
            file_path = safe_relative_path(repository.root, path, allow_symlinks=repository.allow_symlinks)
            relative = relative_posix(repository.root, file_path)
            if is_hard_denied(relative):
                raise PathPolicyError("requested path is rejected by repository content policy")
            if store.file(relative) is None:
                raise RetrievalError("path was not part of the active index")
            matched_paths = [relative]
            lookup_modules = _module_candidates(relative)
            query_value: dict[str, Any] = {"path": relative}
        else:
            assert module is not None
            if not module or len(module) > 200 or any(char in module for char in "\"'\n\r"):
                raise RetrievalError("module must contain 1-200 safe characters")
            lookup_modules = [module]
            matched_paths = [
                item.path for item in store.files() if module in _module_candidates(item.path)
            ]
            query_value = {"module": module}

        imported_modules = sorted(
            {
                imported
                for matched_path in matched_paths
                for imported in store.imports_for_path(matched_path)
            }
        )
        importers = store.importers_for_modules(lookup_modules)
        freshness = self._freshness(
            repository.root,
            store.files(),
            allow_symlinks=repository.allow_symlinks,
            metadata=metadata,
            repo_id=repository.repo_id,
        )
        entries: list[tuple[str, str]] = [
            ("import", item) for item in imported_modules
        ] + [("imported_by", item) for item in importers]

        def build_response(
            selected_items: list[tuple[str, str]],
            omitted_items: list[tuple[str, str]],
            estimated: int,
        ) -> dict[str, Any]:
            return self._envelope(
                repo_id,
                metadata,
                requested_tokens=effective_max_tokens,
                estimated_tokens=estimated,
                freshness=freshness,
                warnings=[
                    "imports_are_lexical_not_resolved",
                    *sorted(
                        {
                            f"dynamic_import_detected:{item.path}"
                            for item in store.files()
                            if item.path in matched_paths and "dynamic_import_detected" in item.warnings
                        }
                    ),
                ],
                truncated=bool(omitted_items),
                data={
                    "query": query_value,
                    "matched_paths": matched_paths,
                    "imports": [item for kind, item in selected_items if kind == "import"],
                    "imported_by": [item for kind, item in selected_items if kind == "imported_by"],
                    "basis": "lexical_import_statements",
                    "omitted_count": len(omitted_items),
                    "estimator_version": ESTIMATOR_VERSION,
                },
            )

        chosen, omitted, used = self._pack_to_budget(
            entries,
            lambda item: _json({"kind": item[0], "value": item[1]}),
            packing_budget,
            build_response,
        )
        response = build_response(chosen, omitted, used)
        self._assert_under_server_cap(response)
        return response

    def symbol_context(
        self,
        repo_id: str,
        *,
        symbol_id: str,
        depth: int = 1,
        include_body: bool | None = None,
        max_tokens: int | None = None,
        include_omitted_ids: bool = False,
        profile: str | None = None,
    ) -> dict[str, Any]:
        profile_settings = self._profile_settings(profile, "symbol_context")
        if max_tokens is None:
            max_tokens = _profile_int(profile_settings, "budget_tokens", 2048)
        if include_body is None:
            include_body = profile_settings.get("include_body") is True
        self._validate_request_bytes(
            repo_id=repo_id,
            symbol_id=symbol_id,
            depth=depth,
            include_body=include_body,
            max_tokens=max_tokens,
            include_omitted_ids=include_omitted_ids,
        )
        self._validate_budget(max_tokens, field_name="max_tokens")
        packing_budget = self._effective_budget(max_tokens)
        if not 0 <= depth <= 3:
            raise ArgumentOutOfRangeError("depth", depth, 0, 3)
        repository, store, metadata = self._repository_store(repo_id)
        freshness = self._freshness(
            repository.root,
            store.files(),
            allow_symlinks=repository.allow_symlinks,
            metadata=metadata,
            repo_id=repository.repo_id,
        )
        canonical_symbol_id = self._resolve_symbol_id(store, symbol_id)
        root_symbol = store.symbol(canonical_symbol_id) if canonical_symbol_id else None
        if root_symbol is None:
            stub = None
            if symbol_id.startswith("ext:"):
                stub_id_str = symbol_id[4:]
                if stub_id_str.isdigit():
                    stub = store.external_stub(int(stub_id_str))
                else:
                    for s in store.external_stubs():
                        if f"{s.package}.{s.export_path}.{s.member_name}".endswith(stub_id_str) or s.export_path == stub_id_str:
                            stub = s
                            break
            elif symbol_id.isdigit():
                stub = store.external_stub(int(symbol_id))

            if stub is not None:
                return self._envelope(
                    repo_id,
                    metadata,
                    requested_tokens=max_tokens,
                    estimated_tokens=150,
                    freshness=freshness,
                    warnings=[],
                    truncated=False,
                    evidence=[],
                    data={
                        "root_symbol_id": f"ext:{stub.stub_id}",
                        "symbols": [{
                            "symbol": {
                                "symbol_id": f"ext:{stub.stub_id}",
                                "path": f"<external:{stub.package}>",
                                "name": stub.member_name,
                                "qualified_name": f"{stub.package}.{stub.export_path}.{stub.member_name}",
                                "kind": "external_stub",
                                "signature": stub.signature,
                                "start_line": 1,
                                "end_line": 1,
                                "is_private": False,
                                "roles": ["external_stub"],
                            },
                            "content": stub.doc_summary or "",
                            "body_included": False,
                            "redacted_lines": 0,
                            "evidence": {"path": f"<external:{stub.package}>", "start_line": 1, "end_line": 1, "sha256": "external"},
                        }],
                        "edges": [],
                        "external_stub": {
                            "stub_id": stub.stub_id,
                            "package": stub.package,
                            "export_path": stub.export_path,
                            "member_name": stub.member_name,
                            "signature": stub.signature,
                            "doc_summary": stub.doc_summary,
                        },
                    },
                )
            raise RetrievalError("unknown symbol_id")
        context_ids, traversal_edges, _ = self._traverse(
            store,
            canonical_symbol_id,
            direction="both",
            depth=depth,
            max_nodes=self.config.server.max_graph_nodes,
        )
        stub_map = {}
        for edge in traversal_edges:
            if edge.target_stub_id and edge.target_stub_id not in stub_map:
                s_rec = store.external_stub(edge.target_stub_id)
                if s_rec:
                    stub_map[str(edge.target_stub_id)] = {
                        "stub_id": s_rec.stub_id,
                        "package": s_rec.package,
                        "export_path": s_rec.export_path,
                        "member_name": s_rec.member_name,
                        "signature": s_rec.signature,
                        "doc_summary": s_rec.doc_summary,
                    }
        symbols = [store.symbol(item) for item in context_ids]
        symbols = [item for item in symbols if item is not None]
        assert symbols, "root symbol must exist"
        root_symbol = symbols[0]

        warnings: list[str] = list(_edge_warnings(traversal_edges))
        extra_data: dict[str, Any] = {}

        def build_response(
            selected_items: list[tuple[str, dict[str, Any]]],
            omitted_items: list[tuple[str, dict[str, Any]]],
            estimated: int,
        ) -> dict[str, Any]:
            selected_symbols = [item for kind, item in selected_items if kind == "symbol"]
            selected_edges = [item for kind, item in selected_items if kind == "edge"]
            omitted_symbols = [item for kind, item in omitted_items if kind == "symbol"]
            omitted_edges = [item for kind, item in omitted_items if kind == "edge"]
            return self._envelope(
                repo_id,
                metadata,
                requested_tokens=max_tokens,
                estimated_tokens=estimated,
                freshness=freshness,
                warnings=warnings,
                truncated=bool(omitted_items) or ("root_body_omitted_budget" in warnings) or ("root_omitted_budget" in warnings),
                edge_precision=_edge_precision(traversal_edges),
                evidence=[item["evidence"] for item in selected_symbols],
                data={
                    "root_symbol_id": canonical_symbol_id,
                    "symbols": selected_symbols,
                    "edges": selected_edges,
                    **({"external_stubs": stub_map} if stub_map else {}),
                    **(
                        {"omitted_symbol_ids": [item["symbol"]["symbol_id"] for item in omitted_symbols[:10]]}
                        if include_omitted_ids
                        else {}
                    ),
                    "omitted_count": len(omitted_symbols),
                    "omitted_edge_count": len(omitted_edges),
                    "estimator_version": ESTIMATOR_VERSION,
                    **extra_data,
                },
            )

        root_packet = self._symbol_packet(
            repository.root,
            store,
            root_symbol,
            include_body,
            allow_symlinks=repository.allow_symlinks,
        )

        root_packet_fits = True
        if include_body:
            preview_with_body = build_response([("symbol", root_packet)], [], 0)
            tokens_with_body = _payload_tokens(preview_with_body)
            final_preview = build_response([("symbol", root_packet)], [], tokens_with_body)
            needed_with_body = _payload_tokens(final_preview)
            if needed_with_body > packing_budget:
                extra_data["root_body_tokens_needed"] = needed_with_body
                if "root_body_omitted_budget" not in warnings:
                    warnings.append("root_body_omitted_budget")
                root_packet = self._symbol_packet(
                    repository.root,
                    store,
                    root_symbol,
                    False,
                    allow_symlinks=repository.allow_symlinks,
                )

        preview_no_body = build_response([("symbol", root_packet)], [], 0)
        tokens_no_body = _payload_tokens(preview_no_body)
        final_no_body = build_response([("symbol", root_packet)], [], tokens_no_body)
        needed_no_body = _payload_tokens(final_no_body)
        if needed_no_body > packing_budget:
            extra_data["min_budget_tokens"] = needed_no_body
            if "root_omitted_budget" not in warnings:
                warnings.append("root_omitted_budget")
            root_packet_fits = False

        packets = [root_packet]
        for symbol in symbols[1:]:
            packets.append(
                self._symbol_packet(
                    repository.root,
                    store,
                    symbol,
                    False,
                    allow_symlinks=repository.allow_symlinks,
                )
            )

        for packet in packets:
            for warning in packet.get("warnings", []):
                if warning not in warnings:
                    warnings.append(warning)

        entries: list[tuple[str, dict[str, Any]]] = []
        if root_packet_fits:
            entries.append(("symbol", packets[0]))
            entries.extend(("edge", edge_as_dict(edge)) for edge in traversal_edges)
            entries.extend(("symbol", packet) for packet in packets[1:])
        else:
            entries = []

        chosen, omitted, used = self._pack_to_budget(entries, lambda item: _json(item[1]), packing_budget, build_response)
        return build_response(chosen, omitted, used)

    def impact_slice(
        self,
        repo_id: str,
        *,
        symbol_id: str,
        direction: Literal["callers", "callees", "both"] = "both",
        depth: int | None = None,
        max_nodes: int | None = None,
        max_tokens: int | None = None,
        profile: str | None = None,
        min_confidence: float | None = None,
        filter_ambiguous: bool = False,
    ) -> dict[str, Any]:
        profile_settings = self._profile_settings(profile, "impact_slice")
        if depth is None:
            depth = _profile_int(profile_settings, "depth", 2)
        if max_nodes is None and "max_nodes" in profile_settings:
            max_nodes = _profile_int(profile_settings, "max_nodes", 100)
        if max_tokens is None and "budget_tokens" in profile_settings:
            max_tokens = _profile_int(profile_settings, "budget_tokens", 2048)
        effective_max_tokens = (
            min(2048, self.config.server.max_result_tokens) if max_tokens is None else max_tokens
        )
        self._validate_request_bytes(
            repo_id=repo_id,
            symbol_id=symbol_id,
            direction=direction,
            depth=depth,
            max_nodes=max_nodes,
            max_tokens=max_tokens,
        )
        self._validate_budget(effective_max_tokens, field_name="max_tokens")
        packing_budget = self._effective_budget(effective_max_tokens)
        if direction not in {"callers", "callees", "both"}:
            raise RetrievalError("direction must be callers, callees, or both")
        if not 0 <= depth <= 3:
            raise ArgumentOutOfRangeError("depth", depth, 0, 3)
        repository, store, metadata = self._repository_store(repo_id)
        freshness = self._freshness(
            repository.root,
            store.files(),
            allow_symlinks=repository.allow_symlinks,
            metadata=metadata,
            repo_id=repository.repo_id,
        )
        if max_nodes is None:
            max_nodes = _metadata_default(metadata, "impact_max_nodes", 100)
        if not 1 <= max_nodes <= DEFAULT_MAX_GRAPH_NODES:
            raise ArgumentOutOfRangeError("max_nodes", max_nodes, 1, DEFAULT_MAX_GRAPH_NODES)
        canonical_symbol_id = self._resolve_symbol_id(store, symbol_id)
        if canonical_symbol_id is None:
            raise RetrievalError("unknown symbol_id")
        effective_max_nodes = min(max_nodes, self.config.server.max_graph_nodes)
        ids, edges, node_limit_reached = self._traverse(
            store,
            canonical_symbol_id,
            direction=direction,
            depth=depth,
            max_nodes=effective_max_nodes,
        )
        if filter_ambiguous:
            edges = [e for e in edges if e.status != "ambiguous"]
        if min_confidence is not None:
            edges = [e for e in edges if e.confidence is not None and e.confidence >= min_confidence]
        symbols = [store.symbol(item) for item in ids]
        symbols = [item for item in symbols if item]
        completeness = _completeness(edges)
        entries: list[tuple[str, dict[str, Any]]] = []
        if symbols:
            root = symbols[0]
            entries.append(
                (
                    "symbol",
                    {
                        "symbol": symbol_as_dict(root),
                        "evidence": self._evidence_for_symbol(store, root).as_dict(),
                    },
                )
            )
        entries.extend(("edge", edge_as_dict(edge)) for edge in edges)
        entries.extend(
            (
                "symbol",
                {
                    "symbol": symbol_as_dict(symbol),
                    "evidence": self._evidence_for_symbol(store, symbol).as_dict(),
                },
            )
            for symbol in symbols[1:]
        )
        warnings = [
            *_edge_warnings(edges),
            *(["graph_node_limit_capped_by_server"] if node_limit_reached else []),
        ]

        def build_response(
            selected_items: list[tuple[str, dict[str, Any]]],
            omitted_items: list[tuple[str, dict[str, Any]]],
            estimated: int,
        ) -> dict[str, Any]:
            selected_symbols = [item[1]["symbol"] for item in selected_items if item[0] == "symbol"]
            selected_edges = [item[1] for item in selected_items if item[0] == "edge"]
            selected_evidence = [item[1]["evidence"] for item in selected_items if item[0] == "symbol"]
            omitted_symbols = [item for item in omitted_items if item[0] == "symbol"]
            omitted_edges = [item for item in omitted_items if item[0] == "edge"]
            return self._envelope(
                repo_id,
                metadata,
                requested_tokens=effective_max_tokens,
                estimated_tokens=estimated,
                freshness=freshness,
                warnings=warnings,
                evidence=selected_evidence,
                completeness=completeness,
                edge_precision=_edge_precision(edges),
                truncated=bool(omitted_items) or node_limit_reached,
                data={
                    "root_symbol_id": canonical_symbol_id,
                    "direction": direction,
                    "depth": depth,
                    "symbols": selected_symbols,
                    "edges": selected_edges,
                    "nodes_visited": len(ids),
                    "node_limit_reached": node_limit_reached,
                    "omitted_count": len(omitted_symbols),
                    "omitted_edge_count": len(omitted_edges),
                    "note": "candidate impact slice; lexical edges do not prove a complete blast radius",
                },
            )

        chosen, omitted, used = self._pack_to_budget(entries, lambda item: _json(item[1]), packing_budget, build_response)
        return build_response(chosen, omitted, used)

    def _profile_settings(self, profile: str | None, tool: str) -> dict[str, object]:
        if profile is None:
            return {}
        settings = _available_profiles(self.config).get(profile)
        if settings is None:
            raise RetrievalError(f"unknown budget profile: {profile}")
        tools = settings.get("tools", [])
        if not isinstance(tools, list) or tool not in tools:
            raise RetrievalError(f"budget profile '{profile}' does not apply to {tool}")
        return settings

    def _effective_budget(self, requested_tokens: int) -> int:
        reserve = _envelope_reserve(requested_tokens)
        if requested_tokens <= reserve:
            raise RetrievalError(
                f"budget must be greater than the {reserve}-token envelope reserve"
            )
        return requested_tokens - reserve

    def _repository_store(self, repo_id: str) -> tuple[Any, SQLiteStore, dict[str, Any]]:
        repository = get_repository(self.config, repo_id)
        store = self._store(repo_id)
        try:
            metadata = store.metadata()
        except Exception as error:
            raise RetrievalError("active index missing; run the admin index command") from error
        return repository, store, metadata

    def _store(self, repo_id: str) -> SQLiteStore:
        idx_dir = index_directory(self.config_path)
        ptr_file = current_pointer_path(idx_dir, repo_id)
        now = time.monotonic()
        cached = self._pointer_cache.get(repo_id)
        if cached is not None and (now - cached[0]) <= 1.0:
            db_path = cached[1]
        else:
            db_path = None
            if ptr_file.is_file():
                try:
                    data = json.loads(ptr_file.read_text(encoding="utf-8"))
                    db_name = data.get("db")
                    if db_name:
                        cand = idx_dir / db_name
                        if cand.exists():
                            db_path = cand
                            self._pointer_cache[repo_id] = (now, cand, data.get("index_run_id"))
                except Exception:
                    pass
            if db_path is None:
                db_path = database_path(idx_dir, repo_id)
                self._pointer_cache[repo_id] = (now, db_path, None)

        return SQLiteStore(db_path, read_only=True)

    def _current_hash(self, root: Path, record: FileRecord, *, allow_symlinks: bool = False) -> str | None:
        state, sha = self._freshness_cache.path_state(root, record, allow_symlinks=allow_symlinks)
        return sha

    def _freshness(
        self,
        root: Path,
        files: list[FileRecord],
        *,
        allow_symlinks: bool = False,
        metadata: dict[str, Any] | None = None,
        repo_id: str | None = None,
    ) -> str:
        if repo_id and metadata:
            return self._freshness_cache.get_snapshot(
                repo_id,
                str(metadata.get("index_run_id", "")),
                root,
                files,
                metadata=metadata,
                allow_symlinks=allow_symlinks,
            ).status
        return "fresh" if all(self._current_hash(root, item, allow_symlinks=allow_symlinks) == item.sha256 for item in files) else "stale"

    def _repo_map_entry(
        self,
        store: SQLiteStore,
        item: tuple[SymbolRecord, float],
        *,
        file_records: dict[str, FileRecord] | None = None,
        output_format: Literal["compact", "full"] = "full",
        rank_basis: list[str] | None = None,
    ) -> dict[str, Any] | list[str]:
        symbol, score = item
        if output_format == "compact":
            # Positional fields keep the high-cardinality map cheap while the
            # server instruction documents the stable order: [id, location,
            # signature]. The short id is accepted by follow-up tools.
            entry: list[str] = [
                _compact_symbol_ref(symbol.symbol_id),
                f"{symbol.path}:{symbol.start_line}",
                _compact_declaration(symbol),
            ]
            compact_basis = _compact_rank_basis(symbol, rank_basis)
            if compact_basis:
                entry.append(compact_basis)
            return entry
        return {
            "rank": round(score, 3),
            "symbol": symbol_as_dict(symbol),
            "evidence": [self._evidence_for_symbol(store, symbol, file_records=file_records).as_dict()],
            "rank_basis": rank_basis or [],
        }

    def _pack_to_budget(
        self,
        items: list[Entry],
        render: Callable[[Entry], str],
        budget_tokens: int,
        build_response: Callable[[list[Entry], list[Entry], int], dict[str, Any]],
    ) -> tuple[list[Entry], list[Entry], int]:
        """Pack entries while accounting for the complete serialized envelope."""

        chosen, omitted, _ = pack_by_budget(items, render, budget_tokens)
        while True:
            preview = build_response(chosen, omitted, 0)
            estimated = _payload_tokens(preview)
            final = build_response(chosen, omitted, estimated)
            final_estimated = _payload_tokens(final)
            if final_estimated <= budget_tokens:
                return chosen, omitted, final_estimated
            if not chosen:
                raise RetrievalError("budget is too small for the response envelope")
            omitted.insert(0, chosen.pop())

    def _assert_under_server_cap(self, response: dict[str, Any]) -> None:
        if _payload_tokens(response) > self.config.server.max_result_tokens:
            raise RetrievalError("response exceeds configured max_result_tokens")

    def _resolve_symbol_id(self, store: SQLiteStore, symbol_id: str) -> str | None:
        if store.symbol(symbol_id) is not None:
            return symbol_id
        matches = [item.symbol_id for item in store.symbols() if _compact_symbol_ref(item.symbol_id) == symbol_id]
        return matches[0] if len(matches) == 1 else None

    def _evidence_for_symbol(
        self,
        store: SQLiteStore,
        symbol: SymbolRecord,
        *,
        file_records: dict[str, FileRecord] | None = None,
    ) -> Evidence:
        record = file_records.get(symbol.path) if file_records is not None else store.file(symbol.path)
        if record is None:
            record = store.file(symbol.path)
        assert record is not None
        return Evidence(symbol.path, symbol.start_line, symbol.end_line, record.sha256)

    def _symbol_packet(
        self,
        root: Path,
        store: SQLiteStore,
        symbol: SymbolRecord,
        include_body: bool,
        *,
        allow_symlinks: bool = False,
    ) -> dict[str, Any]:
        record = store.file(symbol.path)
        assert record is not None
        warnings: list[str] = []
        state, current_hash = self._freshness_cache.path_state(root, record, allow_symlinks=allow_symlinks)
        if state != "fresh" or current_hash != record.sha256:
            content, redacted = None, 0
            warnings.append("stale_content_unavailable")
        else:
            try:
                file_path = safe_relative_path(root, symbol.path, allow_symlinks=allow_symlinks)
                raw = file_path.read_bytes()
                source = raw.decode("utf-8", errors="replace")
                end = symbol.end_byte if include_body else (symbol.body_start_byte or symbol.end_byte)
                content, redacted = redact_text(_source_bytes(source, symbol.start_byte, end))
            except (PathPolicyError, OSError):
                content, redacted = None, 0
                warnings.append("stale_content_unavailable")
        return {
            "symbol": symbol_as_dict(symbol),
            "content": content.strip().replace("\r\n", "\n") if content is not None else None,
            "body_included": include_body,
            "redacted_lines": redacted,
            "evidence": Evidence(symbol.path, symbol.start_line, symbol.end_line, record.sha256).as_dict(),
            **({"warnings": warnings} if warnings else {}),
        }

    def _traverse(
        self,
        store: SQLiteStore,
        root_symbol_id: str,
        *,
        direction: str,
        depth: int,
        max_nodes: int,
    ) -> tuple[list[str], list[EdgeRecord], bool]:
        visited = {root_symbol_id}
        queue: deque[tuple[str, int]] = deque([(root_symbol_id, 0)])
        edges: list[EdgeRecord] = []
        node_limit_reached = False
        while queue:
            current, current_depth = queue.popleft()
            if current_depth >= depth:
                continue
            candidates: list[EdgeRecord] = []
            if direction in {"callees", "both"}:
                candidates.extend(store.edges_from(current))
            if direction in {"callers", "both"}:
                candidates.extend(store.edges_to(current))
            for edge in candidates:
                if edge not in edges:
                    edges.append(edge)
                next_id = edge.target_symbol_id if edge.source_symbol_id == current else edge.source_symbol_id
                if next_id and next_id not in visited and len(visited) >= max_nodes:
                    node_limit_reached = True
                elif next_id and next_id not in visited:
                    visited.add(next_id)
                    queue.append((next_id, current_depth + 1))
        return [root_symbol_id, *sorted(visited - {root_symbol_id})], edges, node_limit_reached

    def _envelope(
        self,
        repo_id: str,
        metadata: dict[str, Any],
        *,
        requested_tokens: int,
        estimated_tokens: int,
        freshness: str,
        warnings: list[str],
        data: dict[str, Any],
        evidence: list[dict[str, Any]] | None = None,
        completeness: dict[str, Any] | None = None,
        truncated: bool | None = None,
        edge_precision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        envelope: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "repo_id": repo_id,
            "index_run_id": metadata.get("index_run_id"),
            "freshness": freshness,
            "budget": {
                "requested_tokens": requested_tokens,
                "estimated_tokens": estimated_tokens,
                **(
                    {"envelope_reserve": _envelope_reserve(requested_tokens)}
                    if requested_tokens > 0
                    else {}
                ),
            },
            "truncated": (estimated_tokens > requested_tokens) if truncated is None else truncated,
            "completeness": completeness or {"value": None, "basis": "not_applicable"},
            "warnings": sorted(set(warnings)),
            "evidence": evidence or [],
            "data": data,
        }
        if edge_precision is not None:
            envelope["edge_precision"] = edge_precision
        return envelope

    def _validate_budget(self, value: int, *, field_name: str) -> None:
        if not 32 <= value <= self.config.server.max_result_tokens:
            raise BudgetOutOfRangeError(field_name, value, 32, self.config.server.max_result_tokens)

    def _validate_request_bytes(self, **request: object) -> None:
        encoded = json.dumps(request, sort_keys=True, default=str).encode("utf-8")
        if len(encoded) > self.config.server.max_request_bytes:
            raise RetrievalError("request exceeds configured byte limit")


def _available_profiles(config: AppConfig) -> dict[str, dict[str, object]]:
    profiles = {name: dict(settings) for name, settings in DEFAULT_BUDGET_PROFILES.items()}
    for name, settings in config.budget_profiles.items():
        profiles[name] = {**profiles.get(name, {}), **settings}
    return profiles


def _metadata_default(metadata: dict[str, Any], key: str, fallback: int) -> int:
    defaults = metadata.get("derived_defaults", {})
    if not isinstance(defaults, dict):
        return fallback
    setting = defaults.get(key, {})
    if not isinstance(setting, dict):
        return fallback
    value = setting.get("value", fallback)
    return value if isinstance(value, int) and not isinstance(value, bool) else fallback


def _envelope_reserve(requested_tokens: int) -> int:
    """Reserve wire framing room when the budget is large enough to use it.

    Very small legacy caps (below 512) cannot afford both the fixed response
    envelope and a useful result. They retain the pre-X1 service-level
    packing behavior; normal budgets, including every shipped profile, use
    the full 96-token reserve.
    """

    return ENVELOPE_RESERVE_TOKENS if requested_tokens >= 512 else 0


def _profile_int(settings: dict[str, object], key: str, default: int) -> int:
    value = settings.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RetrievalError(f"budget profile field '{key}' must be an integer")
    return value


def _profile_str(settings: dict[str, object], key: str, default: str) -> str:
    value = settings.get(key, default)
    if not isinstance(value, str):
        raise RetrievalError(f"budget profile field '{key}' must be a string")
    return value


def _repository_list_response(
    repo_ids: list[str], *, profiles: dict[str, dict[str, object]], truncated: bool
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "repo_ids": repo_ids,
        "budget_profiles": profiles,
        "truncated": truncated,
    }


def _compact_symbol_ref(symbol_id: str) -> str:
    """Return a short, stable repo-scoped reference for follow-up tool calls."""

    return hashlib.sha256(symbol_id.encode("utf-8")).hexdigest()[:8]


def _compact_declaration(symbol: SymbolRecord) -> str:
    """Return the readable, low-cardinality declaration used by compact maps."""
    kind = {"class": "c", "function": "f", "method": "m"}.get(symbol.kind, "s")
    return f"{kind} {symbol.name}"


def _compact_rank_basis(symbol: SymbolRecord, rank_basis: list[str] | None) -> str | None:
    """Return a one-character structural signal for compact entries.

    Full entries carry the detailed ``rank_basis`` list. Compact maps only
    need to tell a caller that a structural signal was present; keeping that
    marker to one byte preserves the breadth contract of the compact format.
    """

    del rank_basis  # The role is the stable, index-time evidence in compact mode.
    for role, code in (
        ("declared_entry_point", "E"),
        ("registry_wiring", "W"),
        ("protocol_definition", "D"),
        ("protocol_implementation", "I"),
        ("module_entry_point", "M"),
    ):
        if role in symbol.roles:
            return code
    return None


def _source_import_lines(source: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")) or " from " in stripped and stripped.startswith("import"):
            lines.append((number, line))
    return lines


def _source_bytes(source: str, start: int, end: int) -> str:
    raw = source.encode("utf-8")
    return raw[start:end].decode("utf-8", errors="replace").replace("\r\n", "\n")


def _looks_like_test_path(path: str) -> bool:
    lowered = path.lower()
    return "/test" in lowered or lowered.startswith("test") or ".test." in lowered or ".spec." in lowered


def _compact_map_order(
    ranked: list[tuple[SymbolRecord, float, list[str]]],
) -> list[tuple[SymbolRecord, float, list[str]]]:
    """Preserve the orientation head while amortising compact-map digests."""

    anchor = ranked[:10]
    anchor_paths = {item[0].path for item in anchor}
    same_file = [item for item in ranked[10:] if item[0].path in anchor_paths]
    new_file = [item for item in ranked[10:] if item[0].path not in anchor_paths]
    return anchor + same_file + new_file


def _module_candidates(path: str) -> list[str]:
    normalized = path.replace("\\", "/").strip("/")
    filename = normalized.rsplit("/", 1)[-1]
    without_suffix = normalized[: -len(filename)] + filename.rsplit(".", 1)[0] if "." in filename else normalized
    parts = without_suffix.split("/")
    candidates = [".".join(parts)]
    if parts and parts[0] == "src":
        candidates.append(".".join(parts[1:]))
    if parts and parts[-1] == "__init__":
        package_parts = parts[:-1]
        candidates.append(".".join(package_parts))
        if package_parts and package_parts[0] == "src":
            candidates.append(".".join(package_parts[1:]))
    return sorted({item for item in candidates if item})


def _fts_query(query: str) -> str:
    terms = _fts_terms(query)
    if not terms:
        raise RetrievalError("query must contain searchable text")
    return " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)


def _fts_terms(query: str) -> list[str]:
    return re.findall(r"[\w]+", query, flags=re.UNICODE)


def _innermost_symbol(symbols: list[SymbolRecord], line_number: int) -> SymbolRecord | None:
    enclosing = [
        sym for sym in symbols
        if sym.start_line <= line_number <= sym.end_line
    ]
    if not enclosing:
        return None
    return min(enclosing, key=lambda s: (s.end_line - s.start_line, -s.start_line))


def _score_and_select_file_matches(
    source: str,
    query: str,
    file_symbols: list[SymbolRecord],
    path: str,
) -> tuple[list[tuple[int, SymbolRecord | None]], int]:
    """Score matching lines in a file, group by innermost enclosing symbol,
    and return up to 3 best symbols (up to 2 best lines per symbol) and the count
    of unselected matching lines.
    """
    lines = source.splitlines()
    if not lines:
        return ([(1, _innermost_symbol(file_symbols, 1))], 0)

    terms = _fts_terms(query)
    valid_terms = [t for t in terms if t.strip()]
    if not valid_terms:
        return ([(1, _innermost_symbol(file_symbols, 1))], 0)

    patterns = [
        re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE)
        for term in valid_terms
    ]

    line_matches: dict[int, set[int]] = {}
    for line_num, line in enumerate(lines, start=1):
        matched = {i for i, p in enumerate(patterns) if p.search(line)}
        if matched:
            line_matches[line_num] = matched

    if not line_matches:
        lowered_terms = [t.lower() for t in valid_terms]
        for line_num, line in enumerate(lines, start=1):
            lowered = line.lower()
            matched = {i for i, t in enumerate(lowered_terms) if t in lowered}
            if matched:
                line_matches[line_num] = matched

    if not line_matches:
        return ([(1, _innermost_symbol(file_symbols, 1))], 0)

    # Group matching lines by innermost enclosing symbol
    groups: dict[str | None, dict[str, Any]] = {}
    for line_num, matched_terms in line_matches.items():
        sym = _innermost_symbol(file_symbols, line_num)
        sym_key = sym.symbol_id if sym else None
        if sym_key not in groups:
            groups[sym_key] = {
                "symbol": sym,
                "lines": [],
            }
        groups[sym_key]["lines"].append((line_num, len(matched_terms)))

    # Compute symbol scores: number of distinct query terms in symbol span
    scored_groups: list[dict[str, Any]] = []
    is_test = 1 if path.startswith(("tests/", "evals/")) else 0

    for group in groups.values():
        sym = group["symbol"]
        if sym is not None:
            distinct_terms: set[int] = set()
            for ln in range(sym.start_line, sym.end_line + 1):
                if ln in line_matches:
                    distinct_terms |= line_matches[ln]
            sym_score = len(distinct_terms)
            sym_start = sym.start_line
        else:
            distinct_terms = set()
            for ln, _ in group["lines"]:
                distinct_terms |= line_matches.get(ln, set())
            sym_score = len(distinct_terms)
            sym_start = group["lines"][0][0] if group["lines"] else 1

        # Per symbol: up to 2 best lines (highest line score, then line number)
        sorted_lines = sorted(group["lines"], key=lambda item: (-item[1], item[0]))
        best_line_score = sorted_lines[0][1] if sorted_lines else 0
        selected_lines = sorted_lines[:2]

        has_symbol = 1 if sym is not None else 0
        scored_groups.append({
            "symbol": sym,
            "has_symbol": has_symbol,
            "sym_score": sym_score,
            "best_line_score": best_line_score,
            "sym_start": sym_start,
            "lines": group["lines"],
            "selected_lines": selected_lines,
        })

    # Per file: up to 3 best symbols
    # Ordered by: symbol score desc, has_symbol desc, best line score desc, is_test asc, sym_start asc
    scored_groups.sort(
        key=lambda g: (-g["sym_score"], -g["has_symbol"], -g["best_line_score"], is_test, g["sym_start"])
    )

    selected_groups = scored_groups[:3]
    selected_line_count = sum(len(g["selected_lines"]) for g in selected_groups)
    unselected_count = len(line_matches) - selected_line_count

    # Collect result pairs: (line_num, sym)
    results: list[tuple[int, SymbolRecord | None]] = []
    for g in selected_groups:
        sym = g["symbol"]
        for ln, _ in g["selected_lines"]:
            results.append((ln, sym))

    return results, max(0, unselected_count)


def _best_matching_lines(
    source: str,
    terms: list[str],
    symbols: list[SymbolRecord],
    *,
    max_lines: int = 2,
) -> list[int]:
    lines = source.splitlines()
    if not lines:
        return [1]

    valid_terms = [t for t in terms if t.strip()]
    if not valid_terms:
        return [1]

    patterns = [
        re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE)
        for term in valid_terms
    ]

    scored_lines: list[tuple[int, int, int, int]] = []
    for line_number, line in enumerate(lines, start=1):
        score = sum(1 for p in patterns if p.search(line))
        if score > 0:
            sym = _innermost_symbol(symbols, line_number)
            has_symbol = 1 if sym is not None else 0
            span = (sym.end_line - sym.start_line) if sym else 99999999
            scored_lines.append((score, has_symbol, -span, line_number))

    if not scored_lines:
        lowered_terms = [t.lower() for t in valid_terms]
        for line_number, line in enumerate(lines, start=1):
            lowered = line.lower()
            score = sum(1 for t in lowered_terms if t in lowered)
            if score > 0:
                sym = _innermost_symbol(symbols, line_number)
                has_symbol = 1 if sym is not None else 0
                span = (sym.end_line - sym.start_line) if sym else 99999999
                scored_lines.append((score, has_symbol, -span, line_number))

    if not scored_lines:
        return [1]

    scored_lines.sort(
        key=lambda item: (item[0], item[1], item[2], -item[3]),
        reverse=True,
    )

    max_score = scored_lines[0][0]
    best_scored = [item for item in scored_lines if item[0] == max_score]
    return [item[3] for item in best_scored[:max_lines]]


def _first_matching_line(source: str, terms: list[str], symbols: list[SymbolRecord]) -> int:
    return _best_matching_lines(source, terms, symbols, max_lines=1)[0]


def _source_snippet(source: str, line_number: int, radius: int = 0) -> str:
    lines = source.splitlines()
    if not lines:
        return ""
    start = max(0, line_number - 1 - radius)
    end = min(len(lines), line_number + radius)
    snippet = "\n".join(lines[start:end])
    return snippet[:1200]


def _edge_warnings(edges: list[EdgeRecord]) -> list[str]:
    warnings: list[str] = []
    if any(edge.status == "ambiguous" for edge in edges):
        warnings.append("ambiguous_lexical_edges_present")
    if any(edge.backend == "lexical" for edge in edges):
        warnings.append("lexical_edges_are_not_complete_semantic_analysis")
    return warnings


def _completeness(edges: list[EdgeRecord]) -> dict[str, Any]:
    if not edges:
        return {"value": None, "basis": "no_edges_observed"}
    resolved = sum(edge.status == "resolved" for edge in edges)
    return {"value": round(resolved / len(edges), 3), "basis": "resolved_edges / observed_edges"}


def _edge_precision(edges: list[EdgeRecord]) -> dict[str, Any]:
    if not edges:
        return {
            "ambiguous_rate": None,
            "resolved_rate": None,
            "basis": "no_edges_observed",
        }
    total = len(edges)
    return {
        "ambiguous_rate": round(sum(edge.status == "ambiguous" for edge in edges) / total, 3),
        "resolved_rate": round(sum(edge.status == "resolved" for edge in edges) / total, 3),
        "basis": "edge_status / observed_edges",
    }


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _payload_tokens(value: Any) -> int:
    return estimate_tokens(json.dumps(value, sort_keys=True, ensure_ascii=False))

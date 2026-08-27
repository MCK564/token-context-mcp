from __future__ import annotations

from collections import deque
import json
from pathlib import Path
from typing import Any, Literal

from token_context_mcp.config import AppConfig, get_repository, index_directory
from token_context_mcp.constants import DEFAULT_MAX_GRAPH_NODES, SCHEMA_VERSION
from token_context_mcp.index.hashing import sha256_file
from token_context_mcp.index.runner import database_path
from token_context_mcp.index.sqlite_store import SQLiteStore
from token_context_mcp.models import EdgeRecord, Evidence, FileRecord, SymbolRecord, edge_as_dict, symbol_as_dict
from token_context_mcp.retrieve.ranking import rank_symbols
from token_context_mcp.retrieve.token_budget import ESTIMATOR_VERSION, estimate_tokens, pack_by_budget
from token_context_mcp.security.content_policy import redact_text
from token_context_mcp.security.path_policy import PathPolicyError, relative_posix, safe_relative_path


class RetrievalError(ValueError):
    """A read-only retrieval request cannot be fulfilled safely."""


class RetrievalService:
    def __init__(self, config: AppConfig, config_path: Path) -> None:
        self.config = config
        self.config_path = config_path

    def status(self, repo_id: str) -> dict[str, Any]:
        self._validate_request_bytes(repo_id=repo_id)
        repository = get_repository(self.config, repo_id)
        store = self._store(repository.repo_id)
        metadata = store.metadata()
        files = store.files()
        pending = [item.path for item in files if self._current_hash(repository.root, item) != item.sha256]
        return self._envelope(
            repo_id,
            metadata,
            requested_tokens=0,
            estimated_tokens=0,
            freshness="stale" if pending else "fresh",
            warnings=["network_policy_not_enforced_by_process"] if metadata.get("network_policy") else [],
            data={
                "commit_sha": metadata.get("commit_sha"),
                "generated_at": metadata.get("generated_at"),
                "files_indexed": metadata.get("files_indexed"),
                "symbols_indexed": metadata.get("symbols_indexed"),
                "edges_indexed": metadata.get("edges_indexed"),
                "pending_paths": pending[:100],
                "pending_path_count": len(pending),
                "index_warnings": metadata.get("warnings", []),
                "network_policy_status": metadata.get("network_policy_status"),
            },
        )

    def repo_map(
        self, repo_id: str, *, query: str | None = None, budget_tokens: int = 1024, include_tests: bool = False
    ) -> dict[str, Any]:
        self._validate_request_bytes(repo_id=repo_id, query=query, budget_tokens=budget_tokens, include_tests=include_tests)
        self._validate_budget(budget_tokens)
        repository, store, metadata = self._repository_store(repo_id)
        symbols = store.symbols()
        if not include_tests:
            symbols = [symbol for symbol in symbols if not _looks_like_test_path(symbol.path)]
        edges = [edge for symbol in symbols for edge in store.edges_from(symbol.symbol_id)]
        ranked = rank_symbols(symbols, edges, query)
        chosen, omitted, used = pack_by_budget(
            ranked,
            lambda item: f"{item[0].path}:{item[0].start_line} {item[0].signature}",
            budget_tokens,
        )
        selected = [
            {
                "rank": round(score, 3),
                "symbol": symbol_as_dict(symbol),
                "evidence": [self._evidence_for_symbol(store, symbol).as_dict()],
            }
            for symbol, score in chosen
        ]
        return self._envelope(
            repo_id,
            metadata,
            requested_tokens=budget_tokens,
            estimated_tokens=used,
            freshness=self._freshness(repository.root, store.files()),
            warnings=[],
            truncated=bool(omitted),
            data={
                "query": query,
                "symbols": selected,
                "omitted_symbol_ids": [symbol.symbol_id for symbol, _ in omitted[:100]],
                "omitted_count": len(omitted),
                "estimator_version": ESTIMATOR_VERSION,
            },
        )

    def find_symbols(self, repo_id: str, *, pattern: str, kind: str | None = None, limit: int = 20) -> dict[str, Any]:
        self._validate_request_bytes(repo_id=repo_id, pattern=pattern, kind=kind, limit=limit)
        if not pattern or len(pattern) > 200:
            raise RetrievalError("pattern must contain 1-200 characters")
        if not 1 <= limit <= 100:
            raise RetrievalError("limit must be between 1 and 100")
        repository, store, metadata = self._repository_store(repo_id)
        effective_limit = min(limit, self.config.server.max_symbol_results)
        symbols = store.find_symbols(pattern, kind=kind, limit=effective_limit)
        evidence = [self._evidence_for_symbol(store, symbol).as_dict() for symbol in symbols]
        return self._envelope(
            repo_id,
            metadata,
            requested_tokens=0,
            estimated_tokens=estimate_tokens(str(symbols)),
            freshness=self._freshness(repository.root, store.files()),
            warnings=["symbol_limit_capped_by_server"] if effective_limit < limit else [],
            evidence=evidence,
            data={"symbols": [symbol_as_dict(symbol) for symbol in symbols]},
        )

    def file_skeleton(
        self, repo_id: str, *, path: str, include_private: bool = False, max_tokens: int = 1024
    ) -> dict[str, Any]:
        self._validate_request_bytes(repo_id=repo_id, path=path, include_private=include_private, max_tokens=max_tokens)
        self._validate_budget(max_tokens)
        repository, store, metadata = self._repository_store(repo_id)
        file_path = safe_relative_path(repository.root, path, allow_symlinks=repository.allow_symlinks)
        relative = relative_posix(repository.root, file_path)
        record = store.file(relative)
        if record is None:
            raise RetrievalError("path was not part of the active index")
        raw = file_path.read_bytes()
        source = raw.decode("utf-8", errors="replace")
        symbols = store.symbols(path=relative)
        if not include_private:
            symbols = [symbol for symbol in symbols if not symbol.is_private]
        imports = _source_import_lines(source)
        parts: list[dict[str, Any]] = []
        for line_number, line in imports:
            content, count = redact_text(line)
            parts.append({"kind": "import", "start_line": line_number, "end_line": line_number, "content": content.rstrip(), "redacted_lines": count})
        for symbol in symbols:
            header = _source_bytes(source, symbol.start_byte, symbol.body_start_byte or symbol.end_byte)
            content, count = redact_text(header)
            parts.append(
                {
                    "kind": symbol.kind,
                    "symbol_id": symbol.symbol_id,
                    "start_line": symbol.start_line,
                    "end_line": symbol.end_line,
                    "content": content.strip(),
                    "redacted_lines": count,
                    "body_elided": symbol.body_start_byte is not None,
                }
            )
        import_parts = [item for item in parts if item["kind"] == "import"]
        symbol_parts = [item for item in parts if item["kind"] != "import"]
        chosen_imports, omitted_imports, used_imports = pack_by_budget(
            import_parts, lambda item: item["content"], max(32, max_tokens // 4)
        )
        chosen_symbols, omitted_symbols, used_symbols = pack_by_budget(
            symbol_parts, lambda item: item["content"], max_tokens - used_imports
        )
        chosen = [*chosen_imports, *chosen_symbols]
        omitted = [*omitted_imports, *omitted_symbols]
        used = used_imports + used_symbols
        warnings: list[str] = []
        if record.sha256 != sha256_file(file_path):
            warnings.append("indexed_hash_differs_from_current_file")
        if any(item["redacted_lines"] for item in chosen):
            warnings.append("potential_secrets_redacted")
        return self._envelope(
            repo_id,
            metadata,
            requested_tokens=max_tokens,
            estimated_tokens=used,
            freshness=self._freshness(repository.root, store.files()),
            warnings=warnings,
            truncated=bool(omitted),
            evidence=[Evidence(relative, 1, max(1, source.count("\n") + 1), record.sha256).as_dict()],
            data={
                "path": relative,
                "source_sha256": record.sha256,
                "skeleton": chosen,
                "omitted_count": len(omitted),
                "estimator_version": ESTIMATOR_VERSION,
            },
        )

    def symbol_context(
        self, repo_id: str, *, symbol_id: str, depth: int = 1, include_body: bool = False, max_tokens: int = 2048
    ) -> dict[str, Any]:
        self._validate_request_bytes(
            repo_id=repo_id, symbol_id=symbol_id, depth=depth, include_body=include_body, max_tokens=max_tokens
        )
        self._validate_budget(max_tokens)
        if not 0 <= depth <= 3:
            raise RetrievalError("depth must be between 0 and 3")
        repository, store, metadata = self._repository_store(repo_id)
        root_symbol = store.symbol(symbol_id)
        if root_symbol is None:
            raise RetrievalError("unknown symbol_id")
        context_ids, traversal_edges = self._traverse(
            store, symbol_id, direction="both", depth=depth, max_nodes=self.config.server.max_graph_nodes
        )
        symbols = [store.symbol(item) for item in context_ids]
        symbols = [item for item in symbols if item is not None]
        packets = [self._symbol_packet(repository.root, store, symbol, include_body and symbol.symbol_id == symbol_id) for symbol in symbols]
        chosen, omitted, used = pack_by_budget(packets, lambda item: item["content"], max_tokens)
        warnings = _edge_warnings(traversal_edges)
        return self._envelope(
            repo_id,
            metadata,
            requested_tokens=max_tokens,
            estimated_tokens=used,
            freshness=self._freshness(repository.root, store.files()),
            warnings=warnings,
            truncated=bool(omitted),
            evidence=[item["evidence"] for item in chosen],
            data={
                "root_symbol_id": symbol_id,
                "symbols": chosen,
                "edges": [edge_as_dict(edge) for edge in traversal_edges],
                "omitted_symbol_ids": [item["symbol"]["symbol_id"] for item in omitted],
                "estimator_version": ESTIMATOR_VERSION,
            },
        )

    def impact_slice(
        self,
        repo_id: str,
        *,
        symbol_id: str,
        direction: Literal["callers", "callees", "both"] = "both",
        depth: int = 2,
        max_nodes: int = 100,
    ) -> dict[str, Any]:
        self._validate_request_bytes(
            repo_id=repo_id, symbol_id=symbol_id, direction=direction, depth=depth, max_nodes=max_nodes
        )
        if direction not in {"callers", "callees", "both"}:
            raise RetrievalError("direction must be callers, callees, or both")
        if not 0 <= depth <= 3 or not 1 <= max_nodes <= DEFAULT_MAX_GRAPH_NODES:
            raise RetrievalError("depth or max_nodes outside allowed range")
        repository, store, metadata = self._repository_store(repo_id)
        if store.symbol(symbol_id) is None:
            raise RetrievalError("unknown symbol_id")
        effective_max_nodes = min(max_nodes, self.config.server.max_graph_nodes)
        ids, edges = self._traverse(store, symbol_id, direction=direction, depth=depth, max_nodes=effective_max_nodes)
        symbols = [store.symbol(item) for item in ids]
        symbols = [item for item in symbols if item]
        completeness = _completeness(edges)
        return self._envelope(
            repo_id,
            metadata,
            requested_tokens=0,
            estimated_tokens=estimate_tokens(str(symbols) + str(edges)),
            freshness=self._freshness(repository.root, store.files()),
            warnings=[
                *_edge_warnings(edges),
                *(["graph_node_limit_capped_by_server"] if effective_max_nodes < max_nodes else []),
            ],
            evidence=[self._evidence_for_symbol(store, symbol).as_dict() for symbol in symbols],
            completeness=completeness,
            data={
                "root_symbol_id": symbol_id,
                "direction": direction,
                "depth": depth,
                "symbols": [symbol_as_dict(symbol) for symbol in symbols],
                "edges": [edge_as_dict(edge) for edge in edges],
                "note": "candidate impact slice; lexical edges do not prove a complete blast radius",
            },
        )

    def _repository_store(self, repo_id: str) -> tuple[Any, SQLiteStore, dict[str, Any]]:
        repository = get_repository(self.config, repo_id)
        store = self._store(repo_id)
        try:
            metadata = store.metadata()
        except Exception as error:
            raise RetrievalError("active index missing; run the admin index command") from error
        return repository, store, metadata

    def _store(self, repo_id: str) -> SQLiteStore:
        return SQLiteStore(database_path(index_directory(self.config_path), repo_id), read_only=True)

    def _current_hash(self, root: Path, record: FileRecord) -> str | None:
        try:
            current = safe_relative_path(root, record.path)
        except PathPolicyError:
            return None
        try:
            return sha256_file(current)
        except OSError:
            return None

    def _freshness(self, root: Path, files: list[FileRecord]) -> str:
        return "fresh" if all(self._current_hash(root, item) == item.sha256 for item in files) else "stale"

    def _evidence_for_symbol(self, store: SQLiteStore, symbol: SymbolRecord) -> Evidence:
        record = store.file(symbol.path)
        assert record is not None
        return Evidence(symbol.path, symbol.start_line, symbol.end_line, record.sha256)

    def _symbol_packet(self, root: Path, store: SQLiteStore, symbol: SymbolRecord, include_body: bool) -> dict[str, Any]:
        record = store.file(symbol.path)
        assert record is not None
        file_path = safe_relative_path(root, symbol.path)
        source = file_path.read_text(encoding="utf-8", errors="replace")
        end = symbol.end_byte if include_body else (symbol.body_start_byte or symbol.end_byte)
        content, redacted = redact_text(_source_bytes(source, symbol.start_byte, end))
        return {
            "symbol": symbol_as_dict(symbol),
            "content": content.strip(),
            "body_included": include_body,
            "redacted_lines": redacted,
            "evidence": Evidence(symbol.path, symbol.start_line, symbol.end_line, record.sha256).as_dict(),
        }

    def _traverse(
        self,
        store: SQLiteStore,
        root_symbol_id: str,
        *,
        direction: str,
        depth: int,
        max_nodes: int,
    ) -> tuple[list[str], list[EdgeRecord]]:
        visited = {root_symbol_id}
        queue: deque[tuple[str, int]] = deque([(root_symbol_id, 0)])
        edges: list[EdgeRecord] = []
        while queue and len(visited) < max_nodes:
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
                if next_id and next_id not in visited and len(visited) < max_nodes:
                    visited.add(next_id)
                    queue.append((next_id, current_depth + 1))
        return [root_symbol_id, *sorted(visited - {root_symbol_id})], edges

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
    ) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "repo_id": repo_id,
            "index_run_id": metadata.get("index_run_id"),
            "freshness": freshness,
            "budget": {"requested_tokens": requested_tokens, "estimated_tokens": estimated_tokens},
            "truncated": (estimated_tokens > requested_tokens if requested_tokens else False) if truncated is None else truncated,
            "completeness": completeness or {"value": None, "basis": "not_applicable"},
            "warnings": sorted(set(warnings)),
            "evidence": evidence or [],
            "data": data,
        }

    def _validate_budget(self, value: int) -> None:
        if not 32 <= value <= self.config.server.max_result_tokens:
            raise RetrievalError(f"budget must be between 32 and {self.config.server.max_result_tokens} tokens")

    def _validate_request_bytes(self, **request: object) -> None:
        encoded = json.dumps(request, sort_keys=True, default=str).encode("utf-8")
        if len(encoded) > self.config.server.max_request_bytes:
            raise RetrievalError("request exceeds configured byte limit")


def _source_import_lines(source: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")) or " from " in stripped and stripped.startswith("import"):
            lines.append((number, line))
    return lines


def _source_bytes(source: str, start: int, end: int) -> str:
    raw = source.encode("utf-8")
    return raw[start:end].decode("utf-8", errors="replace")


def _looks_like_test_path(path: str) -> bool:
    lowered = path.lower()
    return "/test" in lowered or lowered.startswith("test") or ".test." in lowered or ".spec." in lowered


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

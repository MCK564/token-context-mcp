"""In-memory graph cache and CSR representation for retrieval and ranking."""
from __future__ import annotations

import threading
from collections import OrderedDict, defaultdict, deque
from typing import Any, Literal

from token_context_mcp.index.sqlite_store import SQLiteStore
from token_context_mcp.models import EdgeRecord, FileRecord, SymbolRecord


def _looks_like_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return (
        normalized.startswith("tests/")
        or normalized.startswith("test/")
        or "/tests/" in normalized
        or "/test/" in normalized
        or normalized.endswith("_test.py")
        or normalized.endswith("test.py")
    )


class RepoGraph:
    """In-memory representation of repository symbol graph with CSR adjacency."""

    def __init__(
        self,
        repo_id: str,
        index_run_id: str,
        symbols: list[SymbolRecord],
        edges: list[EdgeRecord],
        files: list[FileRecord] | None = None,
        global_ranks: dict[str, tuple[float, list[str]]] | None = None,
    ) -> None:
        self.repo_id = repo_id
        self.index_run_id = index_run_id
        self.symbols = symbols
        self.edges = edges
        self.files = files or []
        self.file_records: dict[str, FileRecord] = {f.path: f for f in self.files}
        self.global_ranks: dict[str, tuple[float, list[str]]] = global_ranks or {}
        self.has_global_ranks: bool = bool(global_ranks)

        # Symbol mappings
        self.symbol_map: dict[str, SymbolRecord] = {s.symbol_id: s for s in symbols}
        self.id_to_index: dict[str, int] = {s.symbol_id: i for i, s in enumerate(symbols)}
        self.index_to_id: list[str] = [s.symbol_id for s in symbols]
        node_count = len(symbols)

        # Adjacency maps for symbol_id -> EdgeRecord list
        self.out_edges: dict[str, list[EdgeRecord]] = defaultdict(list)
        self.in_edges: dict[str, list[EdgeRecord]] = defaultdict(list)
        for e in edges:
            self.out_edges[e.source_symbol_id].append(e)
            if e.target_symbol_id:
                self.in_edges[e.target_symbol_id].append(e)

        # CSR adjacency for fast traversals and algorithms
        # Outgoing edges
        out_adj: list[list[tuple[int, float, EdgeRecord]]] = [[] for _ in range(node_count)]
        in_adj: list[list[tuple[int, float, EdgeRecord]]] = [[] for _ in range(node_count)]

        for e in edges:
            src_idx = self.id_to_index.get(e.source_symbol_id)
            tgt_idx = self.id_to_index.get(e.target_symbol_id) if e.target_symbol_id else None
            conf = float(e.confidence) if e.confidence is not None else 1.0
            if src_idx is not None and tgt_idx is not None:
                out_adj[src_idx].append((tgt_idx, conf, e))
                in_adj[tgt_idx].append((src_idx, conf, e))

        # Flatten into CSR arrays
        self.out_offsets: list[int] = [0] * (node_count + 1)
        self.out_targets: list[int] = []
        self.out_weights: list[float] = []
        curr = 0
        for i in range(node_count):
            self.out_offsets[i] = curr
            for tgt, weight, _ in out_adj[i]:
                self.out_targets.append(tgt)
                self.out_weights.append(weight)
                curr += 1
        self.out_offsets[node_count] = curr

        self.in_offsets: list[int] = [0] * (node_count + 1)
        self.in_sources: list[int] = []
        self.in_weights: list[float] = []
        curr = 0
        for i in range(node_count):
            self.in_offsets[i] = curr
            for src, weight, _ in in_adj[i]:
                self.in_sources.append(src)
                self.in_weights.append(weight)
                curr += 1
        self.in_offsets[node_count] = curr

        # Pre-filter non-test symbols and their edges
        self._non_test_symbols = [s for s in symbols if not _looks_like_test_path(s.path)]
        non_test_ids = {s.symbol_id for s in self._non_test_symbols}
        self._non_test_edges = [e for e in edges if e.source_symbol_id in non_test_ids]

        # Memoization cache for repo_map entries: (symbol_id, output_format) -> entry
        self._entry_memo: dict[tuple[str, str], Any] = {}

    def symbols_filtered(self, include_tests: bool = True) -> list[SymbolRecord]:
        return self.symbols if include_tests else self._non_test_symbols

    def edges_filtered(self, include_tests: bool = True) -> list[EdgeRecord]:
        return self.edges if include_tests else self._non_test_edges

    def get_symbol(self, symbol_id: str) -> SymbolRecord | None:
        return self.symbol_map.get(symbol_id)

    def get_memo_entry(self, symbol_id: str, output_format: str) -> Any | None:
        return self._entry_memo.get((symbol_id, output_format))

    def set_memo_entry(self, symbol_id: str, output_format: str, entry: Any) -> None:
        self._entry_memo[(symbol_id, output_format)] = entry

    def traverse(
        self,
        root_symbol_id: str,
        *,
        direction: str,
        depth: int,
        max_nodes: int,
    ) -> tuple[list[str], list[EdgeRecord], bool]:
        """In-memory breadth-first traversal matching RetrievalService._traverse semantics."""
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
                candidates.extend(self.out_edges.get(current, []))
            if direction in {"callers", "both"}:
                candidates.extend(self.in_edges.get(current, []))
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


class GraphCache:
    """Thread-safe LRU cache for repository symbol graphs with max capacity 3."""

    def __init__(self, capacity: int = 3) -> None:
        self.capacity = capacity
        self._cache: OrderedDict[tuple[str, str], RepoGraph] = OrderedDict()
        self._lock = threading.Lock()

    def get_graph(
        self,
        repo_id: str,
        index_run_id: str,
        store: SQLiteStore,
    ) -> RepoGraph:
        key = (repo_id, index_run_id)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]

        # Load from store outside lock to avoid blocking readers during initialization
        symbols = store.symbols()
        edges = store.edges()
        files = store.files()
        global_ranks = store.symbol_ranks() if hasattr(store, "symbol_ranks") else {}
        graph = RepoGraph(repo_id, index_run_id, symbols, edges, files, global_ranks=global_ranks)

        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            self._cache[key] = graph
            while len(self._cache) > self.capacity:
                self._cache.popitem(last=False)
            return graph

    def invalidate(self, repo_id: str | None = None) -> None:
        with self._lock:
            if repo_id is None:
                self._cache.clear()
            else:
                to_delete = [k for k in self._cache if k[0] == repo_id]
                for k in to_delete:
                    self._cache.pop(k, None)

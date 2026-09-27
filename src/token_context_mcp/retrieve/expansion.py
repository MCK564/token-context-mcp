"""LARGER-lite: anchor lexical hits, then expand over the resolved call graph (M5.2, M5.3).

Design notes
------------
* Anchors are the top search hits. They are never reordered or removed here; expansion only
  adds a separate ``neighbors`` list, so ``expand="none"`` output stays byte-identical.
* Only edges that are ``resolved``, produced by the ``lexical`` backend (not ``virtual_stub``),
  point at a real symbol, and carry ``confidence >= min_confidence`` are traversed. With the M4
  calibration this excludes ``global`` (0.40) and ``unknown_receiver`` (0.10) edges.
* File communities come from deterministic label propagation over the undirected file import
  graph. They are computed lazily per index run and cached on the ``RepoGraph``; no schema change.
* Everything is deterministic: node order is sorted, ties break on (path, line, symbol_id).
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from token_context_mcp.retrieve.code_tokens import split_identifier

if TYPE_CHECKING:  # pragma: no cover
    from token_context_mcp.retrieve.graph_cache import RepoGraph

MODULE_SUFFIX = ":<module>"
MAX_ANCHORS = 5
COMMUNITY_BONUS = 1.2
HUB_PENALTY = 0.5
HUB_Z_THRESHOLD = 3.0
TEST_NEIGHBOR_FACTOR = 0.5
TERM_BONUS = 0.5
LPA_MAX_ROUNDS = 20


@dataclass(frozen=True)
class Neighbor:
    symbol_id: str
    path: str
    line: int
    kind: str
    name: str
    relation: str
    score: float
    anchor_id: str
    anchor_rank: int

    def as_row(self) -> list[object]:
        return [
            self.symbol_id,
            f"{self.path}:{self.line}",
            f"{self.kind} {self.name}",
            self.relation,
            round(self.score, 2),
            self.anchor_id,
        ]


def _is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    name = normalized.rsplit("/", 1)[-1]
    return (
        normalized.startswith(("tests/", "test/", "evals/"))
        or "/tests/" in normalized
        or "/test/" in normalized
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def module_names_for_path(path: str) -> set[str]:
    """Dotted module names a Python-style path can be imported as (``src/`` layout aware)."""
    normalized = path.replace("\\", "/").strip("/")
    filename = normalized.rsplit("/", 1)[-1]
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    parts = [p for p in normalized[: len(normalized) - len(filename)].split("/") if p]
    parts.append(stem)
    names = {".".join(parts)}
    if parts and parts[0] == "src":
        names.add(".".join(parts[1:]))
    if stem == "__init__":
        package = parts[:-1]
        if package:
            names.add(".".join(package))
            if package[0] == "src" and len(package) > 1:
                names.add(".".join(package[1:]))
    return {n for n in names if n}


def file_communities(paths: Iterable[str], imports: Iterable[tuple[str, str]]) -> dict[str, int]:
    """Deterministic label propagation over the undirected in-repo file import graph."""
    nodes = sorted(set(paths))
    module_to_path: dict[str, str] = {}
    for path in nodes:
        for name in sorted(module_names_for_path(path)):
            module_to_path.setdefault(name, path)
    adjacency: dict[str, set[str]] = {path: set() for path in nodes}
    for source, module in imports:
        if source not in adjacency:
            continue
        target = module_to_path.get(module)
        if target is None and "." in module:
            # ``from pkg.mod import Name`` may be stored as ``pkg.mod.Name``.
            target = module_to_path.get(module.rsplit(".", 1)[0])
        if target is None or target == source:
            continue
        adjacency[source].add(target)
        adjacency[target].add(source)

    label = {path: index for index, path in enumerate(nodes)}
    for _ in range(LPA_MAX_ROUNDS):
        changed = False
        for path in nodes:
            neighbours = adjacency[path]
            if not neighbours:
                continue
            counts = Counter(label[other] for other in neighbours)
            best = max(counts.values())
            candidate = min(lab for lab, count in counts.items() if count == best)
            if candidate != label[path]:
                label[path] = candidate
                changed = True
        if not changed:
            break
    # Renumber densely in order of first appearance for stable, readable ids.
    dense: dict[int, int] = {}
    return {path: dense.setdefault(label[path], len(dense)) for path in nodes}


def _edge_ok(edge: object, min_confidence: float) -> bool:
    return (
        getattr(edge, "status", None) == "resolved"
        and getattr(edge, "backend", None) == "lexical"
        and getattr(edge, "target_symbol_id", None) is not None
        and getattr(edge, "confidence", None) is not None
        and float(edge.confidence) >= min_confidence  # type: ignore[attr-defined]
    )


def hub_ids(graph: "RepoGraph", min_confidence: float) -> frozenset[str]:
    """Symbols whose in-degree over traversable edges has z-score > HUB_Z_THRESHOLD."""
    cache: dict[float, frozenset[str]] = graph.__dict__.setdefault("_hub_cache", {})
    if min_confidence in cache:
        return cache[min_confidence]
    indegree: Counter[str] = Counter()
    for edge in graph.edges:
        if _edge_ok(edge, min_confidence):
            indegree[edge.target_symbol_id] += 1  # type: ignore[index]
    values = [indegree.get(s.symbol_id, 0) for s in graph.symbols]
    hubs: frozenset[str] = frozenset()
    if len(values) > 1:
        mean = sum(values) / len(values)
        std = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
        if std > 0:
            hubs = frozenset(
                sid for sid, deg in indegree.items() if (deg - mean) / std > HUB_Z_THRESHOLD
            )
    cache[min_confidence] = hubs
    return hubs


def communities_for(graph: "RepoGraph", imports: Iterable[tuple[str, str]] | None) -> dict[str, int]:
    cached = graph.__dict__.get("_community_cache")
    if cached is not None:
        return cached
    paths = [f.path for f in graph.files] or sorted({s.path for s in graph.symbols})
    communities = file_communities(paths, imports or [])
    graph.__dict__["_community_cache"] = communities
    return communities


def expand_anchors(
    graph: "RepoGraph",
    anchor_ids: list[str],
    query: str,
    *,
    k: int,
    hops: int,
    min_confidence: float,
    communities: dict[str, int],
) -> tuple[list[Neighbor], int]:
    """Return (neighbors, number_of_anchors_expanded)."""
    anchors = anchor_ids[:MAX_ANCHORS]
    anchor_set = set(anchor_ids)
    query_terms = {t for raw in query.lower().split() for t in split_identifier(raw) if len(t) > 1}
    hubs = hub_ids(graph, min_confidence)

    best: dict[str, Neighbor] = {}
    expanded = 0
    for rank, anchor_id in enumerate(anchors):
        if anchor_id.endswith(MODULE_SUFFIX) or anchor_id not in graph.symbol_map:
            continue
        expanded += 1
        anchor_path = graph.symbol_map[anchor_id].path
        anchor_comm = communities.get(anchor_path)
        # best path product and first-hop relation per reachable node
        reach: dict[str, tuple[float, str]] = {}
        frontier: list[tuple[str, float, str | None]] = [(anchor_id, 1.0, None)]
        for _ in range(hops):
            next_frontier: list[tuple[str, float, str | None]] = []
            for node, weight, relation in frontier:
                steps: list[tuple[str, float, str]] = []
                for edge in graph.out_edges.get(node, []):
                    if _edge_ok(edge, min_confidence):
                        steps.append((edge.target_symbol_id, float(edge.confidence), "callee"))  # type: ignore[arg-type]
                for edge in graph.in_edges.get(node, []):
                    if _edge_ok(edge, min_confidence):
                        steps.append((edge.source_symbol_id, float(edge.confidence), "caller"))  # type: ignore[arg-type]
                for other, conf, step_rel in sorted(steps):
                    if other == anchor_id or other.endswith(MODULE_SUFFIX) or other not in graph.symbol_map:
                        continue
                    product = weight * conf
                    rel = relation or step_rel
                    if other not in reach or product > reach[other][0]:
                        reach[other] = (product, rel)
                        next_frontier.append((other, product, rel))
            frontier = next_frontier

        candidates: list[Neighbor] = []
        for sid, (product, rel) in reach.items():
            if sid in anchor_set:
                continue
            sym = graph.symbol_map[sid]
            score = product
            if anchor_comm is not None and communities.get(sym.path) == anchor_comm:
                score *= COMMUNITY_BONUS
            if sid in hubs:
                score *= HUB_PENALTY
            relation = rel
            if _is_test_path(sym.path):
                relation = "test"
                score *= TEST_NEIGHBOR_FACTOR
            name_terms = set(split_identifier(sym.name))
            score *= 1 + TERM_BONUS * len(query_terms & name_terms)
            candidates.append(
                Neighbor(sid, sym.path, sym.start_line, sym.kind, sym.name, relation, score, anchor_id, rank)
            )
        candidates.sort(key=lambda n: (-n.score, n.path, n.line, n.symbol_id))
        for neighbor in candidates[:k]:
            current = best.get(neighbor.symbol_id)
            if current is None or neighbor.score > current.score:
                best[neighbor.symbol_id] = neighbor

    ordered = sorted(best.values(), key=lambda n: (n.anchor_rank, -n.score, n.path, n.line, n.symbol_id))
    return ordered, expanded

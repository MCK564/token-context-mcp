from __future__ import annotations

import math
import re
from collections import defaultdict

from token_context_mcp.models import EdgeRecord, SymbolRecord

DEFAULT_PATH_CLASS_DEMOTIONS = {"scripts": 1.5, "evaluation": 1.0}
ROLE_BONUSES = {
    # Structural evidence is deliberately stronger than a raw degree count,
    # but remains modest enough that well-connected application symbols can
    # still surface in an orientation map. These values were selected against
    # evals/relevance/orientation_invoice_scanner.json; they are not keyword
    # weights and must be re-evaluated when a query-labelled set is added.
    "declared_entry_point": 3.0,
    "registry_wiring": 2.4,
    "protocol_definition": 2.1,
    "protocol_implementation": 1.8,
    "module_entry_point": 0.9,
}


def rank_symbols(
    symbols: list[SymbolRecord],
    edges: list[EdgeRecord],
    query: str | None,
    *,
    body_matches: set[str] | None = None,
) -> list[tuple[SymbolRecord, float, list[str]]]:
    incoming: dict[str, int] = defaultdict(int)
    outgoing: dict[str, int] = defaultdict(int)
    for edge in edges:
        outgoing[edge.source_symbol_id] += 1
        if edge.target_symbol_id:
            incoming[edge.target_symbol_id] += 1
    terms = _expanded_query_terms(query)
    seed_biased = bool(query or body_matches)
    ppr = _personalized_random_walk(symbols, edges, query=query, body_matches=body_matches) if seed_biased else {}
    ranked: list[tuple[SymbolRecord, float, list[str]]] = []
    for symbol in symbols:
        # These weights are intentionally fixed until a labelled relevance
        # evaluation exists; exposing unevaluated guesses as config would not
        # improve ranking quality.
        incoming_count = incoming[symbol.symbol_id]
        outgoing_count = outgoing[symbol.symbol_id]
        if outgoing_count == 0:
            degree_shape = 0.0  # pure sink: utility/data leaf
            basis = ["degree_shape:pure_sink"]
        elif incoming_count <= 1:
            degree_shape = 0.5  # near-source: script root or weakly connected code
            basis = ["degree_shape:near_source"]
        else:
            # Preserve a small connector tie-break without letting raw degree
            # turn high-use helpers into architecture by themselves.
            degree_shape = 1.0 + min(incoming_count, 5) * 0.2 + min(outgoing_count, 5) * 0.2
            basis = ["degree_shape:connector"]
        score = 1.0 + degree_shape
        name_haystack = f"{symbol.name} {symbol.qualified_name} {symbol.signature}"
        query_bonus = 8.0 * _term_match_count(name_haystack, terms)
        if query_bonus:
            score += query_bonus
            basis.append("query_match")
        exact_name_matches = _term_match_count(f"{symbol.name} {symbol.qualified_name}", terms)
        if exact_name_matches:
            score += 8.0 * exact_name_matches
            basis.append(f"name_match:{exact_name_matches}")
            if symbol.kind in {"class", "interface"}:
                score += 10.0
                basis.append("query_class_match")
        path_matches = _term_match_count(symbol.path, terms)
        if path_matches:
            score += 5.0 * path_matches
            basis.append(f"path_match:{path_matches}")
        stage_match = _stage_path_match(symbol.path, terms)
        if stage_match:
            score += 12.0
            basis.append(f"stage_path:{stage_match}")
        if symbol.symbol_id in (body_matches or set()):
            score += 12.0
            basis.append("body_match")
        if seed_biased:
            walk_score = ppr.get(symbol.symbol_id, 0.0)
            score += 1.5 * math.sqrt(max(0.0, walk_score))
            if walk_score > 0:
                basis.append(f"seed_walk:{walk_score:.3f}")
        for role in symbol.roles:
            bonus = ROLE_BONUSES.get(role, 0.0)
            if bonus:
                score += bonus * (2.0 if seed_biased else 1.0)
                basis.append(f"role:{role}")
        path_class = symbol.path.replace("\\", "/").split("/", 1)[0]
        if path_class in DEFAULT_PATH_CLASS_DEMOTIONS:
            score -= DEFAULT_PATH_CLASS_DEMOTIONS[path_class]
            basis.append(f"path_class:-{path_class}")
        if symbol.kind in {"class", "interface"}:
            score += 0.25
            basis.append("kind:class_or_interface")
        ranked.append((symbol, score, basis))
    return sorted(ranked, key=lambda item: (-item[1], item[0].path, item[0].start_line))


def _personalized_random_walk(
    symbols: list[SymbolRecord],
    edges: list[EdgeRecord],
    *,
    query: str | None,
    body_matches: set[str] | None,
) -> dict[str, float]:
    """Return a deterministic query-personalized walk over observed edges.

    This is deliberately a small, local PPR-style scorer rather than a claim
    of semantic call-graph completeness. Resolved lexical edges form an
    undirected neighborhood so a query can reach callers and callees; edges
    without a target symbol are excluded because they are ambiguous. The
    final scores are normalized around one, making the walk a bounded ranking
    signal instead of a repository-size-dependent raw probability.
    """

    symbol_ids = {symbol.symbol_id for symbol in symbols}
    adjacency: dict[str, set[str]] = {symbol_id: set() for symbol_id in symbol_ids}
    for edge in edges:
        if edge.target_symbol_id in symbol_ids and edge.source_symbol_id in symbol_ids:
            adjacency[edge.source_symbol_id].add(edge.target_symbol_id)
            adjacency[edge.target_symbol_id].add(edge.source_symbol_id)

    terms = _expanded_query_terms(query)
    teleport: dict[str, float] = {}
    for symbol in symbols:
        name_haystack = f"{symbol.name} {symbol.qualified_name} {symbol.signature}"
        name_matches = _term_match_count(name_haystack, terms)
        path_matches = _term_match_count(symbol.path, terms)
        body_match = symbol.symbol_id in (body_matches or set())
        if name_matches or path_matches or body_match:
            teleport[symbol.symbol_id] = (
                1.0
                + 1.25 * name_matches
                + 0.75 * path_matches
                + (1.5 if body_match else 0.0)
            )
    if not teleport:
        return {symbol_id: 1.0 for symbol_id in symbol_ids}
    total = sum(teleport.values())
    teleport = {symbol_id: value / total for symbol_id, value in teleport.items()}

    scores = {symbol_id: teleport.get(symbol_id, 0.0) for symbol_id in symbol_ids}
    damping = 0.85
    for _ in range(20):
        next_scores = {symbol_id: (1.0 - damping) * teleport.get(symbol_id, 0.0) for symbol_id in symbol_ids}
        dangling = sum(scores[symbol_id] for symbol_id, neighbors in adjacency.items() if not neighbors)
        for symbol_id in symbol_ids:
            neighbors = adjacency[symbol_id]
            if neighbors:
                share = damping * scores[symbol_id] / len(neighbors)
                for neighbor in neighbors:
                    next_scores[neighbor] += share
        if dangling:
            for symbol_id, probability in teleport.items():
                next_scores[symbol_id] += damping * dangling * probability
        scores = next_scores

    mean = sum(scores.values()) / max(1, len(scores))
    if math.isclose(mean, 0.0):
        return {symbol_id: 0.0 for symbol_id in symbol_ids}
    return {symbol_id: probability / mean for symbol_id, probability in scores.items()}


def _expanded_query_terms(query: str | None) -> set[str]:
    """Expand a few ordinary English/code morphology variants for seeding.

    This is intentionally a small deterministic vocabulary, not an embedding
    model. It lets ``registry`` reach ``register`` and ``recognition`` reach
    ``recognise`` while keeping the ranking explainable in ``rank_basis``.
    """

    terms = {part.lower() for part in (query or "").replace("/", " ").replace("_", " ").split() if part}
    expansions = {
        "registry": {"register", "registry"},
        "registration": {"register", "registry"},
        "selection": {"select", "get", "lookup"},
        "recognition": {"recognize", "recognise", "ocr"},
        "extraction": {"extract"},
        "detection": {"detect"},
        "geometry": {"geom", "geometry"},
        "rendering": {"render", "renderer"},
    }
    for term in tuple(terms):
        terms.update(expansions.get(term, set()))
    return terms


def _stage_path_match(path: str, terms: set[str]) -> str | None:
    """Recognize a query term in a conventional numbered pipeline filename."""

    filename = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    stem = filename.rsplit(".", 1)[0]
    for term in sorted(terms):
        if f"_{term}" in stem and any(char.isdigit() for char in stem.split("_", 1)[0]):
            return term
    return None


def _term_match_count(text: str, terms: set[str]) -> int:
    tokens = set(re.findall(r"[a-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower()))
    return sum(term in tokens for term in terms)

from __future__ import annotations

import math
import re
from collections import defaultdict, deque

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


def compute_global_ranks(
    symbols: list[SymbolRecord],
    edges: list[EdgeRecord],
) -> list[tuple[str, float, list[str]]]:
    """Compute weighted PageRank at index time and return (symbol_id, score, basis) tuples.

    Rules:
    - Only edges with confidence >= 0.6 and resolved target_symbol_id.
    - Forward weight (towards callee) is 1.0; reverse is 0.3.
    - Utility trap dampening: symbol with in-degree z-score > 3.0 and out-degree <= 2 score * 0.5.
    - Role bonuses and path class demotions applied.
    """
    if not symbols:
        return []

    symbol_ids = {s.symbol_id for s in symbols}
    valid_edges = [
        e for e in edges
        if e.target_symbol_id in symbol_ids
        and e.source_symbol_id in symbol_ids
        and e.confidence is not None
        and e.confidence >= 0.6
    ]

    in_degree: dict[str, int] = defaultdict(int)
    out_degree: dict[str, int] = defaultdict(int)
    out_adj: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    in_adj: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for e in valid_edges:
        src = e.source_symbol_id
        tgt = e.target_symbol_id
        assert tgt is not None
        conf = float(e.confidence)
        in_degree[tgt] += 1
        out_degree[src] += 1
        # Forward weight 1.0 (towards callee), reverse 0.3
        out_adj[src][tgt] += 1.0 * conf
        out_adj[tgt][src] += 0.3 * conf
        in_adj[tgt][src] += 1.0 * conf
        in_adj[src][tgt] += 0.3 * conf

    N = len(symbols)
    d = 0.85
    p = {s.symbol_id: 1.0 / N for s in symbols}
    out_sum = {s.symbol_id: sum(out_adj[s.symbol_id].values()) for s in symbols}

    for _ in range(30):
        dangling_mass = sum(p[s.symbol_id] for s in symbols if out_sum[s.symbol_id] == 0)
        p_next = {}
        for s in symbols:
            sid = s.symbol_id
            val = (1.0 - d) / N + d * dangling_mass / N
            for src, weight in in_adj[sid].items():
                if out_sum[src] > 0:
                    val += d * p[src] * (weight / out_sum[src])
            p_next[sid] = val
        p = p_next

    mean_p = sum(p.values()) / N
    pr = {sid: val / mean_p if mean_p > 0 else 1.0 for sid, val in p.items()}

    mean_in = sum(in_degree.values()) / N
    var_in = sum((in_degree[s.symbol_id] - mean_in) ** 2 for s in symbols) / N
    std_in = math.sqrt(var_in)

    scored: list[tuple[str, float, list[str]]] = []
    for s in symbols:
        sid = s.symbol_id
        score = pr[sid]
        basis = [f"pagerank:{score:.3f}"]

        # Utility trap dampening: in-degree z-score > 3 and out-degree <= 2
        z_in = (in_degree[sid] - mean_in) / std_in if std_in > 0 else 0.0
        if z_in > 3.0 and out_degree[sid] <= 2:
            score *= 0.5
            basis.append("utility_trap_dampened")

        # Role bonuses
        for r in s.roles:
            bonus = ROLE_BONUSES.get(r, 0.0)
            if bonus:
                score += bonus
                basis.append(f"role:{r}")

        # Path class demotions
        p_class = s.path.replace("\\", "/").split("/", 1)[0]
        if p_class in DEFAULT_PATH_CLASS_DEMOTIONS:
            score -= DEFAULT_PATH_CLASS_DEMOTIONS[p_class]
            basis.append(f"path_class:-{p_class}")

        if s.kind in {"class", "interface"}:
            score += 0.25
            basis.append("kind:class_or_interface")

        basis.append(f"in_degree:{in_degree[sid]}")
        scored.append((sid, round(score, 6), basis))

    return scored


def local_push_ppr(
    symbols: list[SymbolRecord],
    edges: list[EdgeRecord],
    *,
    query: str | None,
    body_matches: set[str] | None,
    eps: float = 1e-4,
    alpha: float = 0.15,
    query_expansions: dict[str, list[str]] | None = None,
) -> dict[str, float]:
    """Andersen-Chung-Lang local push Personalized PageRank algorithm."""
    symbol_ids = {s.symbol_id for s in symbols}
    if not symbol_ids:
        return {}

    # Build weighted undirected graph, pruning edges with confidence < 0.5
    adjacency: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for edge in edges:
        if (
            edge.target_symbol_id in symbol_ids
            and edge.source_symbol_id in symbol_ids
            and edge.confidence is not None
            and edge.confidence >= 0.5
        ):
            conf = float(edge.confidence)
            src = edge.source_symbol_id
            tgt = edge.target_symbol_id
            assert tgt is not None
            adjacency[src][tgt] += conf
            adjacency[tgt][src] += conf

    deg: dict[str, float] = {sid: sum(adjacency[sid].values()) for sid in symbol_ids}

    terms = _expanded_query_terms(query, query_expansions)
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

    total_teleport = sum(teleport.values())
    teleport = {sid: val / total_teleport for sid, val in teleport.items()}

    # Initialize PageRank vector p and residual vector r
    p: dict[str, float] = defaultdict(float)
    r: dict[str, float] = defaultdict(float)
    for sid, val in teleport.items():
        r[sid] = val

    queue: deque[str] = deque()
    in_queue: set[str] = set()

    for sid in symbol_ids:
        d_val = deg[sid]
        if d_val == 0.0 and r[sid] > 0:
            queue.append(sid)
            in_queue.add(sid)
        elif d_val > 0 and r[sid] >= eps * d_val:
            queue.append(sid)
            in_queue.add(sid)

    max_pushes = 100_000
    pushes = 0

    while queue and pushes < max_pushes:
        u = queue.popleft()
        in_queue.discard(u)
        d_u = deg[u]

        if d_u == 0.0:
            p[u] += r[u]
            r[u] = 0.0
            continue

        if r[u] < eps * d_u:
            continue

        push_val = r[u]
        r[u] = 0.0
        p[u] += alpha * push_val
        mass_to_distribute = (1.0 - alpha) * push_val

        pushes += 1

        for v, weight in adjacency[u].items():
            r[v] += mass_to_distribute * (weight / d_u)
            d_v = deg[v]
            if d_v > 0 and r[v] >= eps * d_v and v not in in_queue:
                queue.append(v)
                in_queue.add(v)

    # Any remaining residual mass on isolated nodes
    for sid in symbol_ids:
        if deg[sid] == 0.0 and r[sid] > 0:
            p[sid] += r[sid]
            r[sid] = 0.0

    scores = {sid: p.get(sid, 0.0) for sid in symbol_ids}
    mean = sum(scores.values()) / max(1, len(scores))
    if math.isclose(mean, 0.0):
        return {symbol_id: 0.0 for symbol_id in symbol_ids}
    return {symbol_id: val / mean for symbol_id, val in scores.items()}


_personalized_random_walk = local_push_ppr


def rank_symbols(
    symbols: list[SymbolRecord],
    edges: list[EdgeRecord],
    query: str | None,
    *,
    body_matches: set[str] | None = None,
    global_ranks: dict[str, tuple[float, list[str]]] | None = None,
    query_expansions: dict[str, list[str]] | None = None,
    stage_prefix_pattern: str | None = None,
) -> list[tuple[SymbolRecord, float, list[str]]]:
    seed_biased = bool(query or body_matches)

    incoming: dict[str, int] = defaultdict(int)
    outgoing: dict[str, int] = defaultdict(int)
    for edge in edges:
        outgoing[edge.source_symbol_id] += 1
        if edge.target_symbol_id:
            incoming[edge.target_symbol_id] += 1

    # Global mode: query is None and no body_matches
    if not seed_biased and global_ranks:
        ranked_global: list[tuple[SymbolRecord, float, list[str], int]] = []
        for symbol in symbols:
            sid = symbol.symbol_id
            if sid in global_ranks:
                score, basis = global_ranks[sid]
            else:
                score = 1.0
                basis = ["fallback_no_global_rank"]
            indeg = incoming[sid]
            ranked_global.append((symbol, score, basis, indeg))
        ranked_global.sort(key=lambda item: (-item[1], -item[3], item[0].path, item[0].start_line))
        return [(s, score, basis) for s, score, basis, _ in ranked_global]

    # Seed-biased mode or global fallback when no global_ranks
    terms = _expanded_query_terms(query, query_expansions)
    ppr = (
        local_push_ppr(
            symbols,
            edges,
            query=query,
            body_matches=body_matches,
            query_expansions=query_expansions,
        )
        if seed_biased
        else {}
    )

    ranked: list[tuple[SymbolRecord, float, list[str]]] = []
    for symbol in symbols:
        incoming_count = incoming[symbol.symbol_id]
        outgoing_count = outgoing[symbol.symbol_id]
        if outgoing_count == 0:
            degree_shape = 0.0
            basis = ["degree_shape:pure_sink"]
        elif incoming_count <= 1:
            degree_shape = 0.5
            basis = ["degree_shape:near_source"]
        else:
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
        stage_match = _stage_path_match(symbol.path, terms, stage_prefix_pattern)
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


def _expanded_query_terms(
    query: str | None,
    query_expansions: dict[str, list[str]] | None = None,
) -> set[str]:
    """Expand morphology variants for seeding, using configured expansions."""
    terms = {part.lower() for part in (query or "").replace("/", " ").replace("_", " ").split() if part}
    expansions = query_expansions or {}
    for term in tuple(terms):
        for exp in expansions.get(term, []):
            terms.add(exp.lower())
    return terms


def _stage_path_match(
    path: str,
    terms: set[str],
    stage_prefix_pattern: str | None = None,
) -> str | None:
    """Recognize a query term in a pipeline filename matching stage_prefix_pattern."""
    if not stage_prefix_pattern:
        return None
    filename = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    stem = filename.rsplit(".", 1)[0]
    try:
        if not re.search(stage_prefix_pattern, stem):
            return None
    except re.error:
        return None
    for term in sorted(terms):
        if term in stem:
            return term
    return None


def _term_match_count(text: str, terms: set[str]) -> int:
    tokens = set(re.findall(r"[a-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower()))
    return sum(term in tokens for term in terms)

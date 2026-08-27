from __future__ import annotations

from collections import defaultdict

from token_context_mcp.models import EdgeRecord, SymbolRecord


def rank_symbols(symbols: list[SymbolRecord], edges: list[EdgeRecord], query: str | None) -> list[tuple[SymbolRecord, float]]:
    incoming: dict[str, int] = defaultdict(int)
    outgoing: dict[str, int] = defaultdict(int)
    for edge in edges:
        outgoing[edge.source_symbol_id] += 1
        if edge.target_symbol_id:
            incoming[edge.target_symbol_id] += 1
    terms = {part.lower() for part in (query or "").replace("/", " ").replace("_", " ").split() if part}
    ranked: list[tuple[SymbolRecord, float]] = []
    for symbol in symbols:
        score = 1.0 + incoming[symbol.symbol_id] * 2.0 + outgoing[symbol.symbol_id] * 0.5
        haystack = f"{symbol.path} {symbol.name} {symbol.qualified_name} {symbol.signature}".lower()
        score += sum(8.0 for term in terms if term in haystack)
        if symbol.kind in {"class", "interface"}:
            score += 0.25
        ranked.append((symbol, score))
    return sorted(ranked, key=lambda item: (-item[1], item[0].path, item[0].start_line))


"""Verifier and fallback guardrails for hallucination detection and symbol grounding."""
from __future__ import annotations

import re
from typing import Sequence

from token_context_mcp.sampling.schema import CodeSummaryPayload, SymbolAnalysis


def is_symbol_grounded(symbol_name: str, verified_anchors: Sequence[str]) -> bool:
    """Check if an analyzed symbol name matches any verified anchor directly or via qualified suffix."""
    if not verified_anchors:
        return True
    cleaned_name = symbol_name.strip()
    # Direct match
    if cleaned_name in verified_anchors:
        return True
    # Qualified name match (e.g., "PaymentService.refund" matching "refund" or "PaymentService")
    parts = cleaned_name.split(".")
    for part in parts:
        if part in verified_anchors:
            return True
    # Reverse qualified check (anchor "PaymentService.refund" matching "refund")
    for anchor in verified_anchors:
        if cleaned_name in anchor.split("."):
            return True
    return False


def verify_and_guard(
    payload: CodeSummaryPayload,
    verified_anchors: Sequence[str],
) -> tuple[CodeSummaryPayload, float, float]:
    """Filter hallucinated symbols and compute symbol coverage and retention rates.
    
    Returns:
        (guarded_payload, symbol_coverage_rate, context_retention_rate)
    """
    if not verified_anchors:
        return payload, 1.0, 1.0

    grounded_symbols: list[SymbolAnalysis] = []
    for item in payload.analyzed_symbols:
        if is_symbol_grounded(item.name, verified_anchors):
            grounded_symbols.append(item)

    # Compute symbol coverage rate: how many analyzed symbols are legitimately grounded
    total_analyzed = len(payload.analyzed_symbols)
    symbol_coverage_rate = (
        round(len(grounded_symbols) / total_analyzed, 3) if total_analyzed > 0 else 1.0
    )

    # Compute context retention rate (CRR): proportion of target anchors covered
    anchors_set = set(verified_anchors)
    covered_anchors = 0
    grounded_names = [s.name for s in grounded_symbols]
    for anchor in anchors_set:
        if is_symbol_grounded(anchor, grounded_names):
            covered_anchors += 1
    crr = round(covered_anchors / max(1, len(anchors_set)), 3)

    guarded_payload = CodeSummaryPayload(
        intent_alignment=payload.intent_alignment,
        analyzed_symbols=grounded_symbols,
        technical_caveats=payload.technical_caveats,
    )
    return guarded_payload, symbol_coverage_rate, crr

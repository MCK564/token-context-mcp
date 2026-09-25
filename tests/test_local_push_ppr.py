"""Tests for M3.4 Andersen-Chung-Lang local push PPR and configurable vocab."""
from __future__ import annotations

import pytest

from token_context_mcp.models import EdgeRecord, SymbolRecord
from token_context_mcp.retrieve.ranking import (
    _expanded_query_terms,
    _stage_path_match,
    local_push_ppr,
    rank_symbols,
)


def _make_sym(sid: str, name: str, path: str = "src/pkg/mod.py") -> SymbolRecord:
    return SymbolRecord(
        symbol_id=sid,
        path=path,
        name=name,
        qualified_name=f"pkg.mod.{name}",
        kind="function",
        signature="() -> None",
        start_line=1,
        end_line=5,
        start_byte=0,
        end_byte=50,
        body_start_byte=10,
        body_end_byte=50,
        is_private=False,
    )


def _make_edge(src: str, tgt: str, confidence: float = 0.8) -> EdgeRecord:
    return EdgeRecord(
        source_symbol_id=src,
        target_symbol_id=tgt,
        target_name=tgt,
        edge_kind="call",
        status="resolved",
        backend="ast",
        confidence=confidence,
        source_path="src/pkg/mod.py",
        source_line=2,
        evidence=[],
    )


def test_local_push_ppr_linear_chain() -> None:
    sA = _make_sym("A", "query_target")
    sB = _make_sym("B", "intermediate")
    sC = _make_sym("C", "far_leaf")

    e1 = _make_edge("A", "B", 0.9)
    e2 = _make_edge("B", "C", 0.9)

    ppr = local_push_ppr(
        [sA, sB, sC],
        [e1, e2],
        query="query target",
        body_matches=None,
        eps=1e-4,
        alpha=0.15,
    )

    # Seed is at A; flow reaches B and then C
    assert ppr["A"] > ppr["C"]
    assert ppr["B"] > ppr["C"]
    assert ppr["C"] > 0.0


def test_local_push_ppr_prunes_low_confidence() -> None:
    sA = _make_sym("A", "seed_func")
    sB = _make_sym("B", "low_conf_neighbor")

    # Edge with 0.49 should be pruned (< 0.5)
    e_low = _make_edge("A", "B", 0.49)

    ppr = local_push_ppr(
        [sA, sB],
        [e_low],
        query="seed func",
        body_matches=None,
    )

    # B receives 0 pushed mass because the edge was pruned
    assert ppr["B"] == 0.0


def test_expanded_query_terms_configurable() -> None:
    # Default is empty
    terms = _expanded_query_terms("registry")
    assert terms == {"registry"}

    # With configured expansions
    expansions = {"registry": ["register", "lookup"]}
    terms_expanded = _expanded_query_terms("registry", query_expansions=expansions)
    assert terms_expanded == {"registry", "register", "lookup"}


def test_stage_prefix_pattern_configurable() -> None:
    # Default is None -> returns None
    assert _stage_path_match("src/01_extract.py", {"extract"}) is None

    # Configured with regex pattern
    matched = _stage_path_match(
        "src/01_extract.py",
        {"extract"},
        stage_prefix_pattern=r"^\d+_",
    )
    assert matched == "extract"

    # Non-matching path
    assert _stage_path_match(
        "src/no_stage.py",
        {"extract"},
        stage_prefix_pattern=r"^\d+_",
    ) is None


def test_rank_symbols_seed_biased_includes_seed_walk() -> None:
    sA = _make_sym("A", "process_invoice")
    sB = _make_sym("B", "helper_parse")
    e1 = _make_edge("A", "B", 0.9)

    ranked = rank_symbols([sA, sB], [e1], query="process invoice")
    assert len(ranked) == 2
    # Seed symbol should have seed_walk in basis
    basis_A = ranked[0][2]
    assert any("seed_walk:" in b for b in basis_A)

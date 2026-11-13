from __future__ import annotations

from token_context_mcp.models import EdgeRecord, SymbolRecord
from token_context_mcp.retrieve.expansion import expand_anchors
from token_context_mcp.retrieve.graph_cache import RepoGraph
from token_context_mcp.retrieve.ranking import rank_symbols


def _sym(sid: str, path: str, name: str, line: int) -> SymbolRecord:
    return SymbolRecord(
        symbol_id=sid,
        path=path,
        name=name,
        qualified_name=name,
        kind="function",
        signature=f"def {name}():",
        start_line=line,
        end_line=line + 5,
        start_byte=0,
        end_byte=50,
        body_start_byte=10,
        body_end_byte=50,
        is_private=False,
    )


def test_rank_symbols_ledger_overlay_and_exact_name_protection() -> None:
    s1 = _sym("python:a.py:alpha:1", "a.py", "alpha", 1)
    s2 = _sym("python:b.py:beta:1", "b.py", "beta", 1)
    s3 = _sym("python:c.py:exact_target:1", "c.py", "exact_target", 1)

    base = rank_symbols([s1, s2, s3], [], "exact_target")
    base_scores = {s.name: sc for s, sc, _ in base}

    overlay = {
        ("a.py", "alpha"): "answer",
        ("b.py", "beta"): "decoy",
        ("c.py", "exact_target"): "decoy",
    }
    with_ov = rank_symbols([s1, s2, s3], [], "exact_target", ledger_overlay=overlay)
    ov_map = {s.name: (sc, basis) for s, sc, basis in with_ov}

    assert ov_map["alpha"][0] == base_scores["alpha"] + 6.0
    assert "ledger_answer" in ov_map["alpha"][1]
    assert ov_map["beta"][0] == base_scores["beta"] - 4.0
    assert "ledger_decoy" in ov_map["beta"][1]
    # Exact name match must NOT be penalized
    assert ov_map["exact_target"][0] == base_scores["exact_target"]
    assert "ledger_decoy" not in ov_map["exact_target"][1]

    # Partial word overlap ('compile' in 'compile_validation' when querying 'compile serialization')
    # MUST still be penalized as a decoy, and protected when querying 'compile validation'
    s_ser = _sym("python:v.py:compile_serialization:1", "v.py", "compile_serialization", 1)
    s_val = _sym("python:v.py:compile_validation:10", "v.py", "compile_validation", 10)
    ov2 = {
        ("v.py", "compile_serialization"): "answer",
        ("v.py", "compile_validation"): "decoy",
    }
    base_q1 = {s.name: sc for s, sc, _ in rank_symbols([s_ser, s_val], [], "compile serialization")}
    res_q1 = {s.name: (sc, b) for s, sc, b in rank_symbols([s_ser, s_val], [], "compile serialization", ledger_overlay=ov2)}
    assert res_q1["compile_validation"][0] == base_q1["compile_validation"] - 4.0
    assert "ledger_decoy" in res_q1["compile_validation"][1]

    base_q2p = {s.name: sc for s, sc, _ in rank_symbols([s_ser, s_val], [], "compile validation")}
    res_q2p = {s.name: (sc, b) for s, sc, b in rank_symbols([s_ser, s_val], [], "compile validation", ledger_overlay=ov2)}
    assert res_q2p["compile_validation"][0] == base_q2p["compile_validation"]
    assert "ledger_decoy" not in res_q2p["compile_validation"][1]


def test_expand_anchors_step_bonus_and_decoy_penalty() -> None:
    anchor = _sym("python:a.py:entry:1", "a.py", "entry", 1)
    n1 = _sym("python:a.py:good_callee:10", "a.py", "good_callee", 10)
    n2 = _sym("python:a.py:bad_callee:20", "a.py", "bad_callee", 20)
    e1 = EdgeRecord(anchor.symbol_id, n1.symbol_id, "good_callee", "call", "resolved", "lexical", 0.9, "a.py", 2, [])
    e2 = EdgeRecord(anchor.symbol_id, n2.symbol_id, "bad_callee", "call", "resolved", "lexical", 0.9, "a.py", 3, [])
    graph = RepoGraph("demo", "run1", [anchor, n1, n2], [e1, e2])
    base, _ = expand_anchors(graph, [anchor.symbol_id], "entry", k=5, hops=1, min_confidence=0.5, communities={"a.py": 1})
    base_scores = {n.name: n.score for n in base}

    ov, _ = expand_anchors(
        graph,
        [anchor.symbol_id],
        "entry",
        k=5,
        hops=1,
        min_confidence=0.5,
        communities={"a.py": 1},
        confirmed_step_edges={("entry", "good_callee")},
        confirmed_decoys={("a.py", "bad_callee")},
    )
    ov_scores = {n.name: n.score for n in ov}
    assert abs(ov_scores["good_callee"] - base_scores["good_callee"] * 1.2) < 1e-6
    assert abs(ov_scores["bad_callee"] - base_scores["bad_callee"] * 0.5) < 1e-6

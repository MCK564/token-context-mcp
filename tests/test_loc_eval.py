from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest
from evals.loc_eval import (
    compute_aggregate,
    evaluate_single_task,
    extract_ranked_files,
    extract_ranked_symbols,
    percentile,
)


def test_percentile_hand_calculated():
    data = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile(data, 50.0) == 30.0
    assert percentile(data, 0.0) == 10.0
    assert percentile(data, 100.0) == 50.0

    data_even = [10.0, 20.0, 30.0, 40.0]
    # idx = 3 * 0.5 = 1.5 -> midpoint between 20 and 30 is 25.0
    assert percentile(data_even, 50.0) == 25.0


def test_extract_ranked_files_and_symbols_with_neighbors():
    response_data = {
        "matches": [
            {"path": "src/alpha.py", "symbol_id": "sym_alpha"},
            {"path": "src/beta.py", "symbol_id": "sym_beta"},
            {"path": "src/alpha.py", "symbol_id": "sym_alpha_2"},  # duplicate file
        ],
        "neighbors": [
            ["sym_gamma", "src/gamma.py:42", "function GammaFunc", "callee", 0.95, "sym_alpha"],
            ["sym_beta", "src/beta.py:10", "function BetaFunc", "caller", 0.80, "sym_alpha"],  # duplicate file
        ],
    }
    symbol_map = {
        "sym_alpha": ("src/alpha.py", "AlphaFunc"),
        "sym_beta": ("src/beta.py", "BetaFunc"),
        "sym_alpha_2": ("src/alpha.py", "AlphaHelper"),
        "sym_gamma": ("src/gamma.py", "GammaFunc"),
    }

    # M5.2: neighbors are ranked immediately after the anchor they were expanded from
    # (alpha -> gamma, beta), so a neighbor can enter the top-k instead of trailing every match.
    files = extract_ranked_files(response_data)
    assert files == ["src/alpha.py", "src/gamma.py", "src/beta.py"]

    symbols = extract_ranked_symbols(response_data, symbol_map)
    assert symbols == [
        ("src/alpha.py", "AlphaFunc"),
        ("src/gamma.py", "GammaFunc"),
        ("src/beta.py", "BetaFunc"),
        ("src/alpha.py", "AlphaHelper"),
    ]


def test_orphan_neighbors_go_last():
    response_data = {
        "matches": [{"path": "src/a.py", "symbol_id": "a"}],
        "neighbors": [["z", "src/z.py:1", "function Z", "callee", 0.9, "not_a_match"]],
    }
    assert extract_ranked_files(response_data) == ["src/a.py", "src/z.py"]


def test_evaluate_single_task_and_aggregate_hand_calculated():
    # Task 1: Complete hit
    task1 = {
        "id": "t1",
        "group": "a_keyword",
        "split": "dev",
        "query": "query 1",
        "gold_files": ["src/a.py", "src/b.py"],
        "gold_symbols": [
            {"path": "src/a.py", "qualified_name": "FuncA"},
            {"path": "src/b.py", "qualified_name": "FuncB"},
        ],
    }
    resp1 = {
        "data": {
            "matches": [
                {"path": "src/a.py", "symbol_id": "sym1"},
                {"path": "src/c.py", "symbol_id": "sym2"},
            ],
            "neighbors": [
                ["sym3", "src/b.py:10", "function FuncB", "callee", 0.9, "sym1"]
            ],
        }
    }

    # Task 2: Miss in top-5 files, partial symbol recall
    task2 = {
        "id": "t2",
        "group": "a_keyword",
        "split": "dev",
        "query": "query 2",
        "gold_files": ["src/gold1.py", "src/gold2.py"],
        "gold_symbols": [
            {"path": "src/gold1.py", "qualified_name": "GoldSym1"},
            {"path": "src/gold2.py", "qualified_name": "GoldSym2"},
        ],
    }
    resp2 = {
        "data": {
            "matches": [
                {"path": "src/x.py", "symbol_id": "sx1"},
                {"path": "src/y.py", "symbol_id": "sx2"},
                {"path": "src/z.py", "symbol_id": "sx3"},
                {"path": "src/w.py", "symbol_id": "sx4"},
                {"path": "src/v.py", "symbol_id": "sx5"},
                {"path": "src/gold1.py", "symbol_id": "sg1"},  # rank 6 file!
            ],
            "neighbors": [],
        }
    }

    symbol_map = {
        "sym1": ("src/a.py", "FuncA"),
        "sym2": ("src/c.py", "FuncC"),
        "sym3": ("src/b.py", "FuncB"),
        "sx1": ("src/x.py", "X1"),
        "sx2": ("src/y.py", "X2"),
        "sx3": ("src/z.py", "X3"),
        "sx4": ("src/w.py", "X4"),
        "sx5": ("src/v.py", "X5"),
        "sg1": ("src/gold1.py", "GoldSym1"),
    }

    res1 = evaluate_single_task(task1, resp1, symbol_map, [10.0, 12.0, 14.0, 16.0])
    assert res1["file_acc_at_5"] == 1.0
    assert res1["file_recall_at_5"] == 1.0
    assert res1["first_gold_file_rank"] == 1
    assert res1["sym_recall_at_10"] == 1.0
    assert res1["first_gold_sym_rank"] == 1
    assert res1["hit"] is True

    res2 = evaluate_single_task(task2, resp2, symbol_map, [20.0, 22.0, 24.0, 26.0])
    assert res2["file_acc_at_5"] == 0.0
    assert res2["file_recall_at_5"] == 0.0
    assert res2["first_gold_file_rank"] == 6
    assert res2["sym_recall_at_10"] == 0.50
    assert res2["first_gold_sym_rank"] == 6
    assert res2["hit"] is False

    agg = compute_aggregate([res1, res2])
    assert agg["task_count"] == 2
    assert agg["file_acc_at_5"] == 0.50
    assert agg["file_recall_at_5"] == 0.50
    assert agg["sym_recall_at_10"] == 0.75

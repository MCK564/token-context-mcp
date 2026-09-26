from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest
from evals.lint_tasks import lint_task_data, split_identifier_tokens


def test_split_identifier_tokens():
    tokens = split_identifier_tokens("MemoryStore.get_value_by_id")
    assert "memory" in tokens
    assert "store" in tokens
    assert "memorystore" in tokens
    assert "get" in tokens
    assert "value" in tokens
    assert "id" in tokens


def test_rule_2_path_format_violations():
    data = {
        "split_seed": 20260926,
        "tasks": [
            {
                "id": "t1",
                "group": "a_keyword",
                "split": "dev",
                "query": "some query",
                "gold_files": ["src\\path\\to\\file.py"],  # backslash
                "gold_symbols": [{"path": "/absolute/path.py", "qualified_name": "Func"}],  # absolute
            }
        ],
    }
    errors = lint_task_data(data)
    assert any("contains backslash" in e for e in errors)
    assert any("absolute path" in e for e in errors)


def test_rule_3_hidden_dep_leak():
    data = {
        "split_seed": 20260926,
        "tasks": [
            {
                "id": "t11",
                "group": "b_hidden_dep",
                "split": "dev",
                "query": "read from memorystore lookup",  # leaks 'memorystore' and 'store'
                "gold_files": ["src/memory/store.py"],
                "gold_symbols": [{"path": "src/memory/store.py", "qualified_name": "MemoryStore.get"}],
            }
        ],
    }
    errors = lint_task_data(data)
    assert any("Rule 3" in e for e in errors)


def test_rule_4_multi_file_count():
    data = {
        "split_seed": 20260926,
        "tasks": [
            {
                "id": "t21",
                "group": "c_multi_file",
                "split": "dev",
                "query": "multi file query",
                "gold_files": ["src/file1.py"],  # only 1 file
                "gold_symbols": [{"path": "src/file1.py", "qualified_name": "Func"}],
            }
        ],
    }
    errors = lint_task_data(data)
    assert any("Rule 4" in e for e in errors)


def test_rule_5_group_count_and_split():
    data = {
        "split_seed": 20260926,
        "tasks": [
            {"id": "t1", "group": "a_keyword", "split": "dev", "query": "q1", "gold_files": ["f.py"], "gold_symbols": []},
        ],
    }
    errors = lint_task_data(data)
    assert any("Rule 5: Group 'a_keyword' must have exactly 10 tasks" in e for e in errors)


def test_rule_6_duplicate_query():
    data = {
        "split_seed": 20260926,
        "tasks": [
            {"id": "t1", "group": "a_keyword", "split": "dev", "query": "duplicate query", "gold_files": ["f.py"], "gold_symbols": []},
            {"id": "t2", "group": "a_keyword", "split": "heldout", "query": "duplicate query", "gold_files": ["f.py"], "gold_symbols": []},
        ],
    }
    errors = lint_task_data(data)
    assert any("Duplicate query" in e for e in errors)

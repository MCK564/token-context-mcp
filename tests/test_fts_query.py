"""Tests for _fts_query construction and SQLite FTS5 execution."""

import sqlite3
import pytest
from token_context_mcp.retrieve.code_tokens import split_identifier
from token_context_mcp.retrieve.service import _fts_query


def test_fts_query_basic():
    # Regular terms
    q = _fts_query("ON edges", op="AND")
    assert '"ON"' in q and '"edges"' in q
    assert " AND " in q


def test_fts_query_identifier_decomposition():
    q = _fts_query("build_server", op="AND")
    # Should decompose into ("build_server" OR ("build" AND "server"))
    assert '"build_server"' in q
    assert '"build"' in q
    assert '"server"' in q
    assert " OR " in q


def test_fts_query_e3_cases():
    # E3 queries that previously risked SQLite FTS5 syntax errors or keyword conflicts
    cases = [
        "def _invoke",
        "ON edges",
        "CREATE TABLE IF NOT EXISTS edges",
        "token-context-mcp",
        "tính freshness bằng stat và mtime",
        'test "quoted phrase"',
    ]
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE fts_demo USING fts5(body);")
    conn.execute("INSERT INTO fts_demo(body) VALUES (?);", ("def _invoke(): pass ON edges CREATE TABLE IF NOT EXISTS edges",))
    conn.execute("INSERT INTO fts_demo(body) VALUES (?);", ("token-context-mcp server freshness cache stat mtime",))

    for case in cases:
        and_q = _fts_query(case, op="AND")
        or_q = _fts_query(case, op="OR")
        # Ensure SQLite FTS5 executes without syntax error
        conn.execute("SELECT COUNT(*) FROM fts_demo WHERE body MATCH ?", (and_q,))
        conn.execute("SELECT COUNT(*) FROM fts_demo WHERE body MATCH ?", (or_q,))


def test_fts_query_empty_raises():
    from token_context_mcp.retrieve.service import RetrievalError
    with pytest.raises(RetrievalError):
        _fts_query("")
    with pytest.raises(RetrievalError):
        _fts_query("   ")

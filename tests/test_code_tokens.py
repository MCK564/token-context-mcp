"""Unit tests for code_tokens module (split_identifier and path_tokens)."""

import pytest
from token_context_mcp.retrieve.code_tokens import path_tokens, split_identifier


@pytest.mark.parametrize(
    "input_s,expected",
    [
        ("HTTPServer", ["http", "server", "httpserver"]),
        ("parseV2Config", ["parse", "v2", "config", "parsev2config"]),
        ("buildServer", ["build", "server", "buildserver"]),
        ("build_server", ["build", "server", "build_server"]),
        ("__init__", ["init", "__init__"]),
        ("", []),
        ("   ", []),
        ("tính_toán", ["tính", "toán", "tính_toán"]),
        ("TìmKiếmDữLiệu", ["tìm", "kiếm", "dữ", "liệu", "tìmkiếmdữliệu"]),
        ("SQLiteStore", ["sq", "lite", "store", "sqlitestore"]),
        ("read_connection_pool", ["read", "connection", "pool", "read_connection_pool"]),
        ("v2", ["v2"]),
        ("get_repo_map@1024", ["get", "repo", "map", "1024", "get_repo_map@1024"]),
        ("token-context-mcp", ["token", "context", "mcp", "token-context-mcp"]),
        ("JSON2XMLConverter", ["json2", "xml", "converter", "json2xmlconverter"]),
    ],
)
def test_split_identifier_table(input_s, expected):
    assert split_identifier(input_s) == expected


def test_split_identifier_idempotence():
    # Splitting an already-lowercased single token returns just that token
    assert split_identifier("server") == ["server"]


def test_path_tokens():
    assert path_tokens("src/token_context_mcp/retrieve/service.py") == [
        "token_context_mcp",
        "token",
        "context",
        "mcp",
        "retrieve",
        "service",
    ]
    assert path_tokens("src/token_context_mcp/cli.py") == [
        "token_context_mcp",
        "token",
        "context",
        "mcp",
        "cli",
    ]
    assert path_tokens("evals/tasks/loc_token_context.json") == [
        "evals",
        "tasks",
        "loc_token_context",
        "loc",
        "token",
        "context",
    ]
    assert path_tokens("README.md") == ["readme"]
    assert path_tokens("") == []

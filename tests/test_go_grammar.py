"""M10.2: the Go grammar (best-effort names, no receiver type inference beyond the method receiver)."""
from __future__ import annotations

from pathlib import Path

import pytest

from token_context_mcp.constants import SUPPORTED_EXTENSIONS
from token_context_mcp.parse.treesitter import PARSER_ARTIFACT_VERSION, parse_source

FIXTURE = Path(__file__).parent / "fixtures" / "go_server.go"


@pytest.fixture(scope="module")
def parsed():
    return parse_source("server/server.go", FIXTURE.read_bytes(), "go")


def test_go_extension_is_supported():
    assert SUPPORTED_EXTENSIONS[".go"] == "go"
    assert PARSER_ARTIFACT_VERSION >= 2  # bumped when the grammar was added


def test_symbols_kinds_and_qualified_names(parsed):
    got = {(s.kind, s.qualified_name) for s in parsed.symbols}
    assert got == {
        ("interface", "Handler"),
        ("struct", "Server"),
        ("type", "ID"),
        ("type", "Alias"),
        ("function", "NewServer"),
        ("method", "Server.Start"),  # pointer receiver
        ("method", "Server.helper"),  # value receiver
        ("method", "Server.Stop"),
    }


def test_signatures_spans_and_privacy(parsed):
    by_name = {s.qualified_name: s for s in parsed.symbols}
    assert by_name["NewServer"].signature == "func NewServer(name string) *Server"
    assert by_name["Server.Start"].signature == "func (s *Server) Start() error"
    assert by_name["Server"].signature == "type Server struct"
    assert by_name["Handler"].signature == "type Handler interface"
    assert by_name["ID"].signature == "type ID int"
    raw = FIXTURE.read_bytes()
    server = by_name["Server"]
    assert raw[server.body_start_byte : server.body_end_byte].startswith(b"struct {") is False  # body starts at "{"
    assert raw[server.body_start_byte : server.body_start_byte + 1] == b"{"
    start = by_name["Server.Start"]
    assert (start.start_line, start.end_line) == (27, 32)
    # Go privacy is capitalisation
    assert by_name["Server.helper"].is_private is True
    assert by_name["Server.Start"].is_private is False
    assert by_name["NewServer"].is_private is False


def test_imports_are_paths_without_quotes_or_aliases(parsed):
    assert parsed.imports == ["fmt", "github.com/acme/util", "net/http/pprof", "strings"]
    assert "dynamic_import_detected" not in parsed.warnings


def test_calls_with_receivers(parsed):
    calls = {(c.receiver, c.name, c.line) for c in parsed.calls}
    assert (None, "NewServer", 36) in calls
    assert ("fmt", "Println", 28) in calls
    assert ("util", "Log", 30) in calls
    assert ("s.h", "Serve", 31) in calls
    # the receiver variable carries the receiver's type: s.helper() is Server.helper
    helper = next(c for c in parsed.calls if c.name == "helper")
    assert helper.receiver == "s" and helper.receiver_type == "Server"
    # a package qualifier is not a typed receiver
    assert next(c for c in parsed.calls if c.name == "Println").receiver_type is None


def test_generic_receiver_and_no_symbols_file():
    src = b"package p\n\ntype Box[T any] struct{ v T }\n\nfunc (b *Box[T]) Get() T { return b.v }\n"
    result = parse_source("p/box.go", src, "go")
    assert {(s.kind, s.qualified_name) for s in result.symbols} == {("struct", "Box"), ("method", "Box.Get")}
    empty = parse_source("p/doc.go", b"// Package p does things.\npackage p\n", "go")
    assert empty.symbols == [] and "parsed_file_has_zero_symbols" in empty.warnings


def test_a_function_named_require_is_an_ordinary_call():
    src = b"package p\n\nfunc a() { require(1) }\n\nfunc require(x int) {}\n"
    result = parse_source("p/r.go", src, "go")
    assert "dynamic_import_detected" not in result.warnings
    assert [c.name for c in result.calls] == ["require"]


def test_syntax_error_is_reported_not_raised():
    result = parse_source("p/bad.go", b"package p\n\nfunc (\n", "go")
    assert "parser_error_node_present" in result.warnings


def test_go_files_are_indexed_and_edges_resolve(tmp_path):
    from token_context_mcp.config import RepositoryConfig
    from token_context_mcp.index.runner import build_index, database_path
    from token_context_mcp.index.sqlite_store import SQLiteStore

    repo = tmp_path / "goapp"
    repo.mkdir()
    (repo / "go.mod").write_text("module example.com/goapp\n\ngo 1.22\n", encoding="utf-8")
    (repo / "a.go").write_text("package goapp\n\nfunc Run() int {\n\treturn compute(2)\n}\n", encoding="utf-8")
    (repo / "b.go").write_text("package goapp\n\nfunc compute(x int) int {\n\treturn x * 2\n}\n", encoding="utf-8")
    index_dir = tmp_path / "indexes"
    build_index(
        RepositoryConfig(repo_id="goapp", root=repo, allow_symlinks=False, max_file_bytes=200_000, max_files=100),
        index_dir,
        network_policy="declared-deny-not-enforced",
    )
    store = SQLiteStore(database_path(index_dir, "goapp"))
    symbols = {s.name: s for s in store.symbols()}
    assert {"Run", "compute"} <= set(symbols)
    edge = next(e for e in store.edges() if e.source_symbol_id == symbols["Run"].symbol_id and e.target_name == "compute")
    assert edge.status == "resolved" and edge.target_symbol_id == symbols["compute"].symbol_id

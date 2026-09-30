"""Tests for C# namespace scoping (E3) in token-context-mcp."""
import dataclasses
from token_context_mcp.parse.treesitter import (
    CallRecord,
    SymbolRecord,
    parse_source,
    _extract_csharp_namespaces,
    _load_language,
    _new_parser,
)
from token_context_mcp.parse.lexical_edges import build_lexical_edges, SCOPE_CONFIDENCE


def make_sym(
    symbol_id: str,
    path: str,
    name: str,
    qualified_name: str,
    kind: str,
    signature: str,
    start_line: int,
    start_byte: int = 0,
    end_byte: int = 100,
) -> SymbolRecord:
    return SymbolRecord(
        symbol_id=symbol_id,
        path=path,
        name=name,
        qualified_name=qualified_name,
        kind=kind,
        signature=signature,
        start_line=start_line,
        end_line=start_line + 5,
        start_byte=start_byte,
        end_byte=end_byte,
        body_start_byte=start_byte + 10,
        body_end_byte=end_byte - 10,
        is_private=False,
    )


def test_extract_csharp_namespaces_block():
    code = b"""
    namespace MyCompany.Services
    {
        public class Worker {}
    }
    """
    lang = _load_language("c_sharp")
    parser = _new_parser(lang)
    tree = parser.parse(code)
    ns = _extract_csharp_namespaces(tree.root_node, code)
    assert ns == ["MyCompany.Services"]


def test_extract_csharp_namespaces_file_scoped():
    code = b"""
    namespace MyCompany.Services;

    public class Worker {}
    """
    lang = _load_language("c_sharp")
    parser = _new_parser(lang)
    tree = parser.parse(code)
    ns = _extract_csharp_namespaces(tree.root_node, code)
    assert ns == ["MyCompany.Services"]


def test_extract_csharp_namespaces_nested():
    code = b"""
    namespace Outer
    {
        namespace Inner
        {
            public class Worker {}
        }
    }
    """
    lang = _load_language("c_sharp")
    parser = _new_parser(lang)
    tree = parser.parse(code)
    ns = _extract_csharp_namespaces(tree.root_node, code)
    assert ns == ["Outer", "Outer.Inner"]


def test_csharp_same_namespace_resolution():
    source_sym = make_sym(
        "c_sharp:src/File1.cs:MyService.Execute:1",
        "src/File1.cs",
        "Execute",
        "MyService.Execute",
        "method",
        "public void Execute()",
        10,
        start_byte=100,
        end_byte=200,
    )
    target_same_ns = make_sym(
        "c_sharp:src/Sub/File2.cs:Helper.Run:1",
        "src/Sub/File2.cs",
        "Run",
        "Helper.Run",
        "method",
        "public static void Run()",
        20,
        start_byte=300,
        end_byte=400,
    )
    other_cand = make_sym(
        "c_sharp:src/Other/File3.cs:Helper.Run:1",
        "src/Other/File3.cs",
        "Run",
        "Helper.Run",
        "method",
        "public static void Run()",
        20,
        start_byte=500,
        end_byte=600,
    )

    call = CallRecord(
        name="Run",
        receiver="Helper",
        start_byte=120,
        end_byte=135,
        line=12,
    )

    file_namespaces = {
        "src/File1.cs": ["Foo.Bar"],
        "src/Sub/File2.cs": ["Foo.Bar"],
        "src/Other/File3.cs": ["Other.Ns"],
    }

    edges = build_lexical_edges(
        symbols=[source_sym, target_same_ns, other_cand],
        source_by_path={},
        calls_by_path={"src/File1.cs": [call]},
        file_namespaces=file_namespaces,
    )

    assert len(edges) == 1
    edge = edges[0]
    assert edge.status == "resolved"
    assert edge.target_symbol_id == target_same_ns.symbol_id
    assert "scope:same_namespace" in edge.evidence
    assert edge.confidence == SCOPE_CONFIDENCE["same_namespace"]


def test_csharp_namespace_match_using():
    source_sym = make_sym(
        "c_sharp:src/File1.cs:MyService.Execute:1",
        "src/File1.cs",
        "Execute",
        "MyService.Execute",
        "method",
        "public void Execute()",
        10,
        start_byte=100,
        end_byte=200,
    )
    target_imported_ns = make_sym(
        "c_sharp:src/Other/File2.cs:External.Run:1",
        "src/Other/File2.cs",
        "Run",
        "External.Run",
        "method",
        "public static void Run()",
        20,
        start_byte=300,
        end_byte=400,
    )
    other_cand = make_sym(
        "c_sharp:src/Third/File3.cs:External.Run:1",
        "src/Third/File3.cs",
        "Run",
        "External.Run",
        "method",
        "public static void Run()",
        20,
        start_byte=500,
        end_byte=600,
    )

    call = CallRecord(
        name="Run",
        receiver="External",
        start_byte=120,
        end_byte=135,
        line=12,
    )

    file_namespaces = {
        "src/File1.cs": ["Foo.Bar"],
        "src/Other/File2.cs": ["Other.Ns"],
        "src/Third/File3.cs": ["Third.Ns"],
    }

    edges = build_lexical_edges(
        symbols=[source_sym, target_imported_ns, other_cand],
        source_by_path={},
        calls_by_path={"src/File1.cs": [call]},
        imports_by_path={"src/File1.cs": ["Other.Ns"]},
        file_namespaces=file_namespaces,
    )

    assert len(edges) == 1
    edge = edges[0]
    assert edge.status == "resolved"
    assert edge.target_symbol_id == target_imported_ns.symbol_id
    assert "scope:namespace_match" in edge.evidence
    assert edge.confidence == SCOPE_CONFIDENCE["namespace_match"]


def test_python_unaffected_by_namespaces():
    source_sym = make_sym(
        "python:src/file1.py:fn:1",
        "src/file1.py",
        "fn",
        "fn",
        "function",
        "def fn():",
        1,
        start_byte=0,
        end_byte=50,
    )
    target1 = make_sym(
        "python:src/file2.py:run:1",
        "src/file2.py",
        "run",
        "run",
        "function",
        "def run():",
        1,
        start_byte=0,
        end_byte=50,
    )
    target2 = make_sym(
        "python:src/file3.py:run:1",
        "src/file3.py",
        "run",
        "run",
        "function",
        "def run():",
        1,
        start_byte=0,
        end_byte=50,
    )
    call = CallRecord(name="run", receiver=None, start_byte=10, end_byte=15, line=2)

    edges = build_lexical_edges(
        symbols=[source_sym, target1, target2],
        source_by_path={},
        calls_by_path={"src/file1.py": [call]},
        file_namespaces={"src/file1.py": ["A"], "src/file2.py": ["A"], "src/file3.py": ["B"]},
    )
    assert len(edges) == 1
    assert "scope:same_namespace" not in edges[0].evidence
    assert "scope:namespace_match" not in edges[0].evidence

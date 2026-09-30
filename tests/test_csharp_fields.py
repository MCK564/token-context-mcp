"""Tests for field without this. in C# and Java (E5)."""
import tree_sitter_c_sharp as tscsharp
from tree_sitter import Language, Parser
from token_context_mcp.parse.treesitter import extract_calls, SymbolRecord
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


def test_csharp_bare_field_receiver():
    code = b"""
    class Service {
        private readonly Worker _worker;
        public IConverter Converter { get; set; }

        void Process() {
            _worker.DoWork();
            Converter.Convert();
        }
    }
    """
    lang = Language(tscsharp.language())
    parser = Parser(lang)
    tree = parser.parse(code)
    calls = extract_calls(tree.root_node, code, "c_sharp")

    assert len(calls) == 2
    assert calls[0].name == "DoWork"
    assert calls[0].receiver == "_worker"
    assert calls[0].receiver_type == "Worker"
    assert getattr(calls[0], "receiver_type_source", None) == "field_type"

    assert calls[1].name == "Convert"
    assert calls[1].receiver == "Converter"
    assert calls[1].receiver_type == "IConverter"
    assert getattr(calls[1], "receiver_type_source", None) == "field_type"


def test_csharp_bare_field_edge_resolution():
    code = b"""
    class Service {
        private readonly Worker _worker;

        void Process() {
            _worker.DoWork();
        }
    }
    """
    lang = Language(tscsharp.language())
    parser = Parser(lang)
    tree = parser.parse(code)
    calls = extract_calls(tree.root_node, code, "c_sharp")

    source_sym = make_sym("c_sharp:src/Service.cs:Service.Process:1", "src/Service.cs", "Process", "Service.Process", "method", "void Process()", 5, start_byte=0, end_byte=len(code))
    target_sym = make_sym("c_sharp:src/Worker.cs:Worker.DoWork:1", "src/Worker.cs", "DoWork", "Worker.DoWork", "method", "public void DoWork()", 10)
    other_sym = make_sym("c_sharp:src/Other.cs:Other.DoWork:1", "src/Other.cs", "DoWork", "Other.DoWork", "method", "public void DoWork()", 20)

    edges = build_lexical_edges(
        symbols=[source_sym, target_sym, other_sym],
        source_by_path={},
        calls_by_path={"src/Service.cs": calls},
    )

    assert len(edges) == 1
    assert edges[0].status == "resolved"
    assert edges[0].target_symbol_id == target_sym.symbol_id
    assert "scope:field_type" in edges[0].evidence
    assert edges[0].confidence == SCOPE_CONFIDENCE["field_type"]


def test_csharp_field_shadowed_by_parameter():
    code = b"""
    class Service {
        private readonly Worker _worker;

        void Process(SpecialWorker _worker) {
            _worker.DoWork();
        }
    }
    """
    lang = Language(tscsharp.language())
    parser = Parser(lang)
    tree = parser.parse(code)
    calls = extract_calls(tree.root_node, code, "c_sharp")

    assert len(calls) == 1
    assert calls[0].name == "DoWork"
    assert calls[0].receiver == "_worker"
    # Parameter SpecialWorker shadows field Worker
    assert calls[0].receiver_type == "SpecialWorker"
    assert getattr(calls[0], "receiver_type_source", None) is None

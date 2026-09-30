"""Tests for C# local variable type tracking and taint rules (E4)."""
import tree_sitter_c_sharp as tscsharp
from tree_sitter import Language, Parser
from token_context_mcp.parse.treesitter import extract_calls, parse_source, SymbolRecord
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


def test_csharp_local_var_types_inferred():
    code = b"""
    class Service {
        void Process() {
            Foo x = new Foo();
            x.Run();

            var y = new Bar(1, 2);
            y.Run();

            var z = new Generic<int>();
            z.Run();

            var casted = (SpecialWorker)obj;
            casted.Run();
        }
    }
    """
    lang = Language(tscsharp.language())
    parser = Parser(lang)
    tree = parser.parse(code)
    calls = extract_calls(tree.root_node, code, "c_sharp")

    assert len(calls) == 4
    assert calls[0].name == "Run" and calls[0].receiver == "x" and calls[0].receiver_type == "Foo"
    assert calls[1].name == "Run" and calls[1].receiver == "y" and calls[1].receiver_type == "Bar"
    assert calls[2].name == "Run" and calls[2].receiver == "z" and calls[2].receiver_type == "Generic"
    assert calls[3].name == "Run" and calls[3].receiver == "casted" and calls[3].receiver_type == "SpecialWorker"


def test_csharp_local_var_taint_reassigned():
    code = b"""
    class Service {
        void Process() {
            var x = new Foo();
            x = new Bar();
            x.Run();
        }
    }
    """
    lang = Language(tscsharp.language())
    parser = Parser(lang)
    tree = parser.parse(code)
    calls = extract_calls(tree.root_node, code, "c_sharp")

    assert len(calls) == 1
    assert calls[0].name == "Run"
    assert calls[0].receiver == "x"
    assert calls[0].receiver_type is None
    assert calls[0].is_tainted is True


def test_csharp_local_var_taint_branch():
    code = b"""
    class Service {
        void Process(bool cond) {
            Foo x;
            if (cond) {
                x = new Foo();
            }
            x.Run();
        }
    }
    """
    lang = Language(tscsharp.language())
    parser = Parser(lang)
    tree = parser.parse(code)
    calls = extract_calls(tree.root_node, code, "c_sharp")

    assert len(calls) == 1
    assert calls[0].name == "Run"
    assert calls[0].receiver == "x"
    assert calls[0].receiver_type is None
    assert calls[0].is_tainted is True


def test_csharp_local_var_edge_resolution():
    code = b"""
    class Service {
        void Process() {
            var worker = new SpecialWorker();
            worker.Execute();
        }
    }
    """
    lang = Language(tscsharp.language())
    parser = Parser(lang)
    tree = parser.parse(code)
    calls = extract_calls(tree.root_node, code, "c_sharp")

    source_sym = make_sym("c_sharp:src/Service.cs:Service.Process:1", "src/Service.cs", "Process", "Service.Process", "method", "void Process()", 1, start_byte=0, end_byte=len(code))
    target_sym = make_sym("c_sharp:src/SpecialWorker.cs:SpecialWorker.Execute:1", "src/SpecialWorker.cs", "Execute", "SpecialWorker.Execute", "method", "public void Execute()", 10)
    other_sym = make_sym("c_sharp:src/Other.cs:Other.Execute:1", "src/Other.cs", "Execute", "Other.Execute", "method", "public void Execute()", 20)

    edges = build_lexical_edges(
        symbols=[source_sym, target_sym, other_sym],
        source_by_path={},
        calls_by_path={"src/Service.cs": calls},
    )

    assert len(edges) == 1
    assert edges[0].status == "resolved"
    assert edges[0].target_symbol_id == target_sym.symbol_id
    assert "scope:exact_receiver_type" in edges[0].evidence

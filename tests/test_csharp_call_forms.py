import tree_sitter_c_sharp as tscsharp
from tree_sitter import Language, Parser
from token_context_mcp.parse.treesitter import extract_calls, parse_source, SymbolRecord
from token_context_mcp.parse.lexical_edges import build_lexical_edges


def test_csharp_call_forms_extraction():
    code = b"""
    class Test {
        void Run(Helper x) {
            Foo<int>();
            this.Bar<string>(1);
            x?.Baz();
            x?.Quux<double>(2);
            a.b?.Run();
        }
    }
    """
    lang = Language(tscsharp.language())
    parser = Parser(lang)
    tree = parser.parse(code)
    calls = extract_calls(tree.root_node, code, "c_sharp")

    call_map = {(c.name, c.receiver, c.arg_count): c for c in calls}

    # 1. generic_name (identifier extracted)
    assert ("Foo", None, 0) in call_map

    # 2. member_access_expression with generic
    assert ("Bar", "this", 1) in call_map

    # 3. conditional_access_expression
    assert ("Baz", "x", 0) in call_map
    assert call_map[("Baz", "x", 0)].receiver_type == "Helper"

    # 4. conditional_access_expression with generic
    assert ("Quux", "x", 1) in call_map
    assert call_map[("Quux", "x", 1)].receiver_type == "Helper"

    # 5. chained conditional access
    assert ("Run", "a.b", 0) in call_map


def test_csharp_conditional_access_edge_resolution():
    code = b"""
namespace App {
    public class Helper {
        public void Baz() {}
    }

    public class Consumer {
        public void Execute(Helper x) {
            x?.Baz();
        }
    }
}
"""
    res = parse_source("app.cs", code, "c_sharp")
    edges = build_lexical_edges(
        symbols=res.symbols,
        source_by_path={"app.cs": code.decode("utf-8")},
        calls_by_path={"app.cs": res.calls},
        file_namespaces={"app.cs": res.namespaces},
    )

    baz_edges = [e for e in edges if e.target_name == "Baz"]
    assert len(baz_edges) == 1
    assert baz_edges[0].status == "resolved"
    assert baz_edges[0].confidence >= 0.85
    target = next(s for s in res.symbols if s.symbol_id == baz_edges[0].target_symbol_id)
    assert target.qualified_name == "Helper.Baz"

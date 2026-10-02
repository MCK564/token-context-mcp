"""M13: Java / C# typed call extraction and member resolution (overloads, overrides, nested types, chains)."""
from __future__ import annotations

import pytest

from token_context_mcp.index.runner import _call_dependency_names
from token_context_mcp.parse import jvm_types as jt
from token_context_mcp.parse.lexical_edges import build_lexical_edges
from token_context_mcp.parse.treesitter import parse_source


# ----------------------------------------------------------------------------------------------- helpers
def _edges(files: dict[str, str]):
    """Parse ``files`` (path -> source; language from the extension) and resolve every call in them."""
    symbols, calls, imports, hierarchy, namespaces = [], {}, {}, {}, {}
    for path, text in files.items():
        language = "java" if path.endswith(".java") else "c_sharp"
        parsed = parse_source(path, text.encode("utf-8"), language)
        symbols.extend(parsed.symbols)
        calls[path] = parsed.calls
        imports[path] = parsed.imports
        for name, parents in parsed.inheritance.items():
            hierarchy[name] = hierarchy.get(name, []) + [p for p in parents if p not in hierarchy.get(name, [])]
        if parsed.namespaces:
            namespaces[path] = parsed.namespaces
    by_id = {s.symbol_id: s for s in symbols}
    edges = build_lexical_edges(
        symbols, {}, calls_by_path=calls, imports_by_path=imports, class_hierarchy=hierarchy, file_namespaces=namespaces
    )
    return edges, by_id


def _target(edges, by_id, name: str, line: int | None = None):
    """(qualified name, start line, scope) of the edge to ``name`` (at ``line``), or ``None`` when unresolved."""
    found = [e for e in edges if e.target_name == name and (line is None or e.source_line == line)]
    assert found, f"no edge for {name} at {line}: {[(e.target_name, e.source_line) for e in edges]}"
    edge = found[0]
    scope = next(x[6:] for x in edge.evidence if x.startswith("scope:"))
    if edge.target_symbol_id is None:
        return None, None, scope
    target = by_id[edge.target_symbol_id]
    return target.qualified_name, target.start_line, scope


# ----------------------------------------------------------------------------------------------- type helpers
def test_type_key_and_ref() -> None:
    assert jt.type_key("Map<String, List<Foo>>") == "Map"
    assert jt.type_key("String...") == "String[]"
    assert jt.type_key("final Connection.@Nullable Response") == "Response"
    assert jt.type_ref("final Connection.@Nullable Response") == "Connection.Response"
    assert jt.type_ref("org.jsoup.nodes.Element") == "Element"  # a lower-case qualifier is a package
    assert jt.type_ref("(int, string)") == ""
    assert jt.type_key("var") == ""


def test_split_params_and_arity() -> None:
    params = jt.split_params("public static string Join(this IEnumerable<string> items, string sep = \",\", params object[] extra)")
    assert params is not None
    assert [p.type for p in params] == ["IEnumerable", "string", "object[]"]
    assert params[0].is_this and params[1].optional and params[2].varargs
    assert jt.arity_range(params) == (0, None)  # called as items.Join(...): the receiver is the first parameter
    assert jt.arity_range(jt.split_params("void f(int a, String b)")) == (2, 2)
    assert jt.return_type("public Document parse(String html)", "parse") == "Document"


def test_arg_type_score_orders_exact_before_widening_before_mismatch() -> None:
    def score(arg: str, param: str) -> int:
        return jt.arg_type_score(arg, param, ancestors=lambda name: [], repo_types=lambda name: False)

    assert score("String", "String") > score("int", "long") > score("String", "int")
    assert score("null", "String") >= 1


# ----------------------------------------------------------------------------------------------- extraction
def test_java_receiver_types_follow_lexical_scope() -> None:
    source = """
    class A { void m() {} }
    class B { void m() {} }
    class C {
        void run(A a) {
            a.m();
            { B a = new B(); a.m(); }
            a.m();
            for (B x : items()) { x.m(); }
            var y = new A(); y.m();
        }
    }
    """
    calls = [c for c in parse_source("C.java", source.encode(), "java").calls if c.name == "m"]
    assert [c.receiver_type for c in calls] == ["A", "B", "A", "B", "A"]


def test_java_new_is_a_call_and_argument_types_are_recorded() -> None:
    source = 'class K { void f(int n) { new Foo("x", n, 1.5); } }'
    calls = parse_source("K.java", source.encode(), "java").calls
    new = [c for c in calls if c.call_kind == "new"]
    assert [(c.name, c.arg_count, c.arg_types) for c in new] == [("Foo", 3, "String,int,double")]


def test_qualified_declared_type_is_kept_as_receiver_type() -> None:
    source = "class K { private Connection.Response res; void f() { res.parse(); } }"
    call = next(c for c in parse_source("K.java", source.encode(), "java").calls if c.name == "parse")
    assert call.receiver_type == "Connection.Response"


def test_csharp_chain_and_property_receivers() -> None:
    source = """
    class K {
        Reader reader;
        void F() { reader.Config.Parse(1); var c = reader.Open(); c.Close(); }
    }
    """
    calls = {c.name: c for c in parse_source("K.cs", source.encode(), "c_sharp").calls}
    assert calls["Parse"].chain == "T:Reader|f:Config"
    assert calls["Close"].chain == "T:Reader|m:Open/0"


# ----------------------------------------------------------------------------------------------- Java resolution
JSOUP_LIKE = {
    "Jsoup.java": """
public class Jsoup {
    public static Document parse(String html, String baseUri) { return null; }
    public static Document parse(String html) { return null; }
    public static Document parse(File file) { return null; }
}
""",
    "Document.java": """
public class Document extends Element {
    protected void outerHtml(Appendable accum) {}
}
""",
    "Element.java": """
public class Element extends Node {
    public String attr(String key, String value) { return null; }
    public String html() { return null; }
    public Element html(String h) { return this; }
    String doIs() { return is(evaluator()) ; }
    boolean is(String q) { return is(evaluator(q)); }
    boolean is(Evaluator e) { return true; }
}
""",
    "Node.java": """
public abstract class Node {
    public String attr(String key) { return null; }
    public String html() { return null; }
    public String outerHtml() { return null; }
}
""",
    "Use.java": """
class Use {
    void f(Document doc, Element el) {
        Jsoup.parse("x");
        Jsoup.parse("x", "y");
        el.attr("k");
        el.attr("k", "v");
        doc.outerHtml();
        doc.html();
        el.html("h");
    }
}
""",
}


def test_java_overloads_by_arity_and_types() -> None:
    edges, by_id = _edges(JSOUP_LIKE)
    assert _target(edges, by_id, "parse", 4)[:2] == ("Jsoup.parse", 4)
    assert _target(edges, by_id, "parse", 5)[:2] == ("Jsoup.parse", 3)
    assert _target(edges, by_id, "attr", 6)[:2] == ("Node.attr", 3)  # inherited, one argument
    assert _target(edges, by_id, "attr", 7)[:2] == ("Element.attr", 3)
    assert _target(edges, by_id, "html", 9)[:2] == ("Element.html", 4)  # html(): nearest declaration (an override)


def test_java_inherited_overload_is_not_shadowed_by_a_different_arity() -> None:
    edges, by_id = _edges(JSOUP_LIKE)
    # Document declares outerHtml(Appendable) only; the no-argument one is Node's
    assert _target(edges, by_id, "outerHtml", 8)[0] == "Node.outerHtml"


def test_java_delegating_overload_is_not_taken_for_recursion() -> None:
    edges, by_id = _edges(JSOUP_LIKE)
    # is(String) calls is(Evaluator) with an argument of unknown type: a sibling overload, not itself
    target = _target(edges, by_id, "is", 7)
    assert target[0] == "Element.is" and target[1] == 8


def test_java_super_and_this_chaining() -> None:
    edges, by_id = _edges(
        {
            "Base.java": "class Base {\n  void go() {}\n  void go(int n) {}\n}",
            "Sub.java": "class Sub extends Base { void go() { super.go(); this.go(1); } }",
        }
    )
    assert _target(edges, by_id, "go", 1)[:2] == ("Base.go", 2)  # super.go(): never Sub.go itself
    assert _target(edges, by_id, "go", 1)[2] in {"cha_inherited", "overload_arity"}


def test_java_nested_types_with_the_same_name_are_told_apart() -> None:
    edges, by_id = _edges(
        {
            "Connection.java": "interface Connection { interface Response { Document parse(); } }",
            "HttpConnection.java": """
class HttpConnection implements Connection {
    static class Response implements Connection.Response { public Document parse() { return null; } }
    private Connection.Response res;
    Document get() { return res.parse(); }
}
""",
        }
    )
    qualified, line, _ = _target(edges, by_id, "parse", 5)
    assert (qualified, line) == ("Connection.Response.parse", 1)


def test_java_same_named_ancestor_is_the_one_declared_beside_the_child() -> None:
    edges, by_id = _edges(
        {
            "Tag.java": "class Tag { boolean isSelfClosing() { return false; } }",
            "Token.java": """
abstract class Token {
    static abstract class Tag extends Token { boolean isSelfClosing() { return true; } }
    static final class StartTag extends Tag { }
}
""",
            "Use.java": "class Use { void f(Token.StartTag t) { t.isSelfClosing(); } }",
        }
    )
    qualified, _, _ = _target(edges, by_id, "isSelfClosing")
    assert qualified == "Token.Tag.isSelfClosing"


def test_java_known_library_receiver_is_decisively_external() -> None:
    edges, by_id = _edges(
        {
            "Entry.java": "class Entry { String getKey() { return null; } }",
            "Use.java": """
import java.util.Map;
class Use {
    void f(java.util.List<String> names, Map.Entry<String, String> e) { names.get(0); e.getKey(); }
    String get(int i) { return null; }
}
""",
        }
    )
    assert _target(edges, by_id, "getKey")[0] is None  # Map.Entry is not the repository's Entry
    assert _target(edges, by_id, "get")[0] is None  # List is a library type: no guessing from the method name


def test_java_constructor_call_resolves_to_the_class() -> None:
    edges, by_id = _edges(
        {
            "Foo.java": "class Foo { Foo() {} Foo(int n) {} }",
            "Use.java": "class Use { Object f() { return new Foo(1); } }",
        }
    )
    assert _target(edges, by_id, "Foo")[0] == "Foo"


def test_java_chain_types_resolve_through_declared_return_types() -> None:
    edges, by_id = _edges(
        {
            "Api.java": """
class Doc { Elements select(String q) { return null; } }
class Elements { Element first() { return null; } }
class Element { String text() { return null; } }
""",
            "Use.java": 'class Use { String f(Doc d) { return d.select("a").first().text(); } }',
        }
    )
    qualified, _, scope = _target(edges, by_id, "text")
    assert qualified == "Element.text" and scope == "chain_type"


# ----------------------------------------------------------------------------------------------- C# resolution
def test_csharp_overloads_extension_methods_and_delegate_properties() -> None:
    edges, by_id = _edges(
        {
            "Writer.cs": """
namespace N {
    public class Writer {
        public void Write(string s) { }
        public void Write(int n) { }
        public Func<Type, bool> CanResolve { get; set; }
        public void Run(Type t) { if (CanResolve(t)) { } Write(1); Write("a"); this.Helper(); }
    }
    public static class Ext { public static void Helper(this Writer w) { } }
}
""",
        }
    )
    assert _target(edges, by_id, "Write", 7)[1] == 5  # Write(1) -> Write(int)
    assert _target(edges, by_id, "CanResolve")[0] == "Writer.CanResolve"
    assert _target(edges, by_id, "Helper")[0] == "Ext.Helper"


def test_csharp_record_instantiation_goes_to_the_record() -> None:
    edges, by_id = _edges(
        {
            "Cfg.cs": "namespace N { public record Cfg { public Cfg(int a) { } public Cfg(int a, int b) { } } }",
            "Use.cs": "namespace N { class Use { object F() { return new Cfg(1); } } }",
        }
    )
    qualified, _, _ = _target(edges, by_id, "Cfg")
    assert qualified == "Cfg"


def test_csharp_preprocessor_branches_do_not_break_the_interface() -> None:
    source = """
namespace N;
public interface ILog
{
#if FEATURE
    ILog With(string a) => With(a, 1);
#else
    ILog With(string a);
#endif
    ILog With(string a, int b);
    void Write(string m);
}
"""
    parsed = parse_source("ILog.cs", source.encode(), "c_sharp")
    assert any(s.kind == "interface" and s.qualified_name == "ILog" for s in parsed.symbols)
    members = [s.qualified_name for s in parsed.symbols if s.kind in {"method", "function"}]
    assert "ILog.Write" in members and set(members) <= {"ILog.With", "ILog.Write"}


# ----------------------------------------------------------------------------------------------- incremental facts
def test_call_dependency_names_cover_types_chains_and_arguments() -> None:
    source = 'class K { Connection.Response r; void f(Foo foo) { r.parse(); foo.make().use(new Bar(), 1); } }'
    calls = parse_source("K.java", source.encode(), "java").calls
    names = _call_dependency_names(calls, jvm=True)
    assert {"parse", "make", "use", "Connection", "Response", "Foo", "Bar"} <= names
    assert _call_dependency_names(calls, jvm=False) == {c.name for c in calls}


@pytest.mark.parametrize("language,path", [("java", "A.java"), ("c_sharp", "A.cs")])
def test_empty_files_still_parse(language: str, path: str) -> None:
    assert parse_source(path, b"", language).calls == []


# ----------------------------------------------------------------------------------------------- I1 for Java
def test_incremental_equals_full_when_a_type_dependency_changes(tmp_path) -> None:
    """A caller's edge depends on names that live in *other* files (the declared return type of a chained call, the
    overloads of a method): editing only those files must re-resolve the caller (invariant I1)."""
    from evals import index_equivalence as ie

    root = tmp_path / "tree"
    root.mkdir()
    files = {
        "A.java": "class A { void f(B b, Z z) { var x = b.make(); x.run(); b.go(1); z.run(); } }",
        "B.java": "class B { X make() { return null; } void go(int n) {} }",
        "X.java": "class X { void run() {} }",
        "Y.java": "class Y { void run() {} }",
    }
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    ie.age_files(root)
    with ie.deterministic_edges():
        incremental = tmp_path / "inc"
        ie.build_incremental("demo", root, incremental)
        steps = [
            ("B.java", "class B { Y make() { return null; } void go(int n) {} }"),  # the chain type changes
            ("B.java", "class B { Y make() { return null; } void go(int n) {} void go(String s) {} }"),  # a new overload
            ("A.java", 'class A { void f(B b, Z z) { var x = b.make(); x.run(); b.go("s"); z.run(); } }'),  # the call changes
            ("Z.java", "class Z { }"),  # a new *type* the caller's receiver is declared with (no member of that name)
        ]
        for index, (name, text) in enumerate(steps):
            (root / name).write_text(text, encoding="utf-8")
            ie.age_files(root)
            ie.build_incremental("demo", root, incremental)
            full = tmp_path / f"full{index}"
            ie.build_full("demo", root, full)
            problems = ie.compare_dumps(
                ie.dump_snapshot(ie.database_path(full, "demo")), ie.dump_snapshot(ie.database_path(incremental, "demo"))
            )
            assert not problems, (index, problems)

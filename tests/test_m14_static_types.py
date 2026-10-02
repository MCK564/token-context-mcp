"""M14.2 unit tests: static types, bounds, element types, await unwrapping, lambda types, constructor chaining."""
from __future__ import annotations

import pytest

from token_context_mcp.parse import jvm_types as jt
from token_context_mcp.parse.lexical_edges import build_lexical_edges
from token_context_mcp.parse.treesitter import parse_source


def _edges(files: dict[str, str]):
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
    found = [e for e in edges if e.target_name == name and (line is None or e.source_line == line)]
    assert found, f"no edge for {name} at {line}: {[(e.target_name, e.source_line) for e in edges]}"
    edge = found[0]
    scope = next(x[6:] for x in edge.evidence if x.startswith("scope:"))
    if edge.target_symbol_id is None:
        return None, None, scope
    target = by_id[edge.target_symbol_id]
    return target.qualified_name, target.start_line, scope


def test_jvm_types_extract_generic_args():
    assert jt.extract_generic_args("Map<String, List<Foo>>") == ["String", "List<Foo>"]
    assert jt.extract_generic_args("Task<int>") == ["int"]
    assert jt.extract_generic_args("Dictionary<string, int>") == ["string", "int"]
    assert jt.extract_generic_args("NonGeneric") == []


def test_jvm_types_element_type_of():
    assert jt.element_type_of("List<String>") == "String"
    assert jt.element_type_of("int[]") == "int"
    assert jt.element_type_of("Map<String, User>") == "User"
    assert jt.element_type_of("Dictionary<string, int>") == "int"
    assert jt.element_type_of("IEnumerable<Node>") == "Node"


def test_jvm_types_unwrap_wrapper_type():
    assert jt.unwrap_wrapper_type("Task<string>") == "string"
    assert jt.unwrap_wrapper_type("ValueTask<int>") == "int"
    assert jt.unwrap_wrapper_type("CompletableFuture<User>") == "User"
    assert jt.unwrap_wrapper_type("Optional<Node>") == "Node"


def test_java_type_bounds_resolution():
    code = """
class Node { void remove() {} }
class Container<T extends Node> {
    void process(T item) {
        item.remove();
    }
}
"""
    edges, by_id = _edges({"Test.java": code})
    target, _, scope = _target(edges, by_id, "remove", 5)
    assert target == "Node.remove"
    assert scope in {"exact_receiver_type", "same_class", "cha_inherited"}


def test_csharp_type_bounds_resolution():
    code = """
public class Node { public void Remove() {} }
public class Container<T> where T : Node {
    public void Process(T item) {
        item.Remove();
    }
}
"""
    edges, by_id = _edges({"Test.cs": code})
    target, _, scope = _target(edges, by_id, "Remove", 5)
    assert target == "Node.Remove"


def test_csharp_collection_indexer_and_linq_element_type():
    code = """
using System.Collections.Generic;
using System.Linq;
public class Item { public void DoWork() {} public void Finish() {} }
public class Service {
    public void ProcessList(List<Item> items) {
        items[0].DoWork();
        items.First().Finish();
    }
}
"""
    edges, by_id = _edges({"Test.cs": code})
    target1, _, _ = _target(edges, by_id, "DoWork", 7)
    target2, _, _ = _target(edges, by_id, "Finish", 8)
    assert target1 == "Item.DoWork"
    assert target2 == "Item.Finish"


def test_java_foreach_element_type():
    code = """
import java.util.List;
class Item { void doWork() {} }
class Service {
    void process(List<Item> items) {
        for (var item : items) {
            item.doWork();
        }
    }
}
"""
    edges, by_id = _edges({"Test.java": code})
    target, _, _ = _target(edges, by_id, "doWork", 7)
    assert target == "Item.doWork"


def test_csharp_await_unwrapping():
    code = """
using System.Threading.Tasks;
public class Worker { public void Execute() {} }
public class Service {
    public async Task<Worker> GetWorkerAsync() => new Worker();
    public async Task Run() {
        var w = await GetWorkerAsync();
        w.Execute();
    }
}
"""
    edges, by_id = _edges({"Test.cs": code})
    target, _, _ = _target(edges, by_id, "Execute", 8)
    assert target == "Worker.Execute"


def test_constructor_chaining():
    java_code = """
class Base { Base(int n) {} }
class Sub extends Base {
    Sub() { this(1); }
    Sub(int n) { super(n); }
}
"""
    edges_j, by_id_j = _edges({"Test.java": java_code})
    assert any(e.target_name == "Sub" and e.edge_kind == "new" and e.source_line == 4 for e in edges_j)
    assert any(e.target_name == "Base" and e.edge_kind == "new" and e.source_line == 5 for e in edges_j)

    cs_code = """
public class Base { public Base(int n) {} }
public class Sub : Base {
    public Sub() : this(1) {}
    public Sub(int n) : base(n) {}
}
"""
    edges_cs, by_id_cs = _edges({"Test.cs": cs_code})
    assert any(e.target_name == "Sub" and e.edge_kind == "new" and e.source_line == 4 for e in edges_cs)
    assert any(e.target_name == "Base" and e.edge_kind == "new" and e.source_line == 5 for e in edges_cs)

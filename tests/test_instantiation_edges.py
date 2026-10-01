import pytest
from token_context_mcp.parse.treesitter import parse_source, SymbolRecord
from token_context_mcp.parse.lexical_edges import build_lexical_edges


def test_js_instantiation_same_file():
    code = b"""
class Service {
    run() { return 1; }
}

class Consumer {
    start() {
        const s = new Service();
        return s.run();
    }
}
"""
    res = parse_source("app.js", code, "javascript")
    calls = [(c.name, c.receiver, c.arg_count) for c in res.calls]
    assert ("Service", None, 0) in calls
    assert ("run", "s", 0) in calls

    edges = build_lexical_edges(
        symbols=res.symbols,
        source_by_path={"app.js": code.decode("utf-8")},
        calls_by_path={"app.js": res.calls},
    )
    ctor_edges = [e for e in edges if e.target_name == "Service"]
    assert len(ctor_edges) == 1
    assert ctor_edges[0].status == "resolved"
    assert ctor_edges[0].confidence >= 0.85
    target = next(s for s in res.symbols if s.symbol_id == ctor_edges[0].target_symbol_id)
    assert target.kind == "class"
    assert target.name == "Service"


def test_ts_instantiation_with_type_arguments():
    code = b"""
export class Box<T> {
    value: T;
}

export function make(): Box<number> {
    return new Box<number>();
}
"""
    res = parse_source("box.ts", code, "typescript")
    calls = [(c.name, c.receiver, c.arg_count) for c in res.calls]
    assert ("Box", None, 0) in calls

    edges = build_lexical_edges(
        symbols=res.symbols,
        source_by_path={"box.ts": code.decode("utf-8")},
        calls_by_path={"box.ts": res.calls},
    )
    ctor_edges = [e for e in edges if e.target_name == "Box"]
    assert len(ctor_edges) == 1
    assert ctor_edges[0].status == "resolved"
    target = next(s for s in res.symbols if s.symbol_id == ctor_edges[0].target_symbol_id)
    assert target.kind == "class"


def test_csharp_instantiation_resolves_to_class():
    code = b"""
namespace MyApp {
    public class Worker {
        public Worker(int id) {}
        public void DoWork() {}
    }

    public class App {
        public void Run() {
            var w = new Worker(42);
        }
    }
}
"""
    res = parse_source("app.cs", code, "c_sharp")
    calls = [(c.name, c.receiver, c.arg_count) for c in res.calls]
    assert ("Worker", None, 1) in calls

    edges = build_lexical_edges(
        symbols=res.symbols,
        source_by_path={"app.cs": code.decode("utf-8")},
        calls_by_path={"app.cs": res.calls},
    )
    ctor_edges = [e for e in edges if e.target_name == "Worker"]
    assert len(ctor_edges) == 1
    assert ctor_edges[0].status == "resolved"
    worker_sym = next(s for s in res.symbols if s.symbol_id == ctor_edges[0].target_symbol_id)
    assert worker_sym.kind == "class"
    assert worker_sym.name == "Worker"


def test_csharp_instantiation_qualified_generic():
    code = b"""
namespace MyLib {
    public class DataStore<T> {
        public DataStore() {}
    }

    public class Program {
        public void Init() {
            var ds = new MyLib.DataStore<string>();
        }
    }
}
"""
    res = parse_source("program.cs", code, "c_sharp")
    calls = [(c.name, c.receiver, c.arg_count) for c in res.calls]
    assert ("DataStore", "MyLib", 0) in calls

    edges = build_lexical_edges(
        symbols=res.symbols,
        source_by_path={"program.cs": code.decode("utf-8")},
        calls_by_path={"program.cs": res.calls},
        file_namespaces={"program.cs": res.namespaces},
    )
    ds_edges = [e for e in edges if e.target_name == "DataStore"]
    assert len(ds_edges) == 1
    assert ds_edges[0].status == "resolved"
    target_sym = next(s for s in res.symbols if s.symbol_id == ds_edges[0].target_symbol_id)
    assert target_sym.kind == "class"

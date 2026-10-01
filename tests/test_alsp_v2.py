from __future__ import annotations

import time
from pathlib import Path

from token_context_mcp.index.sqlite_store import SQLiteStore
from token_context_mcp.models import FileRecord, SymbolRecord
from token_context_mcp.parse.lexical_edges import build_lexical_edges
from token_context_mcp.parse.treesitter import CallRecord, parse_source


def _make_symbol(symbol_id: str, path: str, name: str, qualified_name: str, kind: str, start_byte: int, end_byte: int) -> SymbolRecord:
    return SymbolRecord(
        symbol_id=symbol_id,
        path=path,
        name=name,
        qualified_name=qualified_name,
        kind=kind,
        signature=f"def {name}()",
        start_line=1,
        end_line=10,
        start_byte=start_byte,
        end_byte=end_byte,
        body_start_byte=start_byte + 10,
        body_end_byte=end_byte,
        is_private=False,
    )


def test_treesitter_inheritance_extraction_python() -> None:
    code = b"""
class Base:
    def base_method(self): pass

class Intermediate(Base):
    pass

class Child(Intermediate, Other):
    def child_method(self): pass
"""
    parsed = parse_source("test_inh.py", code, "python")
    assert parsed.inheritance.get("Base") == []
    assert parsed.inheritance.get("Intermediate") == ["Base"]
    assert parsed.inheritance.get("Child") == ["Intermediate", "Other"]


def test_treesitter_inheritance_extraction_typescript() -> None:
    code = b"""
class BaseService {}
interface ILogger {}
class WorkerService extends BaseService implements ILogger {
    run() {}
}
"""
    parsed = parse_source("test_inh.ts", code, "typescript")
    assert "BaseService" in parsed.inheritance.get("WorkerService", [])
    assert "ILogger" in parsed.inheritance.get("WorkerService", [])


def test_pseudo_ssa_single_assignment_type_inference() -> None:
    code = b"""
def run_job():
    worker = Worker()
    worker.execute()
"""
    parsed = parse_source("app.py", code, "python")
    call = next(c for c in parsed.calls if c.name == "execute")
    assert call.receiver == "worker"
    assert call.receiver_type == "Worker"
    assert call.is_tainted is False


def test_pseudo_ssa_parameter_type_annotation() -> None:
    code = b"""
def process_invoice(processor: InvoiceProcessor):
    processor.parse()
"""
    parsed = parse_source("app.py", code, "python")
    call = next(c for c in parsed.calls if c.name == "parse")
    assert call.receiver == "processor"
    assert call.receiver_type == "InvoiceProcessor"
    assert call.is_tainted is False


def test_defensive_heuristic_tainted_reassignment() -> None:
    code = b"""
def process():
    obj = InitialService()
    obj = ChangedService()
    obj.execute()
"""
    parsed = parse_source("app.py", code, "python")
    call = next(c for c in parsed.calls if c.name == "execute")
    assert call.receiver == "obj"
    assert call.is_tainted is True
    assert call.receiver_type is None


def test_defensive_heuristic_tainted_conditional_branch() -> None:
    code = b"""
def process(flag: bool):
    if flag:
        handler = CustomHandler()
    handler.handle()
"""
    parsed = parse_source("app.py", code, "python")
    call = next(c for c in parsed.calls if c.name == "handle")
    assert call.receiver == "handler"
    assert call.is_tainted is True


def test_class_hierarchy_analysis_cha_resolution() -> None:
    caller_code = b"""class Child(Base):
    def child_action(self):
        self.base_action()
"""
    parsed = parse_source("child.py", caller_code, "python")
    child_act = _make_symbol("child:action", "child.py", "child_action", "Child.child_action", "method", 18, 70)
    base_act = _make_symbol("base:action", "base.py", "base_action", "Base.base_action", "method", 0, 50)
    other_act = _make_symbol("other:action", "other.py", "base_action", "Unrelated.base_action", "method", 0, 50)

    edges = build_lexical_edges(
        [child_act, base_act, other_act],
        {"child.py": caller_code.decode()},
        calls_by_path={"child.py": parsed.calls},
        class_hierarchy={"Child": ["Base"]},
    )

    base_edge = next(e for e in edges if e.target_name == "base_action")
    assert base_edge.status == "resolved"
    assert base_edge.target_symbol_id == "base:action"
    assert base_edge.confidence == 0.90
    assert "scope:cha_inherited" in base_edge.evidence


def test_tainted_receiver_downgrades_to_ambiguous_010() -> None:
    caller_code = b"""def run():
    client = A()
    client = B()
    client.do_work()
"""
    parsed = parse_source("app.py", caller_code, "python")
    caller_sym = _make_symbol("app:run", "app.py", "run", "run", "function", 0, 60)
    target_a = _make_symbol("a:do_work", "a.py", "do_work", "A.do_work", "method", 0, 50)
    target_b = _make_symbol("b:do_work", "b.py", "do_work", "B.do_work", "method", 0, 50)

    edges = build_lexical_edges(
        [caller_sym, target_a, target_b],
        {"app.py": caller_code.decode()},
        calls_by_path={"app.py": parsed.calls},
    )

    work_edge = next(e for e in edges if e.target_name == "do_work")
    assert work_edge.status == "ambiguous"
    assert work_edge.target_symbol_id is None
    assert work_edge.confidence == 0.10
    assert "tainted_poly_receiver" in work_edge.evidence


def test_edge_work_budget_is_deterministic() -> None:
    """The per-file edge budget is counted in work units (not seconds): same input, same edges, any machine."""
    import token_context_mcp.parse.lexical_edges as le

    sym = _make_symbol("caller", "huge.py", "caller_fn", "caller_fn", "function", 0, 1000)
    calls = [
        CallRecord(name=f"call_{i}", receiver=None, line=i + 1, start_byte=10 + i * 5, end_byte=15 + i * 5)
        for i in range(100)
    ]
    target = _make_symbol("callee", "lib.py", "call_99", "call_99", "function", 0, 50)
    previous = le.FILE_EDGE_WORK_BUDGET
    try:
        le.FILE_EDGE_WORK_BUDGET = 10  # one symbol per call: the 11th call and every later one is over budget
        first = build_lexical_edges([sym, target], {}, calls_by_path={"huge.py": calls})
        second = build_lexical_edges([sym, target], {}, calls_by_path={"huge.py": calls})
        assert [(e.target_name, e.status, e.evidence) for e in first] == [(e.target_name, e.status, e.evidence) for e in second]
        over = [e for e in first if "edge_work_budget" in e.evidence]
        assert len(over) == 100 - 10
        assert all(e.status == "ambiguous" and e.confidence == 0.10 and e.target_symbol_id is None for e in over)
        le.FILE_EDGE_WORK_BUDGET = 10_000
        unlimited = build_lexical_edges([sym, target], {}, calls_by_path={"huge.py": calls})
        assert not [e for e in unlimited if "edge_work_budget" in e.evidence]
        assert any(e.target_name == "call_99" and e.status == "resolved" for e in unlimited)
    finally:
        le.FILE_EDGE_WORK_BUDGET = previous


def test_sqlite_store_class_hierarchy_and_compaction(tmp_path: Path) -> None:
    db_file = tmp_path / "test_cha.sqlite"
    store = SQLiteStore(db_file)
    store.initialize()

    class_sym = _make_symbol("sym_child", "child.py", "Child", "Child", "class", 0, 100)
    parent_sym = _make_symbol("sym_base", "base.py", "Base", "Base", "class", 0, 100)

    store.write_snapshot(
        metadata={"schema_version": "1.0"},
        files=[
            FileRecord("child.py", "sha1", 100, 1000, "python", "parsed", []),
            FileRecord("base.py", "sha2", 100, 1000, "python", "parsed", []),
        ],
        symbols=[class_sym, parent_sym],
        edges=[],
        imports={},
        symbol_bodies={},
        source_bodies={},
        class_hierarchy=[("sym_child", "Base", "sym_base")],
    )

    ancestors = store.class_ancestors("sym_child")
    assert len(ancestors) == 1
    assert ancestors[0] == ("Base", "sym_base")

    all_h = store.all_class_hierarchies()
    assert all_h.get("sym_child") == ["Base"]

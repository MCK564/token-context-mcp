from __future__ import annotations

from token_context_mcp.models import SymbolRecord
from token_context_mcp.parse.lexical_edges import build_lexical_edges
from token_context_mcp.parse.treesitter import parse_source


def test_python_call_extraction_and_receiver_detection() -> None:
    code = b"""
class Runner:
    def execute(self):
        self.run()
        Worker.build()
        helper()
"""
    parsed = parse_source("test.py", code, "python")
    call_names = {c.name for c in parsed.calls}
    assert "run" in call_names
    assert "build" in call_names
    assert "helper" in call_names

    self_call = next(c for c in parsed.calls if c.name == "run")
    assert self_call.receiver == "self"

    worker_call = next(c for c in parsed.calls if c.name == "build")
    assert worker_call.receiver == "Worker"

    helper_call = next(c for c in parsed.calls if c.name == "helper")
    assert helper_call.receiver is None


def test_self_call_resolves_to_same_class_with_high_confidence() -> None:
    def symbol(symbol_id: str, path: str, name: str, qualified_name: str, start_byte: int, end_byte: int) -> SymbolRecord:
        return SymbolRecord(
            symbol_id=symbol_id,
            path=path,
            name=name,
            qualified_name=qualified_name,
            kind="method",
            signature=f"def {name}()",
            start_line=1,
            end_line=5,
            start_byte=start_byte,
            end_byte=end_byte,
            body_start_byte=start_byte + 10,
            body_end_byte=end_byte,
            is_private=False,
        )

    code = b"""class Worker:
    def run(self):
        self.step()
    def step(self):
        pass
"""
    parsed = parse_source("worker.py", code, "python")
    run_sym = symbol("w-run", "worker.py", "run", "Worker.run", 18, 55)
    step_sym = symbol("w-step", "worker.py", "step", "Worker.step", 60, 95)
    other_step = symbol("other-step", "other.py", "step", "Other.step", 0, 50)

    edges = build_lexical_edges(
        [run_sym, step_sym, other_step],
        {"worker.py": code.decode()},
        calls_by_path={"worker.py": parsed.calls},
    )

    step_edge = next(e for e in edges if e.target_name == "step")
    assert step_edge.status == "resolved"
    assert step_edge.target_symbol_id == "w-step"
    assert step_edge.confidence == 0.95
    assert "receiver:self" in step_edge.evidence


def test_import_aware_candidate_resolution() -> None:
    def symbol(symbol_id: str, path: str, name: str, qualified_name: str, start_byte: int, end_byte: int) -> SymbolRecord:
        return SymbolRecord(
            symbol_id=symbol_id,
            path=path,
            name=name,
            qualified_name=qualified_name,
            kind="function",
            signature=f"def {name}()",
            start_line=1,
            end_line=5,
            start_byte=start_byte,
            end_byte=end_byte,
            body_start_byte=start_byte + 10,
            body_end_byte=end_byte,
            is_private=False,
        )

    caller_code = b"""from core.engine import execute
def main():
    execute()
"""
    parsed = parse_source("app.py", caller_code, "python")
    main_sym = symbol("app:main", "app.py", "main", "main", 32, 60)
    target_engine = symbol("engine:exec", "core/engine.py", "execute", "execute", 0, 50)
    other_engine = symbol("other:exec", "vendor/other.py", "execute", "execute", 0, 50)

    edges = build_lexical_edges(
        [main_sym, target_engine, other_engine],
        {"app.py": caller_code.decode()},
        calls_by_path={"app.py": parsed.calls},
        imports_by_path={"app.py": ["core.engine"]},
    )

    exec_edge = next(e for e in edges if e.target_name == "execute")
    assert exec_edge.status == "resolved"
    assert exec_edge.target_symbol_id == "engine:exec"
    assert exec_edge.confidence >= 0.85


def test_instance_attribute_attr_type_resolution() -> None:
    def symbol(symbol_id: str, path: str, name: str, qualified_name: str, start_byte: int, end_byte: int) -> SymbolRecord:
        return SymbolRecord(
            symbol_id=symbol_id,
            path=path,
            name=name,
            qualified_name=qualified_name,
            kind="method",
            signature=f"def {name}()",
            start_line=1,
            end_line=10,
            start_byte=start_byte,
            end_byte=end_byte,
            body_start_byte=start_byte + 10,
            body_end_byte=end_byte,
            is_private=False,
        )

    service_code = b"""class Service:
    def __init__(self, p):
        self.store = MemoryStore(p)
    def memory_get(self, k):
        return self.store.get(k)
"""
    parsed = parse_source("service.py", service_code, "python")
    mem_get_call = next(c for c in parsed.calls if c.name == "get")
    assert mem_get_call.receiver == "self.store"
    assert mem_get_call.receiver_type == "MemoryStore"

    svc_sym = symbol("svc:mem_get", "service.py", "memory_get", "Service.memory_get", 80, 140)
    store_get_sym = symbol("store:get", "store.py", "get", "MemoryStore.get", 0, 50)

    other_get_sym = symbol("dict:get", "other.py", "get", "DictLike.get", 0, 50)

    edges = build_lexical_edges(
        [svc_sym, store_get_sym, other_get_sym],
        {"service.py": service_code.decode()},
        calls_by_path={"service.py": parsed.calls},
    )

    get_edges = [e for e in edges if e.target_name == "get"]
    assert len(get_edges) == 1
    edge = get_edges[0]
    assert edge.status == "resolved"
    assert edge.target_symbol_id == "store:get"
    assert "scope:attr_type" in edge.evidence
    assert "receiver:self.store" in edge.evidence
    assert "type:MemoryStore" in edge.evidence


def test_generic_method_on_container_type_does_not_link_to_store_get() -> None:
    def symbol(symbol_id: str, path: str, name: str, qualified_name: str, start_byte: int, end_byte: int) -> SymbolRecord:
        return SymbolRecord(
            symbol_id=symbol_id,
            path=path,
            name=name,
            qualified_name=qualified_name,
            kind="function",
            signature=f"def {name}()",
            start_line=1,
            end_line=5,
            start_byte=start_byte,
            end_byte=end_byte,
            body_start_byte=start_byte + 10,
            body_end_byte=end_byte,
            is_private=False,
        )

    caller_code = b"""def process(x: dict[str, list[str]]):
    return x.get("foo")
"""
    parsed = parse_source("worker.py", caller_code, "python")
    proc_sym = symbol("worker:proc", "worker.py", "process", "process", 0, 50)
    store_get = symbol("mem:get", "store.py", "get", "MemoryStore.get", 0, 50)

    edges = build_lexical_edges(
        [proc_sym, store_get],
        {"worker.py": caller_code.decode()},
        calls_by_path={"worker.py": parsed.calls},
    )

    resolved_to_store = [e for e in edges if e.target_symbol_id == "mem:get"]
    assert len(resolved_to_store) == 0


def test_return_type_propagation_and_resolution() -> None:
    def symbol(symbol_id: str, path: str, name: str, qualified_name: str, start_byte: int, end_byte: int, sig: str = "") -> SymbolRecord:
        return SymbolRecord(
            symbol_id=symbol_id,
            path=path,
            name=name,
            qualified_name=qualified_name,
            kind="function",
            signature=sig or f"def {name}()",
            start_line=1,
            end_line=5,
            start_byte=start_byte,
            end_byte=end_byte,
            body_start_byte=start_byte + 10,
            body_end_byte=end_byte,
            is_private=False,
        )

    code = b"""def mk() -> Store:
    return Store()

def test_fn():
    s = mk()
    s.put("k", "v")
"""
    parsed = parse_source("app.py", code, "python")
    put_call = next(c for c in parsed.calls if c.name == "put")
    assert put_call.receiver == "s"
    assert put_call.receiver_type == "Store"

    test_fn_sym = symbol("app:test_fn", "app.py", "test_fn", "test_fn", 35, 80)
    mk_sym = symbol("app:mk", "app.py", "mk", "mk", 0, 30, sig="def mk() -> Store:")
    store_put = symbol("store:put", "store.py", "put", "Store.put", 0, 50)
    other_put = symbol("queue:put", "queue.py", "put", "Queue.put", 0, 50)

    edges = build_lexical_edges(
        [test_fn_sym, mk_sym, store_put, other_put],
        {"app.py": code.decode()},
        calls_by_path={"app.py": parsed.calls},
    )

    put_edge = next(e for e in edges if e.target_name == "put")
    assert put_edge.status == "resolved"
    assert put_edge.target_symbol_id == "store:put"


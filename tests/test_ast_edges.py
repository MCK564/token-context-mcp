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

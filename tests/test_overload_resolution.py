from __future__ import annotations

from token_context_mcp.models import SymbolRecord
from token_context_mcp.parse.lexical_edges import _count_params, _resolve_candidate


def make_sym(symbol_id: str, path: str, name: str, qualified_name: str, kind: str, sig: str, start_line: int) -> SymbolRecord:
    return SymbolRecord(
        symbol_id=symbol_id,
        path=path,
        name=name,
        qualified_name=qualified_name,
        kind=kind,
        signature=sig,
        start_line=start_line,
        end_line=start_line + 5,
        start_byte=0,
        end_byte=100,
        body_start_byte=10,
        body_end_byte=90,
        is_private=False,
    )


def test_count_params() -> None:
    assert _count_params("public void Foo(int a, string b)") == 2
    assert _count_params("public void Empty()") == 0
    assert _count_params("public T Create<T>(int id, Dictionary<string, List<int>> map, Action<int, string> cb)") == 3
    assert _count_params("(a: number, b: string): void") == 2
    assert _count_params("(x: any) => void") == 1
    assert _count_params("void Bar(in int a, out string b, ref double c)") == 3


def test_csharp_overload_arity_match() -> None:
    source = make_sym("c_sharp:src/Worker.cs:Worker.Execute:100", "src/Worker.cs", "Execute", "Worker.Execute", "method", "()", 10)
    overload1 = make_sym("c_sharp:src/Worker.cs:Worker.DoTask:200", "src/Worker.cs", "DoTask", "Worker.DoTask", "method", "public void DoTask(int id)", 20)
    overload2 = make_sym("c_sharp:src/Worker.cs:Worker.DoTask:300", "src/Worker.cs", "DoTask", "Worker.DoTask", "method", "public void DoTask(int id, string name)", 30)

    # Call with 2 arguments should match overload2
    resolved, scope, conf = _resolve_candidate(
        source=source,
        candidates=[overload1, overload2],
        receiver=None,
        call_arg_count=2,
    )
    assert resolved == overload2
    assert scope == "overload_arity"
    assert conf == 0.85

    # Call with 1 argument should match overload1
    resolved, scope, conf = _resolve_candidate(
        source=source,
        candidates=[overload1, overload2],
        receiver=None,
        call_arg_count=1,
    )
    assert resolved == overload1
    assert scope == "overload_arity"
    assert conf == 0.85


def test_csharp_overload_group_fallback() -> None:
    source = make_sym("c_sharp:src/Worker.cs:Worker.Execute:100", "src/Worker.cs", "Execute", "Worker.Execute", "method", "()", 10)
    overload1 = make_sym("c_sharp:src/Worker.cs:Worker.DoTask:200", "src/Worker.cs", "DoTask", "Worker.DoTask", "method", "public void DoTask(int id)", 20)
    overload2 = make_sym("c_sharp:src/Worker.cs:Worker.DoTask:300", "src/Worker.cs", "DoTask", "Worker.DoTask", "method", "public void DoTask(string label)", 30)

    # Call with 1 argument matches BOTH overloads -> falls back to smallest start_line (overload1 at line 20)
    resolved, scope, conf = _resolve_candidate(
        source=source,
        candidates=[overload1, overload2],
        receiver=None,
        call_arg_count=1,
    )
    assert resolved == overload1
    assert scope == "overload_group"
    assert conf == 0.70

    # Call with unknown arg_count (None) -> falls back to smallest start_line
    resolved, scope, conf = _resolve_candidate(
        source=source,
        candidates=[overload1, overload2],
        receiver=None,
        call_arg_count=None,
    )
    assert resolved == overload1
    assert scope == "overload_group"
    assert conf == 0.70


def test_python_overloads_not_resolved() -> None:
    source = make_sym("python:app/service.py:Service.run:10", "app/service.py", "run", "Service.run", "method", "()", 10)
    # In Python, getter and setter have the same qualified name
    cand1 = make_sym("python:app/service.py:Service.prop:20", "app/service.py", "prop", "Service.prop", "method", "(self)", 20)
    cand2 = make_sym("python:app/service.py:Service.prop:30", "app/service.py", "prop", "Service.prop", "method", "(self, val)", 30)

    resolved, scope, conf = _resolve_candidate(
        source=source,
        candidates=[cand1, cand2],
        receiver=None,
        call_arg_count=1,
    )
    # Python must NOT use overload_arity or overload_group (must return ambiguous)
    assert scope == "same_file_ambiguous"
    assert resolved is None

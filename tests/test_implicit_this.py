from __future__ import annotations

from token_context_mcp.models import SymbolRecord
from token_context_mcp.parse.lexical_edges import _resolve_candidate


def make_sym(symbol_id: str, path: str, name: str, qualified_name: str, kind: str) -> SymbolRecord:
    return SymbolRecord(
        symbol_id=symbol_id,
        path=path,
        name=name,
        qualified_name=qualified_name,
        kind=kind,
        signature="()",
        start_line=1,
        end_line=10,
        start_byte=0,
        end_byte=100,
        body_start_byte=10,
        body_end_byte=90,
        is_private=False,
    )


def test_implicit_this_same_file() -> None:
    source = make_sym("c_sharp:src/Foo.cs:Foo.Bar:1234", "src/Foo.cs", "Bar", "Foo.Bar", "method")
    target = make_sym("c_sharp:src/Foo.cs:Foo.Helper:5678", "src/Foo.cs", "Helper", "Foo.Helper", "method")
    other = make_sym("c_sharp:src/Other.cs:Other.Helper:9999", "src/Other.cs", "Helper", "Other.Helper", "method")

    resolved, scope, conf = _resolve_candidate(
        source=source,
        candidates=[target, other],
        receiver=None,
    )
    assert resolved == target
    assert scope == "implicit_this"
    assert conf == 0.90


def test_implicit_this_partial_class() -> None:
    source = make_sym("c_sharp:src/Foo.Part1.cs:Foo.Bar:1234", "src/Foo.Part1.cs", "Bar", "Foo.Bar", "method")
    target = make_sym("c_sharp:src/Foo.Part2.cs:Foo.Helper:5678", "src/Foo.Part2.cs", "Helper", "Foo.Helper", "method")
    other = make_sym("c_sharp:src/Other.cs:Other.Helper:9999", "src/Other.cs", "Helper", "Other.Helper", "method")

    resolved, scope, conf = _resolve_candidate(
        source=source,
        candidates=[target, other],
        receiver=None,
    )
    assert resolved == target
    assert scope == "implicit_this_partial"
    assert conf == 0.85


def test_implicit_this_cha_inherited() -> None:
    source = make_sym("c_sharp:src/Child.cs:Child.Bar:1234", "src/Child.cs", "Bar", "Child.Bar", "method")
    target = make_sym("c_sharp:src/Base.cs:BaseClass.BaseHelper:5678", "src/Base.cs", "BaseHelper", "BaseClass.BaseHelper", "method")

    class_hierarchy = {"Child": ["BaseClass"]}
    resolved, scope, conf = _resolve_candidate(
        source=source,
        candidates=[target],
        receiver=None,
        class_hierarchy=class_hierarchy,
    )
    assert resolved == target
    assert scope == "cha_inherited"
    assert conf == 0.90


def test_python_not_affected_by_implicit_this() -> None:
    source = make_sym("python:app/foo.py:Foo.bar:1234", "app/foo.py", "bar", "Foo.bar", "method")
    target = make_sym("python:other_pkg/other.py:helper:5678", "other_pkg/other.py", "helper", "helper", "function")

    resolved, scope, conf = _resolve_candidate(
        source=source,
        candidates=[target],
        receiver=None,
    )
    assert scope == "global"

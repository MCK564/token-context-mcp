"""M12 follow-up: JS/TS object-literal methods and chained assignments.

M12.1 started qualifying methods of ``const x = {...}`` / ``module.exports = {...}`` and skipped *every*
``method_definition`` inside an object literal, so methods of objects passed as call arguments
(``describe("s", { test() {} })``) stopped being indexed (hono -45, fastify -88, zod -415 symbols on the dev/held-out
repos).  The generic path now skips only members an owning pattern already emitted.
"""
from __future__ import annotations

import pytest

from token_context_mcp.parse.treesitter import parse_source


def _symbols(language: str, path: str, source: str) -> list[tuple[str, str]]:
    result = parse_source(path, source.encode("utf-8"), language)
    return sorted((s.qualified_name, s.kind) for s in result.symbols)


@pytest.mark.parametrize(("language", "path"), [("typescript", "a.ts"), ("javascript", "a.js")])
def test_methods_of_object_literal_passed_as_argument_are_indexed(language: str, path: str) -> None:
    source = 'function helper(x) { return x + 1 }\nconst suite = run("s", {\n  "quoted name"() { return helper(1); },\n  plain() { return helper(2); },\n});\n'
    names = _symbols(language, path, source)
    assert ("plain", "method") in names
    assert ('"quoted name"', "method") in names
    assert ("helper", "function") in names


@pytest.mark.parametrize(("language", "path"), [("typescript", "a.ts"), ("javascript", "a.js")])
def test_top_level_object_methods_are_indexed_once_with_owner_prefix(language: str, path: str) -> None:
    names = _symbols(language, path, "const api = {\n  get() { return 1 },\n  post: function () { return 2 },\n};\n")
    assert names == [("api.get", "method"), ("api.post", "method")]


def test_module_exports_object_methods_are_indexed_once() -> None:
    names = _symbols("javascript", "a.js", "module.exports = {\n  parse() { return 1 },\n  stringify: function () { return 2 },\n};\n")
    assert names == [("parse", "function"), ("stringify", "function")]


def test_prototype_object_methods_are_indexed_once() -> None:
    names = _symbols("javascript", "a.js", "function Box() {}\nBox.prototype = {\n  open() { return 1 },\n};\n")
    assert ("Box.open", "method") in names
    assert [n for n, _ in names].count("Box.open") == 1
    assert "open" not in [n for n, _ in names]


def test_return_value_and_nested_object_methods_are_indexed() -> None:
    names = _symbols("typescript", "a.ts", "function make() {\n  return { run() { return 1 } };\n}\nconst cfg = { inner: { go() { return 2 } } };\n")
    flat = [n for n, _ in names]
    assert "run" in flat
    assert "go" in flat


def test_object_inside_function_is_not_dropped() -> None:
    names = _symbols("javascript", "a.js", "function setup() {\n  const local = { step() { return 1 } };\n  return local;\n}\n")
    assert "step" in [n for n, _ in names]


def test_chained_assignment_binds_every_name() -> None:
    names = _symbols("javascript", "a.js", "var res = {};\nres.set = res.header = function header(field, val) { return field; };\n")
    assert ("res.set", "method") in names
    assert ("res.header", "method") in names


def test_chained_exports_object_is_indexed() -> None:
    names = _symbols("javascript", "a.js", "exports = module.exports = {\n  create() { return 1 },\n};\n")
    assert ("create", "function") in names


def test_non_chained_assignment_is_unchanged() -> None:
    names = _symbols("javascript", "a.js", "var app = {};\napp.init = function () { return 1; };\n")
    assert names == [("app.init", "method")]


def test_python_parse_is_untouched() -> None:
    names = _symbols("python", "a.py", "class A:\n    def run(self):\n        return 1\n")
    assert names == [("A", "class"), ("A.run", "function")]

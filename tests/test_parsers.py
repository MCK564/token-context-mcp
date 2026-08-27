from __future__ import annotations

from token_context_mcp.parse.treesitter import parse_source


def test_python_parser_extracts_qualified_symbols() -> None:
    parsed = parse_source("demo.py", b"class Service:\n    def run(self):\n        return 1\n", "python")
    assert [symbol.qualified_name for symbol in parsed.symbols] == ["Service", "Service.run"]


def test_typescript_parser_extracts_function() -> None:
    parsed = parse_source("demo.ts", b"export function run(value: string): string { return value; }\n", "typescript")
    assert [symbol.name for symbol in parsed.symbols] == ["run"]


from __future__ import annotations

from pathlib import Path

from token_context_mcp.constants import SUPPORTED_EXTENSIONS
from token_context_mcp.parse.treesitter import parse_source


def test_python_parser_extracts_qualified_symbols() -> None:
    parsed = parse_source("demo.py", b"class Service:\n    def run(self):\n        return 1\n", "python")
    assert [symbol.qualified_name for symbol in parsed.symbols] == ["Service", "Service.run"]


def test_typescript_parser_extracts_function() -> None:
    parsed = parse_source("demo.ts", b"export function run(value: string): string { return value; }\n", "typescript")
    assert [symbol.name for symbol in parsed.symbols] == ["run"]


def test_python_imports_are_tree_sitter_extracted_and_relative_imports_are_normalized() -> None:
    fixture = Path(__file__).parent / "fixtures" / "imports.py"
    parsed = parse_source("pkg/sub/module.py", fixture.read_bytes(), "python")
    assert parsed.imports == ["a.b.c", "pkg.pkg", "pkg.sub.helpers"]
    assert "dynamic_import_detected" in parsed.warnings


def test_javascript_and_typescript_import_forms_are_extracted() -> None:
    fixtures = Path(__file__).parent / "fixtures"
    javascript = parse_source(
        "demo.js",
        (fixtures / "imports.js").read_bytes(),
        "javascript",
    )
    assert javascript.imports == ["./reexport", "./side-effect", "./value", "commonjs"]

    typescript = parse_source(
        "demo.ts",
        (fixtures / "imports.ts").read_bytes(),
        "typescript",
    )
    assert typescript.imports == ["./public-types", "./types"]


def test_tsx_indexes_arrow_functions_function_expressions_and_anonymous_default() -> None:
    fixture = Path(__file__).parent / "fixtures" / "modern.tsx"
    parsed = parse_source("modern.tsx", fixture.read_bytes(), "tsx")
    symbols = {symbol.name: symbol for symbol in parsed.symbols}
    assert {"View", "useValue", "modern"} <= symbols.keys()
    assert symbols["View"].start_line == 2
    assert symbols["View"].end_line == 2
    assert symbols["useValue"].start_line == 3
    assert symbols["modern"].start_line == 4
    assert "parsed_file_has_zero_symbols" not in parsed.warnings


def test_successful_symbol_free_file_is_explicitly_flagged() -> None:
    parsed = parse_source("imports.py", b"import only_this\n", "python")
    assert parsed.symbols == []
    assert "parsed_file_has_zero_symbols" in parsed.warnings


def test_java_parser_extracts_types_methods_and_imports() -> None:
    parsed = parse_source(
        "Hello.java",
        b"package demo; import java.util.List; public class Hello { public int run(String x) { return 1; } }",
        "java",
    )
    assert {symbol.name for symbol in parsed.symbols} >= {"Hello", "run"}
    assert parsed.imports == ["java.util.List"]


def test_csharp_parser_extracts_types_methods_properties_and_using() -> None:
    parsed = parse_source(
        "Hello.cs",
        b"using System; namespace Demo { public class Hello { public int Run(string x) { return 1; } public string Name { get; set; } } }",
        "c_sharp",
    )
    assert {symbol.name for symbol in parsed.symbols} >= {"Hello", "Run", "Name"}
    assert parsed.imports == ["System"]


def test_html_parser_extracts_named_elements_without_treating_markup_as_imports() -> None:
    parsed = parse_source(
        "index.html",
        b"<html><body><div><span>Hello</span></div></body></html>",
        "html",
    )
    assert {symbol.name for symbol in parsed.symbols} >= {"html", "body", "div", "span"}
    assert parsed.imports == []


def test_css_parser_extracts_rules_and_media_blocks_without_imports() -> None:
    parsed = parse_source(
        "site.css",
        b".card, #main { color: red; } @media screen { body { margin: 0; } }",
        "css",
    )
    assert any(symbol.kind == "rule" for symbol in parsed.symbols)
    assert any(symbol.kind == "media" for symbol in parsed.symbols)
    assert parsed.imports == []


def test_index_extension_mapping_covers_requested_language_families() -> None:
    assert SUPPORTED_EXTENSIONS == {
        ".py": "python",
        ".pyi": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".java": "java",
        ".cs": "c_sharp",
        ".csx": "c_sharp",
        ".html": "html",
        ".htm": "html",
        ".css": "css",
    }

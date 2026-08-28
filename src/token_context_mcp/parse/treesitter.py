from __future__ import annotations

import ast
import hashlib
import importlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace

from tree_sitter import Language, Parser, Query, QueryCursor

from token_context_mcp.models import SymbolRecord


class ParseError(RuntimeError):
    """The configured Tree-sitter adapter could not parse a supported file."""


@dataclass(frozen=True)
class ParseResult:
    language: str
    symbols: list[SymbolRecord]
    imports: list[str]
    warnings: list[str]


_NODE_KINDS: dict[str, dict[str, str]] = {
    "python": {
        "function_definition": "function",
        "class_definition": "class",
    },
    "javascript": {
        "function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "generator_function_declaration": "function",
    },
    "typescript": {
        "function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "abstract_method_signature": "method",
        "interface_declaration": "interface",
        "type_alias_declaration": "type",
        "enum_declaration": "enum",
    },
    "tsx": {
        "function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "interface_declaration": "interface",
        "type_alias_declaration": "type",
        "enum_declaration": "enum",
    },
}


def parse_source(path: str, raw: bytes, language_name: str) -> ParseResult:
    language = _load_language(language_name)
    parser = _new_parser(language)
    tree = parser.parse(raw)
    if tree.root_node is None:
        raise ParseError("Tree-sitter returned no root node")
    line_offsets = _line_offsets(raw)
    symbols = list(_walk_symbols(tree.root_node, raw, path, language_name, [], line_offsets))
    symbols = _add_module_entry_roles(tree.root_node, raw, symbols)
    imports, import_warnings = _extract_imports(tree.root_node, raw, path, language_name, language)
    warnings: list[str] = list(import_warnings)
    if tree.root_node.has_error:
        warnings.append("parser_error_node_present")
    if not symbols:
        warnings.append("parsed_file_has_zero_symbols")
    return ParseResult(language=language_name, symbols=symbols, imports=imports, warnings=warnings)


def _load_language(language_name: str) -> Language:
    module_name, accessor = {
        "python": ("tree_sitter_python", "language"),
        "javascript": ("tree_sitter_javascript", "language"),
        "typescript": ("tree_sitter_typescript", "language_typescript"),
        "tsx": ("tree_sitter_typescript", "language_tsx"),
    }.get(language_name, ("", ""))
    if not module_name:
        raise ParseError(f"unsupported language: {language_name}")
    try:
        module = importlib.import_module(module_name)
        value = getattr(module, accessor)()
    except (AttributeError, ImportError, TypeError) as error:
        raise ParseError(f"unable to load grammar for {language_name}") from error
    return value if isinstance(value, Language) else Language(value)


def _new_parser(language: Language) -> Parser:
    parser = Parser()
    try:
        parser.language = language
        return parser
    except (AttributeError, TypeError):
        return Parser(language)


def _walk_symbols(
    node: object,
    raw: bytes,
    path: str,
    language_name: str,
    parents: list[str],
    line_offsets: list[int],
) -> Iterable[SymbolRecord]:
    node_kind = node.type
    mapping = _NODE_KINDS[language_name]
    next_parents = parents
    if node_kind in mapping:
        name = _node_name(node, raw) or _anonymous_export_name(node, raw, path) or f"anonymous_{node.start_point[0] + 1}"
        yield _symbol_record(
            node,
            raw,
            path,
            language_name,
            parents,
            name,
            mapping[node_kind],
        )
        if mapping[node_kind] in {"class", "interface"}:
            next_parents = [*parents, name]
    elif language_name in {"javascript", "typescript", "tsx"} and node_kind == "variable_declarator":
        value = _field(node, "value")
        name = _declarator_name(node, raw)
        if name and value is not None and value.type in {"arrow_function", "function_expression"}:
            yield _symbol_record(value, raw, path, language_name, parents, name, "function")
    elif language_name in {"javascript", "typescript", "tsx"} and node_kind == "export_statement":
        declaration = _field(node, "declaration") or _field(node, "value")
        if declaration is not None and declaration.type in {"arrow_function", "function_expression"}:
            name = _file_stem(path)
            yield _symbol_record(declaration, raw, path, language_name, parents, name, "function")
    for child in node.named_children:
        yield from _walk_symbols(child, raw, path, language_name, next_parents, line_offsets)


def _symbol_record(
    node: object,
    raw: bytes,
    path: str,
    language_name: str,
    parents: list[str],
    name: str,
    kind: str,
) -> SymbolRecord:
    qualified_name = ".".join([*parents, name])
    start_byte = int(node.start_byte)
    end_byte = int(node.end_byte)
    body = _field(node, "body")
    body_start = int(body.start_byte) if body else None
    body_end = int(body.end_byte) if body else None
    signature_end = body_start if body_start is not None else end_byte
    signature = _signature(raw[start_byte:signature_end])
    start_line = int(node.start_point[0]) + 1
    end_line = int(node.end_point[0]) + 1
    digest = hashlib.sha256(f"{language_name}:{path}:{qualified_name}:{start_byte}".encode()).hexdigest()[:16]
    symbol_id = f"{language_name}:{path}:{qualified_name}:{digest}"
    roles: list[str] = []
    role_evidence: dict[str, str] = {}
    if language_name == "python" and node.type == "class_definition" and _has_protocol_base(node, raw):
        roles.append("protocol_definition")
        role_evidence["protocol_definition"] = "base: Protocol"
    return SymbolRecord(
        symbol_id=symbol_id,
        path=path,
        name=name,
        qualified_name=qualified_name,
        kind=kind,
        signature=signature,
        start_line=start_line,
        end_line=end_line,
        start_byte=start_byte,
        end_byte=end_byte,
        body_start_byte=body_start,
        body_end_byte=body_end,
        is_private=name.startswith("_"),
        roles=roles,
        role_evidence=role_evidence,
    )


def _field(node: object, field_name: str) -> object | None:
    try:
        return node.child_by_field_name(field_name)
    except (AttributeError, TypeError):
        return None


def _node_name(node: object, raw: bytes) -> str | None:
    for field in ("name", "property"):
        child = _field(node, field)
        if child is not None:
            value = raw[int(child.start_byte) : int(child.end_byte)].decode(
                "utf-8", errors="replace"
            )
            if value:
                return value.strip()
    for child in node.named_children:
        if getattr(child, "type", "") in {"identifier", "type_identifier", "property_identifier"}:
            return raw[int(child.start_byte) : int(child.end_byte)].decode(
                "utf-8", errors="replace"
            ).strip()
    return None


def _declarator_name(node: object, raw: bytes) -> str | None:
    name_node = _field(node, "name")
    if name_node is None or getattr(name_node, "type", "") not in {"identifier", "type_identifier", "property_identifier"}:
        return None
    return _node_text(name_node, raw)


def _anonymous_export_name(node: object, raw: bytes, path: str) -> str | None:
    parent = getattr(node, "parent", None)
    if parent is None or getattr(parent, "type", "") != "export_statement":
        return None
    declaration = _field(parent, "declaration")
    if declaration is None or int(declaration.start_byte) != int(node.start_byte):
        return None
    prefix = raw[int(parent.start_byte) : int(declaration.start_byte)].decode("utf-8", errors="replace")
    return _file_stem(path) if "default" in prefix else None


def _file_stem(path: str) -> str:
    filename = path.replace("\\", "/").rsplit("/", 1)[-1]
    return filename.rsplit(".", 1)[0] if "." in filename else filename


def _signature(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace").strip()
    text = re.sub(r"\s+", " ", text)
    text = text.rstrip("{:")
    return text[:500]


def _has_protocol_base(node: object, raw: bytes) -> bool:
    superclasses = _field(node, "superclasses")
    if superclasses is None:
        return False
    return bool(re.search(r"\bProtocol\b", raw[int(superclasses.start_byte) : int(superclasses.end_byte)].decode("utf-8", errors="replace")))


def _add_module_entry_roles(node: object, raw: bytes, symbols: list[SymbolRecord]) -> list[SymbolRecord]:
    role_targets = _module_entry_targets(node, raw)
    if not role_targets:
        return symbols
    updated: list[SymbolRecord] = []
    for symbol in symbols:
        target_lines = role_targets.get(symbol.name, [])
        if target_lines and "." not in symbol.qualified_name:
            roles = list(symbol.roles)
            evidence = dict(symbol.role_evidence)
            if "module_entry_point" not in roles:
                roles.append("module_entry_point")
            evidence["module_entry_point"] = f"if __name__ == __main__ at line {target_lines[0]}"
            updated.append(replace(symbol, roles=roles, role_evidence=evidence))
        else:
            updated.append(symbol)
    return updated


def _module_entry_targets(node: object, raw: bytes) -> dict[str, list[int]]:
    targets: dict[str, list[int]] = {}

    def visit(current: object) -> None:
        if getattr(current, "type", "") == "if_statement":
            condition = _field(current, "condition")
            condition_text = ""
            if condition is not None:
                condition_text = raw[int(condition.start_byte) : int(condition.end_byte)].decode(
                    "utf-8", errors="replace"
                )
            if "__name__" in condition_text and "__main__" in condition_text:
                for descendant in _descendants(current):
                    if getattr(descendant, "type", "") != "call":
                        continue
                    function = _field(descendant, "function")
                    if function is None or getattr(function, "type", "") != "identifier":
                        continue
                    name = raw[int(function.start_byte) : int(function.end_byte)].decode(
                        "utf-8", errors="replace"
                    )
                    if name:
                        targets.setdefault(name, []).append(int(current.start_point[0]) + 1)
        for child in getattr(current, "named_children", []):
            visit(child)

    visit(node)
    return targets


def _descendants(node: object) -> Iterable[object]:
    yield node
    for child in getattr(node, "named_children", []):
        yield from _descendants(child)


def _line_offsets(raw: bytes) -> list[int]:
    offsets = [0]
    for index, value in enumerate(raw):
        if value == 10:
            offsets.append(index + 1)
    return offsets


_IMPORT_QUERY = {
    "python": "(import_statement) @import (import_from_statement) @import",
    "javascript": "(import_statement) @import (export_statement) @export",
    "typescript": "(import_statement) @import (export_statement) @export",
    "tsx": "(import_statement) @import (export_statement) @export",
}


def _extract_imports(
    root: object,
    raw: bytes,
    path: str,
    language_name: str,
    language: Language,
) -> tuple[list[str], list[str]]:
    query = Query(language, _IMPORT_QUERY[language_name])
    captures = QueryCursor(query).captures(root)
    imports: list[str] = []
    for node in captures.get("import", []):
        if language_name == "python":
            if node.type == "import_from_statement":
                module = _field(node, "module_name")
                if module is not None:
                    imports.append(_normalize_python_import(_node_text(module, raw), path))
            else:
                for child in node.named_children:
                    module = _field(child, "name") if child.type == "aliased_import" else child
                    if module is not None:
                        imports.append(_node_text(module, raw))
        else:
            source = _field(node, "source")
            value = _string_literal_value(source, raw) if source is not None else None
            if value:
                imports.append(value)
    for node in captures.get("export", []):
        source = _field(node, "source")
        value = _string_literal_value(source, raw) if source is not None else None
        if value:
            imports.append(value)

    dynamic_detected = False
    for node in _descendants(root):
        if node.type not in {"call", "call_expression"}:
            continue
        function = _field(node, "function")
        function_name = _node_text(function, raw) if function is not None else ""
        arguments = _field(node, "arguments")
        first_argument = next(iter(getattr(arguments, "named_children", [])), None) if arguments else None
        if language_name == "python" and function_name in {"__import__", "importlib.import_module"}:
            dynamic_detected = True
        elif language_name != "python" and function_name == "import":
            dynamic_detected = True
        elif language_name != "python" and function_name == "require":
            value = _string_literal_value(first_argument, raw) if first_argument is not None else None
            if value:
                imports.append(value)
            else:
                dynamic_detected = True
    warnings = ["dynamic_import_detected"] if dynamic_detected else []
    return sorted({item for item in imports if item}), warnings


def _normalize_python_import(module: str, path: str) -> str:
    if not module.startswith("."):
        return module
    level = len(module) - len(module.lstrip("."))
    remainder = module[level:]
    parts = [item for item in path.replace("\\", "/").split("/")[:-1] if item]
    if level > 1:
        parts = parts[: max(0, len(parts) - level + 1)]
    return ".".join([*parts, *([remainder] if remainder else [])])


def _node_text(node: object, raw: bytes) -> str:
    return raw[int(node.start_byte) : int(node.end_byte)].decode("utf-8", errors="replace").strip()


def _string_literal_value(node: object | None, raw: bytes) -> str | None:
    if node is None:
        return None
    value = _node_text(node, raw)
    if len(value) < 2 or value[0] not in {"'", '"'} or value[-1] != value[0]:
        return None
    try:
        result = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return value[1:-1]
    return result if isinstance(result, str) else None

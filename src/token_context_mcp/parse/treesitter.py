from __future__ import annotations

import hashlib
import importlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace

from tree_sitter import Language, Parser

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
    text = raw.decode("utf-8", errors="replace")
    line_offsets = _line_offsets(raw)
    symbols = list(_walk_symbols(tree.root_node, raw, path, language_name, [], line_offsets))
    symbols = _add_module_entry_roles(tree.root_node, raw, symbols)
    imports = _extract_imports(text, language_name)
    warnings: list[str] = []
    if tree.root_node.has_error:
        warnings.append("parser_error_node_present")
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
        name = _node_name(node, raw) or f"anonymous_{node.start_point[0] + 1}"
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
        if language_name == "python" and node_kind == "class_definition" and _has_protocol_base(node, raw):
            roles.append("protocol_definition")
            role_evidence["protocol_definition"] = "base: Protocol"
        yield SymbolRecord(
            symbol_id=symbol_id,
            path=path,
            name=name,
            qualified_name=qualified_name,
            kind=mapping[node_kind],
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
        if mapping[node_kind] in {"class", "interface"}:
            next_parents = [*parents, name]
    for child in node.named_children:
        yield from _walk_symbols(child, raw, path, language_name, next_parents, line_offsets)


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


def _extract_imports(text: str, language_name: str) -> list[str]:
    if language_name == "python":
        patterns = (
            r"(?m)^\s*import\s+([A-Za-z_][\w.]*)",
            r"(?m)^\s*from\s+([A-Za-z_][\w.]*)\s+import\s+",
        )
    else:
        patterns = (
            r"(?m)^\s*import(?:.+?from\s+)?[\"']([^\"']+)[\"']",
            r"(?m)^\s*(?:const|let|var).+?require\([\"']([^\"']+)[\"']\)",
        )
    imports: list[str] = []
    for pattern in patterns:
        imports.extend(re.findall(pattern, text))
    return sorted(set(imports))

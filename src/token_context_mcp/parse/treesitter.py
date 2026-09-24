from __future__ import annotations

import ast
import hashlib
import importlib
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field, replace

from tree_sitter import Language, Parser, Query, QueryCursor

from token_context_mcp.models import SymbolRecord

try:
    import token_context_fast_ast as _fast_ast  # type: ignore[import-not-found]
    _HAS_FAST_AST = True
except ImportError:
    _fast_ast = None
    _HAS_FAST_AST = False


class ParseError(RuntimeError):
    """The configured Tree-sitter adapter could not parse a supported file."""


@dataclass(frozen=True)
class CallRecord:
    name: str
    receiver: str | None
    line: int
    start_byte: int
    end_byte: int
    receiver_type: str | None = None
    is_tainted: bool = False


@dataclass(frozen=True)
class ParseResult:
    language: str
    symbols: list[SymbolRecord]
    imports: list[str]
    warnings: list[str]
    calls: list[CallRecord] = field(default_factory=list)
    inheritance: dict[str, list[str]] = field(default_factory=dict)


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
    "java": {
        "class_declaration": "class",
        "interface_declaration": "interface",
        "enum_declaration": "enum",
        "annotation_type_declaration": "annotation",
        "record_declaration": "class",
        "method_declaration": "method",
        "constructor_declaration": "constructor",
    },
    "c_sharp": {
        "class_declaration": "class",
        "interface_declaration": "interface",
        "struct_declaration": "struct",
        "enum_declaration": "enum",
        "record_declaration": "record",
        "method_declaration": "method",
        "constructor_declaration": "constructor",
        "property_declaration": "property",
        "local_function_statement": "function",
    },
    "html": {
        "element": "element",
        "script_element": "script",
        "style_element": "style",
    },
    "css": {
        "rule_set": "rule",
        "media_statement": "media",
        "keyframes_statement": "keyframes",
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
    calls = extract_calls(tree.root_node, raw, language_name)
    inheritance = _extract_inheritance(tree.root_node, raw, language_name)
    warnings: list[str] = list(import_warnings)
    if tree.root_node.has_error:
        warnings.append("parser_error_node_present")
    if not symbols:
        warnings.append("parsed_file_has_zero_symbols")
    return ParseResult(
        language=language_name,
        symbols=symbols,
        imports=imports,
        warnings=warnings,
        calls=calls,
        inheritance=inheritance,
    )


def _load_language(language_name: str) -> Language:
    module_name, accessor = {
        "python": ("tree_sitter_python", "language"),
        "javascript": ("tree_sitter_javascript", "language"),
        "typescript": ("tree_sitter_typescript", "language_typescript"),
        "tsx": ("tree_sitter_typescript", "language_tsx"),
        "java": ("tree_sitter_java", "language"),
        "c_sharp": ("tree_sitter_c_sharp", "language"),
        "html": ("tree_sitter_html", "language"),
        "css": ("tree_sitter_css", "language"),
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
    for field in ("name", "property", "tag_name", "selectors"):
        child = _field(node, field)
        if child is not None:
            value = raw[int(child.start_byte) : int(child.end_byte)].decode(
                "utf-8", errors="replace"
            )
            if value:
                return value.strip()
    for child in node.named_children:
        if getattr(child, "type", "") in {
            "identifier",
            "type_identifier",
            "property_identifier",
            "tag_name",
            "class_name",
            "selectors",
        }:
            return raw[int(child.start_byte) : int(child.end_byte)].decode(
                "utf-8", errors="replace"
            ).strip()
    # HTML stores the tag name inside start_tag/end_tag nodes rather than as
    # a direct field; CSS selectors can likewise be nested in a selector list.
    for descendant in _descendants(node):
        if descendant is node:
            continue
        if getattr(descendant, "type", "") in {"tag_name", "selectors"}:
            value = _node_text(descendant, raw)
            if value:
                return value
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
    "java": "(import_declaration) @import",
    "c_sharp": "(using_directive) @import",
}


def _extract_imports(
    root: object,
    raw: bytes,
    path: str,
    language_name: str,
    language: Language,
) -> tuple[list[str], list[str]]:
    if language_name in {"html", "css"}:
        return [], []
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
        elif language_name in {"java", "c_sharp"}:
            value = _normalize_declared_import(node, raw, language_name)
            if value:
                imports.append(value)
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


def _normalize_declared_import(node: object, raw: bytes, language_name: str) -> str | None:
    """Normalize Java imports and C# using directives to stable text."""
    value = _node_text(node, raw).strip().rstrip(";").strip()
    if language_name == "java":
        value = re.sub(r"^import\s+", "", value)
        return value.removeprefix("static ").strip()
    value = re.sub(r"^using\s+", "", value)
    value = re.sub(r"^global\s+", "", value)
    if "=" in value:
        value = value.split("=", 1)[1].strip()
    return value or None


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


_GENERIC_WRAPPERS = {
    "Optional", "Union", "List", "Dict", "Set", "Tuple", "Iterable", "Sequence",
    "Mapping", "Any", "None", "Callable", "Iterator", "Generator", "AsyncGenerator",
    "Coroutine", "Awaitable", "Type", "ClassVar", "Final", "Annotated",
}
_BRANCH_NODES = {
    "if_statement", "try_statement", "while_statement", "for_statement",
    "for_in_statement", "switch_statement", "match_statement", "conditional_expression",
}


def _clean_type_name(text: str) -> str:
    cleaned = text.lstrip(":").strip()
    identifiers = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", cleaned)
    for ident in identifiers:
        if ident not in _GENERIC_WRAPPERS and (ident[0].isupper() or "_" in ident):
            return ident
    return identifiers[0] if identifiers else ""


def _analyze_function_scope(
    fn_node: object,
    raw: bytes,
    language_name: str,
) -> tuple[dict[str, str], set[str]]:
    param_types: dict[str, str] = {}
    params = _field(fn_node, "parameters") or (
        _field(fn_node, "formal_parameters") if language_name == "java" else (
            _field(fn_node, "parameter_list") if language_name == "c_sharp" else None
        )
    )
    if params is not None:
        for child in getattr(params, "named_children", []):
            p_node = child
            if getattr(p_node, "type", "") == "default_parameter":
                p_node = p_node.named_children[0] if getattr(p_node, "named_children", None) else p_node
            c_type = getattr(p_node, "type", "")
            if language_name == "python" and c_type == "typed_parameter":
                n = p_node.named_children[0] if getattr(p_node, "named_children", None) else None
                t = p_node.named_children[1] if len(getattr(p_node, "named_children", [])) > 1 else None
                if n is not None and t is not None:
                    p_name = _node_text(n, raw).strip()
                    p_type = _clean_type_name(_node_text(t, raw))
                    if p_name and p_type:
                        param_types[p_name] = p_type
            elif language_name in {"javascript", "typescript", "tsx"} and c_type in {"required_parameter", "optional_parameter"}:
                n = p_node.named_children[0] if getattr(p_node, "named_children", None) else None
                t = _field(p_node, "type")
                if n is not None and t is not None:
                    p_name = _node_text(n, raw).strip()
                    p_type = _clean_type_name(_node_text(t, raw))
                    if p_name and p_type:
                        param_types[p_name] = p_type
            elif language_name in {"java", "c_sharp"} and c_type in {"formal_parameter", "parameter"}:
                t = _field(p_node, "type")
                n = _field(p_node, "name")
                if t is not None and n is not None:
                    p_name = _node_text(n, raw).strip()
                    p_type = _clean_type_name(_node_text(t, raw))
                    if p_name and p_type:
                        param_types[p_name] = p_type

    assign_counts: dict[str, int] = defaultdict(int)
    assigned_in_branch: set[str] = set()
    annotated_types: dict[str, str] = {}
    ctor_types: dict[str, str] = {}

    body = _field(fn_node, "body")
    if body is None:
        return param_types, set()

    nested_fn_types = {
        "function_definition", "class_definition", "function_declaration",
        "method_definition", "arrow_function", "function_expression",
        "method_declaration", "constructor_declaration", "local_function_statement",
    }

    def walk(node: object, in_branch: bool) -> None:
        node_type = getattr(node, "type", "")
        if node != body and node_type in nested_fn_types:
            return
        branch = in_branch or (node_type in _BRANCH_NODES)
        if language_name == "python":
            if node_type in {"assignment", "augmented_assignment"}:
                left = _field(node, "left")
                if left is not None and getattr(left, "type", "") == "identifier":
                    v = _node_text(left, raw).strip()
                    assign_counts[v] += 1
                    if branch:
                        assigned_in_branch.add(v)
                    t_node = _field(node, "type")
                    if t_node is not None:
                        t = _clean_type_name(_node_text(t_node, raw))
                        if t:
                            annotated_types[v] = t
                    right = _field(node, "right")
                    if right is not None and getattr(right, "type", "") == "call":
                        fn = _field(right, "function")
                        if fn is not None and getattr(fn, "type", "") == "identifier":
                            fn_name = _node_text(fn, raw).strip()
                            if fn_name and (fn_name[0].isupper() or "_" in fn_name):
                                ctor_types[v] = fn_name
        elif language_name in {"javascript", "typescript", "tsx"}:
            if node_type == "variable_declarator":
                n_node = _field(node, "name")
                if n_node is not None and getattr(n_node, "type", "") == "identifier":
                    v = _node_text(n_node, raw).strip()
                    assign_counts[v] += 1
                    if branch:
                        assigned_in_branch.add(v)
                    t_node = _field(node, "type")
                    if t_node is not None:
                        t = _clean_type_name(_node_text(t_node, raw))
                        if t:
                            annotated_types[v] = t
                    val_node = _field(node, "value")
                    if val_node is not None and getattr(val_node, "type", "") == "new_expression":
                        ctor = _field(val_node, "constructor")
                        if ctor is not None and getattr(ctor, "type", "") == "identifier":
                            ctor_types[v] = _node_text(ctor, raw).strip()
            elif node_type in {"assignment_expression", "augmented_assignment_expression"}:
                left = _field(node, "left")
                if left is not None and getattr(left, "type", "") == "identifier":
                    v = _node_text(left, raw).strip()
                    assign_counts[v] += 1
                    if branch:
                        assigned_in_branch.add(v)
        elif language_name in {"java", "c_sharp"}:
            if node_type == "local_variable_declaration":
                t_node = _field(node, "type")
                t_text = _clean_type_name(_node_text(t_node, raw)) if t_node else ""
                for child in getattr(node, "named_children", []):
                    if getattr(child, "type", "") == "variable_declarator":
                        n_node = _field(child, "name")
                        if n_node is not None and getattr(n_node, "type", "") == "identifier":
                            v = _node_text(n_node, raw).strip()
                            assign_counts[v] += 1
                            if branch:
                                assigned_in_branch.add(v)
                            if t_text:
                                annotated_types[v] = t_text
            elif node_type == "assignment_expression":
                left = _field(node, "left")
                if left is not None and getattr(left, "type", "") == "identifier":
                    v = _node_text(left, raw).strip()
                    assign_counts[v] += 1
                    if branch:
                        assigned_in_branch.add(v)

        for child in getattr(node, "named_children", []):
            walk(child, branch)

    walk(body, False)

    resolved_types: dict[str, str] = {}
    tainted_vars: set[str] = set()

    for p_name, p_type in param_types.items():
        if assign_counts[p_name] == 0:
            resolved_types[p_name] = p_type
        else:
            tainted_vars.add(p_name)

    for v_name in assign_counts:
        if v_name in param_types:
            continue
        if assign_counts[v_name] >= 2 or v_name in assigned_in_branch:
            tainted_vars.add(v_name)
        elif assign_counts[v_name] == 1:
            if v_name in annotated_types:
                resolved_types[v_name] = annotated_types[v_name]
            elif v_name in ctor_types:
                resolved_types[v_name] = ctor_types[v_name]

    return resolved_types, tainted_vars


def _extract_inheritance(root: object, raw: bytes, language_name: str) -> dict[str, list[str]]:
    inheritance: dict[str, list[str]] = {}

    def visit(current: object) -> None:
        c_type = getattr(current, "type", "")
        if language_name == "python" and c_type == "class_definition":
            name_node = _field(current, "name")
            if name_node is not None:
                cls_name = _node_text(name_node, raw).strip()
                bases: list[str] = []
                superclasses = _field(current, "superclasses")
                if superclasses is not None:
                    for child in getattr(superclasses, "named_children", []):
                        if getattr(child, "type", "") == "keyword_argument":
                            continue
                        base_name = _node_text(child, raw).strip()
                        if base_name:
                            bases.append(base_name)
                inheritance[cls_name] = bases
        elif language_name in {"javascript", "typescript", "tsx"} and c_type in {"class_declaration", "class"}:
            name_node = _field(current, "name")
            if name_node is not None:
                cls_name = _node_text(name_node, raw).strip()
                bases = []
                for child in getattr(current, "named_children", []):
                    if child.type == "class_heritage":
                        for h_child in getattr(child, "named_children", []):
                            if h_child.type in {"extends_clause", "implements_clause"}:
                                for expr in getattr(h_child, "named_children", []):
                                    if expr.type in {"identifier", "type_identifier"}:
                                        b = _node_text(expr, raw).strip()
                                        if b and b not in bases:
                                            bases.append(b)
                    elif child.type in {"extends_clause", "implements_clause"}:
                        for expr in getattr(child, "named_children", []):
                            if expr.type in {"identifier", "type_identifier"}:
                                b = _node_text(expr, raw).strip()
                                if b and b not in bases:
                                    bases.append(b)
                inheritance[cls_name] = bases
        elif language_name == "java" and c_type in {"class_declaration", "record_declaration", "interface_declaration"}:
            name_node = _field(current, "name")
            if name_node is not None:
                cls_name = _node_text(name_node, raw).strip()
                bases = []
                sc = _field(current, "superclass")
                if sc is not None:
                    for expr in getattr(sc, "named_children", []):
                        if expr.type == "type_identifier":
                            b = _node_text(expr, raw).strip()
                            if b and b not in bases:
                                bases.append(b)
                si = _field(current, "super_interfaces") or _field(current, "interfaces")
                if si is not None:
                    for expr in _descendants(si):
                        if getattr(expr, "type", "") == "type_identifier":
                            b = _node_text(expr, raw).strip()
                            if b and b not in bases:
                                bases.append(b)
                inheritance[cls_name] = bases
        elif language_name == "c_sharp" and c_type in {"class_declaration", "struct_declaration", "record_declaration", "interface_declaration"}:
            name_node = _field(current, "name")
            if name_node is not None:
                cls_name = _node_text(name_node, raw).strip()
                bases = []
                bl = _field(current, "base_list")
                if bl is not None:
                    for expr in getattr(bl, "named_children", []):
                        if expr.type in {"identifier", "type_identifier", "generic_name"}:
                            b = _node_text(expr, raw).strip()
                            if b and b not in bases:
                                bases.append(b)
                inheritance[cls_name] = bases

        for child in getattr(current, "named_children", []):
            visit(child)

    visit(root)
    return inheritance


def _detect_type_narrowing(
    if_node: object,
    raw: bytes,
    language_name: str,
) -> tuple[str, str] | None:
    cond = _field(if_node, "condition")
    if cond is None:
        return None
    if language_name == "python" and getattr(cond, "type", "") == "call":
        fn = _field(cond, "function")
        if fn is not None and getattr(fn, "type", "") == "identifier":
            if _node_text(fn, raw).strip() == "isinstance":
                args = _field(cond, "arguments")
                if args is not None and len(getattr(args, "named_children", [])) >= 2:
                    first = args.named_children[0]
                    second = args.named_children[1]
                    if getattr(first, "type", "") == "identifier":
                        var_name = _node_text(first, raw).strip()
                        type_name = _clean_type_name(_node_text(second, raw))
                        if var_name and type_name:
                            return var_name, type_name
    elif language_name in {"javascript", "typescript", "tsx"}:
        inner = cond
        if getattr(cond, "type", "") == "parenthesized_expression" and getattr(cond, "named_children", None):
            inner = cond.named_children[0]
        if getattr(inner, "type", "") == "binary_expression":
            op = _field(inner, "operator")
            if op is not None and _node_text(op, raw).strip() == "instanceof":
                left = _field(inner, "left")
                right = _field(inner, "right")
                if left is not None and right is not None and getattr(left, "type", "") == "identifier":
                    var_name = _node_text(left, raw).strip()
                    type_name = _clean_type_name(_node_text(right, raw))
                    if var_name and type_name:
                        return var_name, type_name
    elif language_name == "java" and getattr(cond, "type", "") in {"instanceof_expression", "parenthesized_expression"}:
        inner = cond.named_children[0] if getattr(cond, "type", "") == "parenthesized_expression" and getattr(cond, "named_children", None) else cond
        if getattr(inner, "type", "") == "instanceof_expression":
            left = _field(inner, "left") or (inner.named_children[0] if getattr(inner, "named_children", None) else None)
            right = _field(inner, "right") or (inner.named_children[-1] if getattr(inner, "named_children", None) else None)
            if left is not None and right is not None and getattr(left, "type", "") == "identifier":
                var_name = _node_text(left, raw).strip()
                type_name = _clean_type_name(_node_text(right, raw))
                if var_name and type_name:
                    return var_name, type_name
    return None


def _detect_case_narrowing(
    case_node: object,
    raw: bytes,
    language_name: str,
) -> tuple[str, str] | None:
    if language_name != "python":
        return None
    pattern = None
    for ch in getattr(case_node, "named_children", []):
        if getattr(ch, "type", "") == "case_pattern":
            pattern = ch.named_children[0] if getattr(ch, "named_children", None) else None
            break
    if pattern is None:
        return None
    if getattr(pattern, "type", "") == "as_pattern":
        cls_pat = pattern.named_children[0] if getattr(pattern, "named_children", None) else None
        alias_node = pattern.named_children[-1] if len(getattr(pattern, "named_children", [])) > 1 else None
        if cls_pat and alias_node and getattr(cls_pat, "type", "") == "class_pattern":
            cls_node = _field(cls_pat, "class") or (cls_pat.named_children[0] if getattr(cls_pat, "named_children", None) else None)
            if cls_node is not None:
                var_name = _node_text(alias_node, raw).strip()
                type_name = _clean_type_name(_node_text(cls_node, raw))
                if var_name and type_name:
                    return var_name, type_name
    return None


def extract_calls(root: object, raw: bytes, language_name: str) -> list[CallRecord]:
    calls: list[CallRecord] = []
    scope_stack: list[tuple[dict[str, str], set[str]]] = []

    fn_node_types = {
        "python": {"function_definition"},
        "javascript": {"function_declaration", "method_definition", "arrow_function", "function_expression"},
        "typescript": {"function_declaration", "method_definition", "arrow_function", "function_expression"},
        "tsx": {"function_declaration", "method_definition", "arrow_function", "function_expression"},
        "java": {"method_declaration", "constructor_declaration"},
        "c_sharp": {"method_declaration", "constructor_declaration", "local_function_statement"},
    }.get(language_name, set())

    def resolve_receiver_meta(receiver: str | None) -> tuple[str | None, bool]:
        if not receiver or receiver in {"self", "cls", "this"}:
            return None, False
        for types, tainted in reversed(scope_stack):
            if receiver in types:
                return types[receiver], False
            if receiver in tainted:
                return None, True
        return None, False

    def visit(current: object) -> None:
        c_type = getattr(current, "type", "")
        is_fn = c_type in fn_node_types
        if is_fn:
            scope_stack.append(_analyze_function_scope(current, raw, language_name))

        # Type Narrowing on if_statement (isinstance / instanceof)
        if c_type == "if_statement" and len(scope_stack) < 12:
            narrowing = _detect_type_narrowing(current, raw, language_name)
            if narrowing:
                var_name, type_name = narrowing
                cond = _field(current, "condition")
                consequence = _field(current, "consequence")
                alternative = _field(current, "alternative")
                if cond is not None:
                    visit(cond)
                if consequence is not None:
                    scope_stack.append(({var_name: type_name}, set()))
                    visit(consequence)
                    scope_stack.pop()
                if alternative is not None:
                    visit(alternative)
                return

        # Type Narrowing on match case_clause (case ClassName() as var:)
        if c_type == "case_clause" and len(scope_stack) < 12:
            case_narrowing = _detect_case_narrowing(current, raw, language_name)
            if case_narrowing:
                var_name, type_name = case_narrowing
                scope_stack.append(({var_name: type_name}, set()))
                for child in getattr(current, "named_children", []):
                    visit(child)
                scope_stack.pop()
                return

        if language_name == "python" and c_type == "call":
            func = _field(current, "function")
            if func is not None:
                if func.type == "attribute":
                    obj = _field(func, "object")
                    attr = _field(func, "attribute")
                    if attr is not None:
                        rec = _node_text(obj, raw) if obj is not None else None
                        r_type, is_t = resolve_receiver_meta(rec)
                        calls.append(
                            CallRecord(
                                name=_node_text(attr, raw),
                                receiver=rec,
                                line=int(current.start_point[0]) + 1,
                                start_byte=int(current.start_byte),
                                end_byte=int(current.end_byte),
                                receiver_type=r_type,
                                is_tainted=is_t,
                            )
                        )
                elif func.type == "identifier":
                    calls.append(
                        CallRecord(
                            name=_node_text(func, raw),
                            receiver=None,
                            line=int(current.start_point[0]) + 1,
                            start_byte=int(current.start_byte),
                            end_byte=int(current.end_byte),
                        )
                    )
        elif language_name in {"javascript", "typescript", "tsx"} and c_type == "call_expression":
            func = _field(current, "function")
            if func is not None:
                if func.type == "member_expression":
                    obj = _field(func, "object")
                    prop = _field(func, "property")
                    if prop is not None:
                        rec = _node_text(obj, raw) if obj is not None else None
                        r_type, is_t = resolve_receiver_meta(rec)
                        calls.append(
                            CallRecord(
                                name=_node_text(prop, raw),
                                receiver=rec,
                                line=int(current.start_point[0]) + 1,
                                start_byte=int(current.start_byte),
                                end_byte=int(current.end_byte),
                                receiver_type=r_type,
                                is_tainted=is_t,
                            )
                        )
                elif func.type == "identifier":
                    calls.append(
                        CallRecord(
                            name=_node_text(func, raw),
                            receiver=None,
                            line=int(current.start_point[0]) + 1,
                            start_byte=int(current.start_byte),
                            end_byte=int(current.end_byte),
                        )
                    )
        elif language_name == "java" and c_type == "method_invocation":
            obj = _field(current, "object")
            name = _field(current, "name")
            if name is not None:
                rec = _node_text(obj, raw) if obj is not None else None
                r_type, is_t = resolve_receiver_meta(rec)
                calls.append(
                    CallRecord(
                        name=_node_text(name, raw),
                        receiver=rec,
                        line=int(current.start_point[0]) + 1,
                        start_byte=int(current.start_byte),
                        end_byte=int(current.end_byte),
                        receiver_type=r_type,
                        is_tainted=is_t,
                    )
                )
        elif language_name == "c_sharp" and c_type == "invocation_expression":
            expr = _field(current, "expression") or (
                current.named_children[0] if getattr(current, "named_children", None) else None
            )
            if expr is not None:
                if expr.type == "member_access_expression":
                    expr_obj = _field(expr, "expression")
                    expr_name = _field(expr, "name")
                    if expr_name is not None:
                        rec = _node_text(expr_obj, raw) if expr_obj is not None else None
                        r_type, is_t = resolve_receiver_meta(rec)
                        calls.append(
                            CallRecord(
                                name=_node_text(expr_name, raw),
                                receiver=rec,
                                line=int(current.start_point[0]) + 1,
                                start_byte=int(current.start_byte),
                                end_byte=int(current.end_byte),
                                receiver_type=r_type,
                                is_tainted=is_t,
                            )
                        )
                elif expr.type == "identifier":
                    calls.append(
                        CallRecord(
                            name=_node_text(expr, raw),
                            receiver=None,
                            line=int(current.start_point[0]) + 1,
                            start_byte=int(current.start_byte),
                            end_byte=int(current.end_byte),
                        )
                    )
        for child in getattr(current, "named_children", []):
            visit(child)

        if is_fn:
            scope_stack.pop()

    visit(root)
    return calls

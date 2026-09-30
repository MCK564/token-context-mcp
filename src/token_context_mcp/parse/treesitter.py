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

# Version of everything a snapshot caches per file (M7 `file_parse_artifacts`): symbols, imports, calls,
# inheritance, warnings and parse status as produced by parse_source().  BUMP IT whenever the output of
# parse_source changes for the same bytes (new/changed query, new CallRecord field, new symbol kind, a
# tree-sitter grammar upgrade is detected separately through the package versions).  Snapshots written
# with another value are re-parsed once.  tests/test_parser_artifact_version.py fails when this is forgotten.
PARSER_ARTIFACT_VERSION = 5  # 5: CallRecord arg_count and E2 overload resolution (M12.3)


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
    assigned_from_fn: str | None = None
    # "attr_param" when receiver_type was inferred from a typed constructor/method
    # parameter assigned onto self/cls (M6.0); None for every other inference path
    # (annotation, constructor call, local var, etc.), which keeps the existing
    # "attr_type" scope label in lexical_edges.py.
    receiver_type_source: str | None = None
    arg_count: int | None = None


@dataclass(frozen=True)
class ParseResult:
    language: str
    symbols: list[SymbolRecord]
    imports: list[str]
    warnings: list[str]
    calls: list[CallRecord] = field(default_factory=list)
    inheritance: dict[str, list[str]] = field(default_factory=dict)
    namespaces: list[str] = field(default_factory=list)


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
    "go": {
        "function_declaration": "function",
        "method_declaration": "method",
        "type_spec": "type",
        "type_alias": "type",
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
    namespaces: list[str] = []
    if language_name == "c_sharp":
        namespaces = _extract_csharp_namespaces(tree.root_node, raw)
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
        namespaces=namespaces,
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
        "go": ("tree_sitter_go", "language"),
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


_JS_SPECIAL_IDENTIFIERS = {
    "this", "module", "exports", "prototype",
    "window", "global", "globalThis", "process",
    "console", "document",
}


def _js_fn_signature(prop_name: str, fn_node: object, raw: bytes) -> str:
    params_node = _field(fn_node, "parameters") or _field(fn_node, "parameter")
    params_text = _node_text(params_node, raw) if params_node else "()"
    if not params_text.startswith("("):
        params_text = f"({params_text})"
    ret_node = _field(fn_node, "return_type")
    if ret_node is not None:
        params_text = f"{params_text}{_node_text(ret_node, raw)}"
    return f"{prop_name}{params_text}"


def _extract_js_object_methods(
    object_node: object,
    raw: bytes,
    path: str,
    language_name: str,
    parents: list[str],
    prefix: str,
    default_kind: str = "method",
) -> Iterable[SymbolRecord]:
    for member in object_node.named_children:
        if member.type == "method_definition":
            m_name = _node_name(member, raw)
            if m_name:
                qname = f"{prefix}.{m_name}" if prefix else m_name
                yield _symbol_record(
                    member,
                    raw,
                    path,
                    language_name,
                    parents,
                    name=m_name,
                    kind=default_kind,
                    qualified_name=qname,
                )
        elif member.type == "pair":
            k = _field(member, "key")
            v = _field(member, "value")
            if k and v and v.type in {"function_expression", "arrow_function", "generator_function"}:
                m_name = _node_text(k, raw).strip("'\"`")
                if m_name:
                    body_node = _field(v, "body")
                    sig = _js_fn_signature(m_name, v, raw)
                    qname = f"{prefix}.{m_name}" if prefix else m_name
                    yield _symbol_record(
                        member,
                        raw,
                        path,
                        language_name,
                        parents,
                        name=m_name,
                        kind=default_kind,
                        qualified_name=qname,
                        signature=sig,
                        body_node=body_node,
                    )


def _extract_js_assigned_expression(
    node: object,
    raw: bytes,
    path: str,
    language_name: str,
    parents: list[str],
    enclosing_func: str | None = None,
) -> Iterable[SymbolRecord]:
    child = node.named_children[0] if node.named_children else None
    if child is None:
        return

    # Assignment: X.prototype.m = fn, X.m = fn, this.m = fn, module.exports.m = fn, exports.m = fn, etc.
    if child.type == "assignment_expression":
        left = _field(child, "left")
        right = _field(child, "right")
        if left is None or right is None:
            return

        is_fn_value = right.type in {"function_expression", "arrow_function", "generator_function"}

        if left.type == "member_expression":
            obj = _field(left, "object")
            prop = _field(left, "property")
            prop_name = _node_text(prop, raw) if prop else ""

            # Pattern 1 & 7a: X.prototype.m = fn or module.exports.m = fn
            if obj and obj.type == "member_expression":
                sub_obj = _field(obj, "object")
                sub_prop = _field(obj, "property")
                sub_prop_name = _node_text(sub_prop, raw) if sub_prop else ""
                if sub_prop_name == "prototype" and sub_obj:
                    class_name = _node_text(sub_obj, raw)
                    if is_fn_value and class_name and prop_name:
                        body_node = _field(right, "body")
                        sig = _js_fn_signature(prop_name, right, raw)
                        yield _symbol_record(
                            node,
                            raw,
                            path,
                            language_name,
                            parents,
                            name=prop_name,
                            kind="method",
                            qualified_name=f"{class_name}.{prop_name}",
                            signature=sig,
                            body_node=body_node,
                        )
                elif _node_text(sub_obj, raw) == "module" and sub_prop_name == "exports":
                    if is_fn_value and prop_name:
                        body_node = _field(right, "body")
                        sig = _js_fn_signature(prop_name, right, raw)
                        yield _symbol_record(
                            node,
                            raw,
                            path,
                            language_name,
                            parents,
                            name=prop_name,
                            kind="function",
                            qualified_name=prop_name,
                            signature=sig,
                            body_node=body_node,
                        )

            # Pattern 7b: exports.m = fn
            elif obj and obj.type == "identifier" and _node_text(obj, raw) == "exports":
                if is_fn_value and prop_name:
                    body_node = _field(right, "body")
                    sig = _js_fn_signature(prop_name, right, raw)
                    yield _symbol_record(
                        node,
                        raw,
                        path,
                        language_name,
                        parents,
                        name=prop_name,
                        kind="function",
                        qualified_name=prop_name,
                        signature=sig,
                        body_node=body_node,
                    )

            # Pattern 5: this.m = fn inside constructor
            elif obj and obj.type == "this":
                if is_fn_value and enclosing_func and prop_name:
                    body_node = _field(right, "body")
                    sig = _js_fn_signature(prop_name, right, raw)
                    yield _symbol_record(
                        node,
                        raw,
                        path,
                        language_name,
                        parents,
                        name=prop_name,
                        kind="method",
                        qualified_name=f"{enclosing_func}.{prop_name}",
                        signature=sig,
                        body_node=body_node,
                    )

            # Pattern 2: X.prototype = { m() {}, n: fn }
            elif obj and prop_name == "prototype" and right.type == "object":
                class_name = _node_text(obj, raw)
                if class_name:
                    yield from _extract_js_object_methods(
                        right, raw, path, language_name, parents, prefix=class_name, default_kind="method"
                    )

            # Pattern 7c: module.exports = { m() {}, n: fn }
            elif obj and _node_text(obj, raw) == "module" and prop_name == "exports":
                if right.type == "object":
                    yield from _extract_js_object_methods(
                        right, raw, path, language_name, parents, prefix="", default_kind="function"
                    )
                elif is_fn_value:
                    fn_name = _node_name(right, raw) or _file_stem(path)
                    body_node = _field(right, "body")
                    sig = _js_fn_signature(fn_name, right, raw)
                    yield _symbol_record(
                        node,
                        raw,
                        path,
                        language_name,
                        parents,
                        name=fn_name,
                        kind="function",
                        qualified_name=fn_name,
                        signature=sig,
                        body_node=body_node,
                    )

            # Pattern 4: X.m = fn (where X is an identifier and not special)
            elif obj and obj.type == "identifier":
                obj_name = _node_text(obj, raw)
                if is_fn_value and obj_name not in _JS_SPECIAL_IDENTIFIERS and prop_name:
                    body_node = _field(right, "body")
                    sig = _js_fn_signature(prop_name, right, raw)
                    yield _symbol_record(
                        node,
                        raw,
                        path,
                        language_name,
                        parents,
                        name=prop_name,
                        kind="method",
                        qualified_name=f"{obj_name}.{prop_name}",
                        signature=sig,
                        body_node=body_node,
                    )

    # Pattern 3: Object.defineProperty / Object.defineProperties
    elif child.type == "call_expression":
        fn = _field(child, "function")
        fn_text = _node_text(fn, raw) if fn else ""
        args_node = _field(child, "arguments")
        args = [c for c in args_node.named_children] if args_node else []

        if fn_text == "Object.defineProperty" and len(args) >= 3:
            target_obj = args[0]
            class_name = None
            kind = "method"
            if target_obj.type == "member_expression":
                sub_obj = _field(target_obj, "object")
                sub_prop = _field(target_obj, "property")
                if sub_prop and _node_text(sub_prop, raw) == "prototype" and sub_obj:
                    class_name = _node_text(sub_obj, raw)
                elif _node_text(sub_obj, raw) == "module" and sub_prop and _node_text(sub_prop, raw) == "exports":
                    kind = "function"
                else:
                    class_name = _node_text(target_obj, raw)
            elif target_obj.type == "identifier":
                tname = _node_text(target_obj, raw)
                if tname == "exports":
                    kind = "function"
                elif tname not in _JS_SPECIAL_IDENTIFIERS:
                    class_name = tname
            elif target_obj.type == "this" and enclosing_func:
                class_name = enclosing_func

            prop_name = _node_text(args[1], raw).strip("'\"`")
            desc = args[2]
            target_qname = f"{class_name}.{prop_name}" if class_name else prop_name
            if prop_name and desc.type == "object":
                for member in desc.named_children:
                    if member.type == "method_definition":
                        m_name = _node_name(member, raw)
                        if m_name in {"get", "set"}:
                            params_node = _field(member, "parameters")
                            ptext = _node_text(params_node, raw) if params_node else "()"
                            sig = f"{m_name} {prop_name}{ptext}"
                            yield _symbol_record(
                                member,
                                raw,
                                path,
                                language_name,
                                parents,
                                name=prop_name,
                                kind=kind,
                                qualified_name=target_qname,
                                signature=sig,
                            )
                    elif member.type == "pair":
                        k = _field(member, "key")
                        v = _field(member, "value")
                        m_name = _node_text(k, raw).strip("'\"`") if k else ""
                        if m_name in {"get", "set"} and v and v.type in {"function_expression", "arrow_function", "generator_function"}:
                            params_node = _field(v, "parameters") or _field(v, "parameter")
                            ptext = _node_text(params_node, raw) if params_node else "()"
                            if not ptext.startswith("("):
                                ptext = f"({ptext})"
                            sig = f"{m_name} {prop_name}{ptext}"
                            yield _symbol_record(
                                member,
                                raw,
                                path,
                                language_name,
                                parents,
                                name=prop_name,
                                kind=kind,
                                qualified_name=target_qname,
                                signature=sig,
                                body_node=_field(v, "body"),
                            )
                        elif m_name == "value" and v and v.type in {"function_expression", "arrow_function", "generator_function"}:
                            sig = _js_fn_signature(prop_name, v, raw)
                            yield _symbol_record(
                                member,
                                raw,
                                path,
                                language_name,
                                parents,
                                name=prop_name,
                                kind=kind,
                                qualified_name=target_qname,
                                signature=sig,
                                body_node=_field(v, "body"),
                            )

        elif fn_text == "Object.defineProperties" and len(args) >= 2:
            target_obj = args[0]
            class_name = None
            kind = "method"
            if target_obj.type == "member_expression":
                sub_obj = _field(target_obj, "object")
                sub_prop = _field(target_obj, "property")
                if sub_prop and _node_text(sub_prop, raw) == "prototype" and sub_obj:
                    class_name = _node_text(sub_obj, raw)
                elif _node_text(sub_obj, raw) == "module" and sub_prop and _node_text(sub_prop, raw) == "exports":
                    kind = "function"
                else:
                    class_name = _node_text(target_obj, raw)
            elif target_obj.type == "identifier":
                tname = _node_text(target_obj, raw)
                if tname == "exports":
                    kind = "function"
                elif tname not in _JS_SPECIAL_IDENTIFIERS:
                    class_name = tname
            elif target_obj.type == "this" and enclosing_func:
                class_name = enclosing_func

            desc = args[1]
            if desc.type == "object":
                for pair in desc.named_children:
                    if pair.type == "pair":
                        k = _field(pair, "key")
                        v = _field(pair, "value")
                        prop_name = _node_text(k, raw).strip("'\"`")
                        target_qname = f"{class_name}.{prop_name}" if class_name else prop_name
                        if prop_name and v and v.type == "object":
                            for member in v.named_children:
                                if member.type == "method_definition":
                                    m_name = _node_name(member, raw)
                                    if m_name in {"get", "set"}:
                                        params_node = _field(member, "parameters")
                                        ptext = _node_text(params_node, raw) if params_node else "()"
                                        sig = f"{m_name} {prop_name}{ptext}"
                                        yield _symbol_record(
                                            member,
                                            raw,
                                            path,
                                            language_name,
                                            parents,
                                            name=prop_name,
                                            kind=kind,
                                            qualified_name=target_qname,
                                            signature=sig,
                                        )
                                elif member.type == "pair":
                                    mk = _field(member, "key")
                                    mv = _field(member, "value")
                                    m_name = _node_text(mk, raw).strip("'\"`") if mk else ""
                                    if m_name in {"get", "set"} and mv and mv.type in {"function_expression", "arrow_function", "generator_function"}:
                                        params_node = _field(mv, "parameters") or _field(mv, "parameter")
                                        ptext = _node_text(params_node, raw) if params_node else "()"
                                        if not ptext.startswith("("):
                                            ptext = f"({ptext})"
                                        sig = f"{m_name} {prop_name}{ptext}"
                                        yield _symbol_record(
                                            member,
                                            raw,
                                            path,
                                            language_name,
                                            parents,
                                            name=prop_name,
                                            kind=kind,
                                            qualified_name=target_qname,
                                            signature=sig,
                                            body_node=_field(mv, "body"),
                                        )
                                    elif m_name == "value" and mv and mv.type in {"function_expression", "arrow_function", "generator_function"}:
                                        sig = _js_fn_signature(prop_name, mv, raw)
                                        yield _symbol_record(
                                            member,
                                            raw,
                                            path,
                                            language_name,
                                            parents,
                                            name=prop_name,
                                            kind=kind,
                                            qualified_name=target_qname,
                                            signature=sig,
                                            body_node=_field(mv, "body"),
                                        )


def _walk_symbols(
    node: object,
    raw: bytes,
    path: str,
    language_name: str,
    parents: list[str],
    line_offsets: list[int],
    enclosing_function: str | None = None,
) -> Iterable[SymbolRecord]:
    node_kind = node.type
    mapping = _NODE_KINDS[language_name]
    next_parents = parents
    if language_name == "go" and node_kind in mapping:
        record = _go_symbol(node, raw, path, parents)
        if record is not None:
            yield record
    elif node_kind in mapping:
        if language_name in {"javascript", "typescript", "tsx"} and node_kind == "method_definition" and getattr(node.parent, "type", "") == "object":
            # Handled by assigned method patterns or local object
            pass
        else:
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
        if name and value is not None:
            if value.type in {"arrow_function", "function_expression"}:
                yield _symbol_record(value, raw, path, language_name, parents, name, "function")
            elif not parents and not enclosing_function and value.type == "object":
                yield from _extract_js_object_methods(value, raw, path, language_name, parents, prefix=name, default_kind="method")
    elif language_name in {"javascript", "typescript", "tsx"} and node_kind == "export_statement":
        declaration = _field(node, "declaration") or _field(node, "value")
        if declaration is not None and declaration.type in {"arrow_function", "function_expression"}:
            name = _file_stem(path)
            yield _symbol_record(declaration, raw, path, language_name, parents, name, "function")
    elif language_name in {"javascript", "typescript", "tsx"} and node_kind == "expression_statement":
        yield from _extract_js_assigned_expression(node, raw, path, language_name, parents, enclosing_function)

    next_enclosing_function = enclosing_function
    if node_kind == "function_declaration":
        fn_name = _node_name(node, raw)
        next_enclosing_function = fn_name or enclosing_function
    elif node_kind == "variable_declarator":
        val = _field(node, "value")
        if val is not None and val.type in {"arrow_function", "function_expression"}:
            decl_name = _declarator_name(node, raw)
            next_enclosing_function = decl_name or enclosing_function
    elif node_kind in {"class_declaration", "interface_declaration", "method_definition"}:
        next_enclosing_function = None

    for child in node.named_children:
        yield from _walk_symbols(child, raw, path, language_name, next_parents, line_offsets, next_enclosing_function)


def _go_receiver_type(node: object, raw: bytes) -> str | None:
    """``(s *Server)`` / ``(s Server[T])`` -> ``Server`` (the type a method belongs to)."""
    receiver = _field(node, "receiver")
    if receiver is None:
        return None
    for parameter in receiver.named_children:
        type_node = _field(parameter, "type")
        if type_node is None:
            continue
        text = _node_text(type_node, raw).lstrip("*").strip()
        text = re.split(r"[\[\s]", text, maxsplit=1)[0]
        return text or None
    return None


def _go_symbol(node: object, raw: bytes, path: str, parents: list[str]) -> SymbolRecord | None:
    """Go declarations (M10.2): functions, methods (qualified as ``Type.Method``), struct / interface / other types."""
    name_node = _field(node, "name")
    if name_node is None:
        return None
    name = _node_text(name_node, raw)
    if not name or name == "_":
        return None
    kind = "type"
    method_parents = parents
    if node.type == "function_declaration":
        kind = "function"
    elif node.type == "method_declaration":
        kind = "method"
        receiver_type = _go_receiver_type(node, raw)
        method_parents = [*parents, receiver_type] if receiver_type else parents
    record = _symbol_record(node, raw, path, "go", method_parents, name, kind)
    if kind == "type":
        record = replace(record, signature=_signature(b"type " + raw[int(node.start_byte) : int(node.end_byte)]))
    if node.type == "type_spec":
        type_node = _field(node, "type")
        type_kind = {"struct_type": "struct", "interface_type": "interface"}.get(getattr(type_node, "type", ""))
        if type_node is not None and type_kind is not None:
            brace = raw.find(b"{", int(type_node.start_byte), int(type_node.end_byte))
            if brace >= 0:
                record = replace(
                    record,
                    kind=type_kind,
                    signature=_signature(b"type " + raw[int(node.start_byte) : brace]),
                    body_start_byte=brace,
                    body_end_byte=int(type_node.end_byte),
                )
            else:
                record = replace(record, kind=type_kind)
    return record


def _symbol_record(
    node: object,
    raw: bytes,
    path: str,
    language_name: str,
    parents: list[str],
    name: str,
    kind: str,
    qualified_name: str | None = None,
    signature: str | None = None,
    body_node: object | None = None,
) -> SymbolRecord:
    if qualified_name is None:
        qualified_name = ".".join([*parents, name])
    start_byte = int(node.start_byte)
    end_byte = int(node.end_byte)
    body = body_node if body_node is not None else _field(node, "body")
    body_start = int(body.start_byte) if body else None
    body_end = int(body.end_byte) if body else None
    if signature is None:
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
        is_private=(not name[:1].isupper()) if language_name == "go" else name.startswith("_"),
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
    "go": "(import_spec) @import",
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
        elif language_name == "go":
            path_node = _field(node, "path")
            value = _node_text(path_node, raw).strip('"`') if path_node is not None else ""
            if value:
                imports.append(value)
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
        if language_name == "go":
            break  # Go has no dynamic import or require(); a function named "require" is an ordinary call
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


def _extract_csharp_namespaces(root: object, raw: bytes) -> list[str]:
    """Extract C# block-scoped and file-scoped namespace declarations (E3)."""
    namespaces: list[str] = []

    def visit(node: object, prefix: str = "") -> None:
        c_type = getattr(node, "type", "")
        if c_type in {"namespace_declaration", "file_scoped_namespace_declaration"}:
            name_node = _field(node, "name")
            if name_node is not None:
                ns_name = _node_text(name_node, raw)
                full_ns = f"{prefix}.{ns_name}" if prefix else ns_name
                namespaces.append(full_ns)
                for child in getattr(node, "named_children", []):
                    visit(child, full_ns)
                return
        for child in getattr(node, "named_children", []):
            visit(child, prefix)

    visit(root)
    return namespaces


_CONTAINER_TYPES = {
    "dict", "Dict", "defaultdict", "Mapping", "MutableMapping",
    "list", "List", "Sequence", "MutableSequence", "Iterable", "Iterator",
    "set", "Set", "MutableSet", "frozenset", "FrozenSet",
    "tuple", "Tuple",
}

_BUILTIN_RECEIVERS = {
    "os", "sys", "re", "json", "time", "math", "uuid", "shutil", "pathlib", "logging",
    "logger", "log", "tomllib", "hashlib", "sqlite3", "pathspec", "pytest", "io",
    "dict", "list", "set", "tuple", "str", "bytes", "bytearray", "int", "float", "bool",
    "raw", "os.environ", "payload", "manifest", "usage", "agent", "topic",
    "i", "d", "data", "resp", "response", "params", "args", "kwargs", "settings",
    "None", "Any", "void",
}

_UNWRAP_WRAPPERS = {
    "Optional", "Union", "Final", "ClassVar", "Annotated", "Type",
}


_BRANCH_NODES = {
    "if_statement", "try_statement", "while_statement", "for_statement",
    "for_in_statement", "switch_statement", "match_statement", "conditional_expression",
}


def _clean_type_name(text: str) -> str:
    cleaned = text.lstrip(":").strip()
    if not cleaned:
        return ""

    # Handle X | None or None | X
    if "|" in cleaned:
        parts = [p.strip() for p in cleaned.split("|") if p.strip() and p.strip() != "None"]
        if len(parts) == 1:
            cleaned = parts[0]
        else:
            return ""

    # Check container types before brackets
    bracket_idx = cleaned.find("[")
    if bracket_idx != -1:
        outer = cleaned[:bracket_idx].strip()
        outer_short = outer.rsplit(".", 1)[-1]
        if outer_short in _CONTAINER_TYPES:
            # The variable itself is a container!
            if outer_short in {"dict", "Dict", "defaultdict", "Mapping", "MutableMapping"}:
                return "dict"
            if outer_short in {"list", "List", "Sequence", "MutableSequence", "Iterable", "Iterator"}:
                return "list"
            if outer_short in {"set", "Set", "MutableSet", "frozenset", "FrozenSet"}:
                return "set"
            if outer_short in {"tuple", "Tuple"}:
                return "tuple"
        if outer_short in _UNWRAP_WRAPPERS:
            # Unwrap first type argument: Optional[T] -> T
            inner = cleaned[bracket_idx + 1 :].rstrip("]").strip()
            first_arg = inner.split(",")[0].strip()
            return _clean_type_name(first_arg)

    # Standard identifier extraction
    identifiers = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", cleaned)
    for ident in identifiers:
        if ident not in _UNWRAP_WRAPPERS and ident not in {"Any", "None"} and (ident[0].isupper() or "_" in ident):
            return ident
    return identifiers[0] if identifiers else ""



def _analyze_function_scope(
    fn_node: object,
    raw: bytes,
    language_name: str,
    fn_return_types: dict[str, str] | None = None,
) -> tuple[dict[str, str], set[str], dict[str, str]]:
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
    fn_call_assigns: dict[str, str] = {}

    body = _field(fn_node, "body")
    if body is None:
        return param_types, set(), {}

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
                        if fn is not None:
                            if getattr(fn, "type", "") == "identifier":
                                fn_name = _node_text(fn, raw).strip()
                                fn_call_assigns[v] = fn_name
                                if fn_name and (fn_name[0].isupper() or "_" in fn_name):
                                    ctor_types[v] = fn_name
                                elif fn_return_types and fn_name in fn_return_types:
                                    ctor_types[v] = fn_return_types[fn_name]
                            elif getattr(fn, "type", "") == "attribute":
                                fn_attr = _field(fn, "attribute")
                                if fn_attr is not None:
                                    a_name = _node_text(fn_attr, raw).strip()
                                    fn_call_assigns[v] = a_name
                                    if fn_return_types and a_name in fn_return_types:
                                        ctor_types[v] = fn_return_types[a_name]
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
                    if val_node is not None:
                        if getattr(val_node, "type", "") == "new_expression":
                            ctor = _field(val_node, "constructor")
                            if ctor is not None and getattr(ctor, "type", "") == "identifier":
                                ctor_types[v] = _node_text(ctor, raw).strip()
                        elif getattr(val_node, "type", "") == "call_expression":
                            fn = _field(val_node, "function")
                            if fn is not None and getattr(fn, "type", "") == "identifier":
                                fn_name = _node_text(fn, raw).strip()
                                fn_call_assigns[v] = fn_name
                                if fn_return_types and fn_name in fn_return_types:
                                    ctor_types[v] = fn_return_types[fn_name]
            elif node_type in {"assignment_expression", "augmented_assignment_expression"}:
                left = _field(node, "left")
                if left is not None and getattr(left, "type", "") == "identifier":
                    v = _node_text(left, raw).strip()
                    assign_counts[v] += 1
                    if branch:
                        assigned_in_branch.add(v)
        elif language_name in {"java", "c_sharp"}:
            if node_type in {"local_variable_declaration", "variable_declaration"}:
                t_node = _field(node, "type")
                t_raw = _node_text(t_node, raw) if t_node else ""
                t_text = _clean_type_name(t_raw) if t_raw and t_raw != "var" else ""
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
                            named_ch = getattr(child, "named_children", [])
                            val_node = named_ch[1] if len(named_ch) > 1 else None
                            if val_node is not None:
                                if val_node.type == "object_creation_expression":
                                    type_child = _field(val_node, "type")
                                    if type_child is not None:
                                        c_type = _clean_type_name(_node_text(type_child, raw))
                                        if c_type:
                                            ctor_types[v] = c_type
                                elif val_node.type == "cast_expression":
                                    type_child = _field(val_node, "type")
                                    if type_child is not None:
                                        c_type = _clean_type_name(_node_text(type_child, raw))
                                        if c_type:
                                            ctor_types[v] = c_type
                                elif val_node.type == "invocation_expression":
                                    expr = _field(val_node, "expression")
                                    if expr is not None and expr.type == "identifier":
                                        fn_name = _node_text(expr, raw).strip()
                                        fn_call_assigns[v] = fn_name
                                        if fn_return_types and fn_name in fn_return_types:
                                            ctor_types[v] = fn_return_types[fn_name]
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

    return resolved_types, tainted_vars, fn_call_assigns



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
                bl = _field(current, "base_list") or next(
                    (c for c in getattr(current, "children", []) if getattr(c, "type", "") == "base_list"),
                    None,
                )
                if bl is not None:
                    for expr in getattr(bl, "named_children", []):
                        if expr.type in {"identifier", "type_identifier", "generic_name", "qualified_name"}:
                            b = _node_text(expr, raw).strip()
                            clean_b = re.split(r"[<\[]", b)[0].strip()
                            if "." in clean_b:
                                clean_b = clean_b.rsplit(".", 1)[-1].strip()
                            if clean_b and clean_b not in bases:
                                bases.append(clean_b)
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


def _extract_file_return_types(root: object, raw: bytes, language_name: str) -> dict[str, str]:
    return_types: dict[str, str] = {}
    fn_node_kinds = {
        "python": {"function_definition"},
        "javascript": {"function_declaration", "method_definition"},
        "typescript": {"function_declaration", "method_definition"},
        "tsx": {"function_declaration", "method_definition"},
        "java": {"method_declaration"},
        "c_sharp": {"method_declaration"},
    }.get(language_name, set())

    def visit(current: object) -> None:
        c_type = getattr(current, "type", "")
        if c_type in fn_node_kinds:
            name_node = _field(current, "name")
            if name_node is not None:
                fn_name = _node_text(name_node, raw).strip()
                t_node = _field(current, "return_type") or _field(current, "type")
                if t_node is not None:
                    t_str = _clean_type_name(_node_text(t_node, raw))
                    if t_str and t_str not in _BUILTIN_RECEIVERS and t_str not in {"None", "Any", "void", "bool", "int", "str", "float"}:
                        return_types[fn_name] = t_str
        for child in getattr(current, "named_children", []):
            visit(child)

    visit(root)
    return return_types


def _python_param_types(fn_node: object, raw: bytes) -> dict[str, str]:
    """Map a Python function's own parameter names to their cleaned type annotations.

    Handles both ``typed_parameter`` (``x: T``, whose Tree-sitter node exposes no
    ``name``/``type`` fields, only positional named children) and
    ``typed_default_parameter`` (``x: T = default``, which does expose ``name``/``type``
    fields). Untyped, *args/**kwargs, and positional-only markers are skipped.
    """
    param_types: dict[str, str] = {}
    params = _field(fn_node, "parameters")
    if params is None:
        return param_types
    for p_node in getattr(params, "named_children", []):
        c_type = getattr(p_node, "type", "")
        if c_type == "typed_parameter":
            children = getattr(p_node, "named_children", [])
            n = children[0] if children else None
            t = children[1] if len(children) > 1 else None
        elif c_type == "typed_default_parameter":
            n = _field(p_node, "name")
            t = _field(p_node, "type")
        else:
            continue
        if n is not None and t is not None:
            p_name = _node_text(n, raw).strip()
            p_type = _clean_type_name(_node_text(t, raw))
            if p_name and p_type:
                param_types[p_name] = p_type
    return param_types


def _extract_class_attributes(
    root: object,
    raw: bytes,
    language_name: str,
    fn_return_types: dict[str, str],
) -> tuple[dict[tuple[str, str], str], set[tuple[str, str]], dict[tuple[str, str], str]]:
    # Each entry is a list of (inferred_type, source) pairs, where source is
    # "attr_param" (M6.0: self.x = <typed parameter>) or "attr_type" (pre-existing:
    # self.x: T = ... / self.x = Cls(...) / this.x = new Cls() / field declarations).
    class_attr_assigned: dict[str, dict[str, list[tuple[str, str]]]] = defaultdict(lambda: defaultdict(list))

    def visit(
        current: object,
        current_class: str | None = None,
        param_type_map: dict[str, str] | None = None,
    ) -> None:
        param_type_map = param_type_map or {}
        c_type = getattr(current, "type", "")
        next_class = current_class
        if language_name == "python" and c_type == "function_definition":
            # Each method gets its own fresh parameter-type map: a parameter named
            # the same thing in a different method has no bearing here.
            param_type_map = _python_param_types(current, raw)
        if language_name == "python" and c_type == "class_definition":
            name_node = _field(current, "name")
            if name_node is not None:
                next_class = _node_text(name_node, raw).strip()
        elif language_name in {"javascript", "typescript", "tsx"} and c_type in {"class_declaration", "class"}:
            name_node = _field(current, "name")
            if name_node is not None:
                next_class = _node_text(name_node, raw).strip()
        elif language_name == "java" and c_type in {"class_declaration", "record_declaration"}:
            name_node = _field(current, "name")
            if name_node is not None:
                next_class = _node_text(name_node, raw).strip()
        elif language_name == "c_sharp" and c_type in {"class_declaration", "struct_declaration", "record_declaration"}:
            name_node = _field(current, "name")
            if name_node is not None:
                next_class = _node_text(name_node, raw).strip()

        if next_class:
            if language_name == "python":
                if c_type in {"assignment", "augmented_assignment"}:
                    left = _field(current, "left")
                    if left is not None and getattr(left, "type", "") == "attribute":
                        obj = _field(left, "object")
                        attr = _field(left, "attribute")
                        if obj is not None and attr is not None:
                            obj_text = _node_text(obj, raw).strip()
                            attr_text = _node_text(attr, raw).strip()
                            if obj_text in {"self", "cls"}:
                                t_node = _field(current, "type")
                                inferred_t = None
                                inferred_source = "attr_type"
                                if t_node is not None:
                                    inferred_t = _clean_type_name(_node_text(t_node, raw))
                                else:
                                    right = _field(current, "right")
                                    if right is not None and getattr(right, "type", "") == "call":
                                        fn = _field(right, "function")
                                        if fn is not None:
                                            if getattr(fn, "type", "") == "identifier":
                                                fn_name = _node_text(fn, raw).strip()
                                                if fn_name and (fn_name[0].isupper() or "_" in fn_name):
                                                    inferred_t = fn_name
                                                elif fn_name in fn_return_types:
                                                    inferred_t = fn_return_types[fn_name]
                                            elif getattr(fn, "type", "") == "attribute":
                                                fn_attr = _field(fn, "attribute")
                                                if fn_attr is not None:
                                                    a_name = _node_text(fn_attr, raw).strip()
                                                    if a_name in fn_return_types:
                                                        inferred_t = fn_return_types[a_name]
                                    elif right is not None and getattr(right, "type", "") == "identifier":
                                        # M6.0: self.x = <name>, where <name> is a typed parameter
                                        # of the enclosing method (most common DI pattern in
                                        # __init__). Tagged "attr_param" so its confidence can be
                                        # calibrated independently of the other attr_type sources.
                                        ident_name = _node_text(right, raw).strip()
                                        if ident_name in param_type_map:
                                            inferred_t = param_type_map[ident_name]
                                            inferred_source = "attr_param"
                                if inferred_t and inferred_t not in _BUILTIN_RECEIVERS and inferred_t not in {"None", "Any"}:
                                    class_attr_assigned[next_class][attr_text].append((inferred_t, inferred_source))
            elif language_name in {"javascript", "typescript", "tsx"}:
                if c_type in {"public_field_definition", "field_definition", "property_definition"}:
                    name_node = _field(current, "property") or _field(current, "name")
                    t_node = _field(current, "type")
                    if name_node is not None and t_node is not None:
                        attr_text = _node_text(name_node, raw).strip()
                        inferred_t = _clean_type_name(_node_text(t_node, raw))
                        if inferred_t and inferred_t not in _BUILTIN_RECEIVERS:
                            class_attr_assigned[next_class][attr_text].append((inferred_t, "attr_type"))
                elif c_type in {"assignment_expression", "augmented_assignment_expression"}:
                    left = _field(current, "left")
                    if left is not None and getattr(left, "type", "") == "member_expression":
                        obj = _field(left, "object")
                        prop = _field(left, "property")
                        if obj is not None and prop is not None and _node_text(obj, raw).strip() == "this":
                            attr_text = _node_text(prop, raw).strip()
                            right = _field(current, "right")
                            inferred_t = None
                            if right is not None and getattr(right, "type", "") == "new_expression":
                                ctor = _field(right, "constructor")
                                if ctor is not None and getattr(ctor, "type", "") == "identifier":
                                    inferred_t = _node_text(ctor, raw).strip()
                            if inferred_t:
                                class_attr_assigned[next_class][attr_text].append((inferred_t, "attr_type"))
            elif language_name in {"java", "c_sharp"}:
                if c_type == "field_declaration":
                    t_node = _field(current, "type")
                    t_text = _clean_type_name(_node_text(t_node, raw)) if t_node else ""
                    if t_text and t_text not in _BUILTIN_RECEIVERS:
                        for child in getattr(current, "named_children", []):
                            if getattr(child, "type", "") in {"variable_declarator", "variable_declaration"}:
                                n_node = _field(child, "name") or (child.named_children[0] if getattr(child, "named_children", None) else None)
                                if n_node is not None:
                                    attr_text = _node_text(n_node, raw).strip()
                                    class_attr_assigned[next_class][attr_text].append((t_text, "attr_type"))

        for child in getattr(current, "named_children", []):
            visit(child, next_class, param_type_map)

    visit(root)

    resolved_attrs: dict[tuple[str, str], str] = {}
    resolved_attrs_source: dict[tuple[str, str], str] = {}
    tainted_attrs: set[tuple[str, str]] = set()
    for cls_name, attrs in class_attr_assigned.items():
        for attr, entries in attrs.items():
            unique_types = {t for t, _ in entries}
            if len(unique_types) == 1:
                resolved_attrs[(cls_name, attr)] = next(iter(unique_types))
                sources = {s for _, s in entries}
                if sources == {"attr_param"}:
                    resolved_attrs_source[(cls_name, attr)] = "attr_param"
            else:
                tainted_attrs.add((cls_name, attr))

    return resolved_attrs, tainted_attrs, resolved_attrs_source


def extract_calls(root: object, raw: bytes, language_name: str) -> list[CallRecord]:
    calls: list[CallRecord] = []
    scope_stack: list[tuple[dict[str, str], set[str], dict[str, str]]] = []
    class_stack: list[str] = []

    fn_return_types = _extract_file_return_types(root, raw, language_name)
    class_attr_types, class_attr_tainted, class_attr_param_source = _extract_class_attributes(
        root, raw, language_name, fn_return_types
    )

    fn_node_types = {
        "python": {"function_definition"},
        "javascript": {"function_declaration", "method_definition", "arrow_function", "function_expression"},
        "typescript": {"function_declaration", "method_definition", "arrow_function", "function_expression"},
        "tsx": {"function_declaration", "method_definition", "arrow_function", "function_expression"},
        "java": {"method_declaration", "constructor_declaration"},
        "c_sharp": {"method_declaration", "constructor_declaration", "local_function_statement"},
    }.get(language_name, set())  # Go is handled by the receiver scope below (names only, no type inference)

    cls_node_types = {
        "python": {"class_definition"},
        "javascript": {"class_declaration", "class"},
        "typescript": {"class_declaration", "class"},
        "tsx": {"class_declaration", "class"},
        "java": {"class_declaration", "record_declaration"},
        "c_sharp": {"class_declaration", "struct_declaration", "record_declaration"},
    }.get(language_name, set())

    def resolve_receiver_meta(receiver: str | None) -> tuple[str | None, bool, str | None, str | None]:
        if not receiver or receiver in {"self", "cls", "this"}:
            return None, False, None, None
        for types, tainted, fn_assigns in reversed(scope_stack):
            if receiver in types:
                return types[receiver], False, None, None
            if receiver in tainted:
                return None, True, None, None
            if receiver in fn_assigns:
                return None, False, fn_assigns[receiver], None
        if receiver and any(receiver.startswith(p) for p in ("self.", "this.", "cls.")):
            parts = receiver.split(".", 1)
            if len(parts) == 2 and "." not in parts[1] and class_stack and class_stack[-1]:
                curr_cls = class_stack[-1]
                attr_name = parts[1]
                if (curr_cls, attr_name) in class_attr_tainted:
                    return None, True, None, None
                if (curr_cls, attr_name) in class_attr_types:
                    attr_source = class_attr_param_source.get((curr_cls, attr_name))
                    return class_attr_types[(curr_cls, attr_name)], False, None, attr_source
        return None, False, None, None

    def visit(current: object) -> None:
        c_type = getattr(current, "type", "")
        is_cls = c_type in cls_node_types
        if is_cls:
            name_node = _field(current, "name")
            class_stack.append(_node_text(name_node, raw).strip() if name_node else "")

        is_fn = c_type in fn_node_types
        if is_fn:
            scope_stack.append(_analyze_function_scope(current, raw, language_name, fn_return_types))
        elif language_name == "go" and c_type == "method_declaration":
            # the receiver variable (s in ``func (s *Server) Start()``) has the receiver's type: s.helper() -> Server.helper
            is_fn = True
            receiver_types: dict[str, str] = {}
            receiver_node = _field(current, "receiver")
            receiver_type = _go_receiver_type(current, raw)
            if receiver_node is not None and receiver_type:
                for parameter in receiver_node.named_children:
                    variable = _field(parameter, "name")
                    if variable is not None:
                        receiver_types[_node_text(variable, raw)] = receiver_type
            scope_stack.append((receiver_types, set(), {}))

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
                    scope_stack.append(({var_name: type_name}, set(), {}))
                    visit(consequence)
                    scope_stack.pop()
                if alternative is not None:
                    visit(alternative)
                if is_cls:
                    class_stack.pop()
                return

        # Type Narrowing on match case_clause (case ClassName() as var:)
        if c_type == "case_clause" and len(scope_stack) < 12:
            case_narrowing = _detect_case_narrowing(current, raw, language_name)
            if case_narrowing:
                var_name, type_name = case_narrowing
                scope_stack.append(({var_name: type_name}, set(), {}))
                for child in getattr(current, "named_children", []):
                    visit(child)
                scope_stack.pop()
                if is_cls:
                    class_stack.pop()
                return

        if language_name == "python" and c_type == "call":
            args_node = _field(current, "arguments")
            call_arg_count = len(args_node.named_children) if args_node is not None else None
            func = _field(current, "function")
            if func is not None:
                if func.type == "attribute":
                    obj = _field(func, "object")
                    attr = _field(func, "attribute")
                    if attr is not None:
                        rec = _node_text(obj, raw) if obj is not None else None
                        r_type, is_t, fn_src, r_src = resolve_receiver_meta(rec)
                        calls.append(
                            CallRecord(
                                name=_node_text(attr, raw),
                                receiver=rec,
                                line=int(current.start_point[0]) + 1,
                                start_byte=int(current.start_byte),
                                end_byte=int(current.end_byte),
                                receiver_type=r_type,
                                is_tainted=is_t,
                                assigned_from_fn=fn_src,
                                receiver_type_source=r_src,
                                arg_count=call_arg_count,
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
                            arg_count=call_arg_count,
                        )
                    )
        elif language_name in {"javascript", "typescript", "tsx"} and c_type == "call_expression":
            args_node = _field(current, "arguments")
            call_arg_count = len(args_node.named_children) if args_node is not None else None
            func = _field(current, "function")
            if func is not None:
                if func.type == "member_expression":
                    obj = _field(func, "object")
                    prop = _field(func, "property")
                    if prop is not None:
                        rec = _node_text(obj, raw) if obj is not None else None
                        r_type, is_t, fn_src, r_src = resolve_receiver_meta(rec)
                        calls.append(
                            CallRecord(
                                name=_node_text(prop, raw),
                                receiver=rec,
                                line=int(current.start_point[0]) + 1,
                                start_byte=int(current.start_byte),
                                end_byte=int(current.end_byte),
                                receiver_type=r_type,
                                is_tainted=is_t,
                                assigned_from_fn=fn_src,
                                receiver_type_source=r_src,
                                arg_count=call_arg_count,
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
                            arg_count=call_arg_count,
                        )
                    )
        elif language_name == "go" and c_type == "call_expression":
            args_node = _field(current, "arguments")
            call_arg_count = len(args_node.named_children) if args_node is not None else None
            func = _field(current, "function")
            if func is not None:
                if func.type == "selector_expression":
                    operand = _field(func, "operand")
                    selected = _field(func, "field")
                    if selected is not None:
                        rec = _node_text(operand, raw) if operand is not None else None
                        r_type, is_t, fn_src, r_src = resolve_receiver_meta(rec)
                        calls.append(
                            CallRecord(
                                name=_node_text(selected, raw),
                                receiver=rec,
                                line=int(current.start_point[0]) + 1,
                                start_byte=int(current.start_byte),
                                end_byte=int(current.end_byte),
                                receiver_type=r_type,
                                is_tainted=is_t,
                                assigned_from_fn=fn_src,
                                receiver_type_source=r_src,
                                arg_count=call_arg_count,
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
                            arg_count=call_arg_count,
                        )
                    )
        elif language_name == "java" and c_type == "method_invocation":
            args_node = _field(current, "arguments")
            call_arg_count = len(args_node.named_children) if args_node is not None else None
            obj = _field(current, "object")
            name = _field(current, "name")
            if name is not None:
                rec = _node_text(obj, raw) if obj is not None else None
                r_type, is_t, fn_src, r_src = resolve_receiver_meta(rec)
                calls.append(
                    CallRecord(
                        name=_node_text(name, raw),
                        receiver=rec,
                        line=int(current.start_point[0]) + 1,
                        start_byte=int(current.start_byte),
                        end_byte=int(current.end_byte),
                        receiver_type=r_type,
                        is_tainted=is_t,
                        assigned_from_fn=fn_src,
                        receiver_type_source=r_src,
                        arg_count=call_arg_count,
                    )
                )
        elif language_name == "c_sharp" and c_type == "invocation_expression":
            args_node = _field(current, "arguments")
            call_arg_count = len(args_node.named_children) if args_node is not None else None
            expr = _field(current, "expression") or (
                current.named_children[0] if getattr(current, "named_children", None) else None
            )
            if expr is not None:
                if expr.type == "member_access_expression":
                    expr_obj = _field(expr, "expression")
                    expr_name = _field(expr, "name")
                    if expr_name is not None:
                        rec = _node_text(expr_obj, raw) if expr_obj is not None else None
                        r_type, is_t, fn_src, r_src = resolve_receiver_meta(rec)
                        calls.append(
                            CallRecord(
                                name=_node_text(expr_name, raw),
                                receiver=rec,
                                line=int(current.start_point[0]) + 1,
                                start_byte=int(current.start_byte),
                                end_byte=int(current.end_byte),
                                receiver_type=r_type,
                                is_tainted=is_t,
                                assigned_from_fn=fn_src,
                                receiver_type_source=r_src,
                                arg_count=call_arg_count,
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
                            arg_count=call_arg_count,
                        )
                    )
        for child in getattr(current, "named_children", []):
            visit(child)

        if is_fn:
            scope_stack.pop()
        if is_cls:
            class_stack.pop()

    visit(root)
    return calls


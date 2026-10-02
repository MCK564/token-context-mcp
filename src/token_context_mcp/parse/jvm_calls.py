"""Call extraction for Java and C# (M13).

Statically typed languages get their own extractor instead of the assignment-counting heuristics of the dynamic ones:

* lexical block scoping - a local's declared type never changes, so there is no "tainted" receiver any more;
* the type of ``var`` locals comes from their initialiser, lambda/foreach/catch/pattern/``out`` variables are scoped;
* every call carries the inferred *argument types* (overload resolution) and, when its receiver is an expression
  (``a.b().c()``, ``(Foo) x``, ``new Foo().bar()``), a *chain descriptor* the resolver evaluates against the
  repository's declared return types;
* Java ``new X(...)`` creates an instantiation record like C#'s ``new X(...)`` always did;
* the walk is iterative, so pathological expression chains cannot hit the interpreter's recursion limit.

Chain descriptors (``CallRecord.chain``) are ``|``-joined: a root followed by steps.

    root   T:<Type>   statically known type            S:<Name>  a name that is probably a type (static access)
           this       the enclosing class (implicit)   super     the superclass of the enclosing class
    step   m:<name>/<n>   call of method <name> with <n> arguments (``?`` when unknown)
           f:<name>       field / property access
"""
from __future__ import annotations

from typing import Any

from token_context_mcp.parse.jvm_types import split_params, type_key, type_ref

_COMMENT_TYPES = frozenset({"comment", "line_comment", "block_comment"})

_CLASS_NODES = {
    "java": frozenset(
        {"class_declaration", "record_declaration", "interface_declaration", "enum_declaration", "annotation_type_declaration"}
    ),
    "c_sharp": frozenset(
        {"class_declaration", "struct_declaration", "record_declaration", "record_struct_declaration",
         "interface_declaration", "enum_declaration"}
    ),
}
_OWNER_NODES = {
    "java": frozenset({"method_declaration", "constructor_declaration"}),
    "c_sharp": frozenset(
        {"method_declaration", "constructor_declaration", "destructor_declaration", "operator_declaration",
         "conversion_operator_declaration", "local_function_statement"}
    ),
}
_SCOPE_NODES = {
    "java": frozenset(
        {"block", "constructor_body", "for_statement", "enhanced_for_statement", "try_with_resources_statement",
         "catch_clause", "lambda_expression", "switch_block", "switch_rule", "switch_block_statement_group"}
    ),
    "c_sharp": frozenset(
        {"block", "for_statement", "foreach_statement", "using_statement", "catch_clause", "lambda_expression",
         "anonymous_method_expression", "switch_section", "switch_expression_arm", "fixed_statement"}
    ),
}
_LAMBDA_NODES = frozenset({"lambda_expression", "anonymous_method_expression"})

_JAVA_INT_LITERALS = frozenset({"decimal_integer_literal", "hex_integer_literal", "octal_integer_literal", "binary_integer_literal"})
_JAVA_FLOAT_LITERALS = frozenset({"decimal_floating_point_literal", "hex_floating_point_literal"})
_STRING_LITERALS = frozenset(
    {"string_literal", "verbatim_string_literal", "raw_string_literal", "interpolated_string_expression", "text_block"}
)
_BOOL_OPERATORS = frozenset({"==", "!=", "<", ">", "<=", ">=", "&&", "||"})
_MAX_CHAIN_STEPS = 12
_MAX_INFER_DEPTH = 40
_MISSING: Any = object()


class JvmCallExtractor:
    def __init__(self, root: object, raw: bytes, language_name: str, inheritance: dict[str, list[str]], record_cls: type) -> None:
        self.raw = raw
        self.java = language_name == "java"
        self.record_cls = record_cls
        self.inheritance = inheritance
        self.class_nodes = _CLASS_NODES[language_name]
        self.owner_nodes = _OWNER_NODES[language_name]
        self.scope_nodes = _SCOPE_NODES[language_name] | self.owner_nodes
        self.scopes: list[dict[str, str | None]] = [{}]
        self.class_stack: list[str] = []
        self.cache: dict[tuple[int, int, str], str | None] = {}
        self.calls: list[Any] = []
        self.fields = self._collect_fields(root)

    # ------------------------------------------------------------------ helpers
    def text(self, node: object | None) -> str:
        if node is None:
            return ""
        return self.raw[node.start_byte : node.end_byte].decode("utf-8", errors="replace")  # type: ignore[attr-defined]

    @staticmethod
    def _field(node: object, name: str) -> object | None:
        try:
            return node.child_by_field_name(name)  # type: ignore[attr-defined]
        except (AttributeError, TypeError):
            return None

    @staticmethod
    def _named(node: object | None) -> list[object]:
        if node is None:
            return []
        return [child for child in node.named_children if child.type not in _COMMENT_TYPES]  # type: ignore[attr-defined]

    def _is_anonymous_body(self, node: object) -> bool:
        parent = getattr(node, "parent", None)
        return node.type == "class_body" and parent is not None and parent.type in {"object_creation_expression", "enum_constant"}  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ fields
    def _collect_fields(self, root: object) -> dict[tuple[str, str], str | None]:
        fields: dict[tuple[str, str], str | None] = {}

        def add(cls: str, name: str, texpr: str | None) -> None:
            key = (cls, name)
            if key not in fields:
                fields[key] = texpr
            elif fields[key] != texpr:
                fields[key] = None  # the same member declared with two different types in one file: unknown

        stack: list[tuple[object, str]] = [(root, "")]
        while stack:
            node, cls = stack.pop()
            kind = node.type  # type: ignore[attr-defined]
            if kind in self.class_nodes:
                name_node = self._field(node, "name")
                cls = self.text(name_node) if name_node is not None else ""
                params = self._field(node, "parameters")  # record components / C# primary constructor parameters
                if params is not None and cls:
                    for parameter in split_params(self.text(params)) or ():
                        key = parameter.ref or parameter.type
                        if parameter.name:
                            add(cls, parameter.name, f"T:{key}" if key else None)
            elif cls:
                if kind == "field_declaration":
                    holder = node
                    if not self.java:
                        holder = next((c for c in node.named_children if c.type == "variable_declaration"), None)  # type: ignore[attr-defined]
                    if holder is not None:
                        type_node = self._field(holder, "type")
                        key = type_ref(self.text(type_node)) if type_node is not None else ""
                        for child in holder.named_children:  # type: ignore[attr-defined]
                            if child.type == "variable_declarator":
                                name_node = self._field(child, "name")
                                if name_node is not None:
                                    add(cls, self.text(name_node), f"T:{key}" if key else None)
                elif kind == "property_declaration" and not self.java:
                    type_node = self._field(node, "type")
                    name_node = self._field(node, "name")
                    if name_node is not None:
                        key = type_ref(self.text(type_node)) if type_node is not None else ""
                        add(cls, self.text(name_node), f"T:{key}" if key else None)
            for child in reversed(node.named_children):  # type: ignore[attr-defined]
                stack.append((child, cls))
        return fields

    def _field_in(self, cls: str, name: str, depth: int) -> Any:
        key = (cls, name)
        if key in self.fields:
            return self.fields[key]
        if depth < 6:
            for base in self.inheritance.get(cls, ()):
                found = self._field_in(base, name, depth + 1)
                if found is not _MISSING:
                    return found
        return _MISSING

    def field_texpr(self, name: str) -> Any:
        for cls in reversed(self.class_stack):
            if not cls:
                continue
            found = self._field_in(cls, name, 0)
            if found is not _MISSING:
                return found
        return _MISSING

    # ------------------------------------------------------------------ scopes
    def declare(self, name: str, texpr: str | None) -> None:
        if name:
            self.scopes[-1][name] = texpr

    def lookup(self, name: str) -> tuple[bool, str | None]:
        for scope in reversed(self.scopes):
            if name in scope:
                return True, scope[name]
        return False, None

    def _declare_params(self, params_node: object | None) -> None:
        if params_node is None:
            return
        kind = params_node.type  # type: ignore[attr-defined]
        if kind in {"identifier", "implicit_parameter"}:
            self.declare(self.text(params_node).strip(), None)
            return
        if kind == "inferred_parameters":
            for child in self._named(params_node):
                self.declare(self.text(child).strip(), None)
            return
        for parameter in split_params(self.text(params_node)) or ():
            key = parameter.ref or parameter.type
            self.declare(parameter.name, f"T:{key}" if key else None)

    def _declare_typed(self, type_node: object | None, name_node: object | None, value: object | None = None) -> None:
        if name_node is None:
            return
        name = self.text(name_node).strip()
        if not name:
            return
        type_text = self.text(type_node).strip() if type_node is not None else ""
        if type_text in {"", "var"} or (type_node is not None and type_node.type == "implicit_type"):  # type: ignore[attr-defined]
            self.declare(name, self.infer(value) if value is not None else None)
            return
        key = type_ref(type_text)
        self.declare(name, f"T:{key}" if key else None)

    # ------------------------------------------------------------------ inference
    def infer(self, node: object | None, depth: int = 0) -> str | None:
        if node is None or depth > _MAX_INFER_DEPTH:
            return None
        key = (node.start_byte, node.end_byte, node.type)  # type: ignore[attr-defined]
        if key in self.cache:
            return self.cache[key]
        result = self._infer(node, depth)
        self.cache[key] = result
        return result

    @staticmethod
    def _extend(base: str | None, step: str) -> str | None:
        if base is None:
            return None
        if base.count("|") >= _MAX_CHAIN_STEPS:
            return None
        return f"{base}|{step}"

    def _arg_count_text(self, args: object | None) -> str:
        if args is None:
            return "?"
        return str(len(self._named(args)))

    def _call_name(self, name_node: object | None) -> str:
        if name_node is None:
            return ""
        if name_node.type == "generic_name":  # type: ignore[attr-defined]
            first = self._named(name_node)
            return self.text(first[0]) if first else self.text(name_node).split("<")[0].strip()
        return self.text(name_node)

    def _infer(self, node: object, depth: int) -> str | None:
        kind = node.type  # type: ignore[attr-defined]
        nxt = depth + 1
        if kind == "identifier":
            name = self.text(node)
            found, texpr = self.lookup(name)
            if found:
                return texpr
            fexpr = self.field_texpr(name)
            if fexpr is not _MISSING:
                return fexpr
            return f"S:{name}" if name[:1].isupper() else None
        if kind == "this":
            return "this"
        if kind in {"super", "base"}:
            return "super"
        if kind == "parenthesized_expression":
            inner = self._named(node)
            return self.infer(inner[0], nxt) if inner else None
        if kind == "cast_expression":
            key = type_ref(self.text(self._field(node, "type")))
            return f"T:{key}" if key else None
        if kind == "as_expression":
            key = type_ref(self.text(self._field(node, "right")))
            return f"T:{key}" if key else None
        if kind == "object_creation_expression":
            type_node = self._field(node, "type")
            key = type_ref(self.text(type_node)) if type_node is not None else ""
            return f"T:{key}" if key and not key.endswith("[]") else None
        if kind == "array_creation_expression":
            type_node = self._field(node, "type")
            key = type_key(self.text(type_node)) if type_node is not None else ""
            return f"T:{key}[]" if key and not key.endswith("[]") else None
        if kind in _STRING_LITERALS:
            return "T:String"
        if kind in {"character_literal"}:
            return "T:char"
        if kind in {"true", "false", "boolean_literal"}:
            return "T:boolean"
        if kind == "null_literal":
            return "T:null"
        if kind in _JAVA_INT_LITERALS or kind == "integer_literal":
            suffix = self.text(node).strip().lower()
            if suffix.endswith(("ul", "lu")):
                return "T:ulong"
            if suffix.endswith("u") and not suffix.startswith("0x"):
                return "T:uint"
            if suffix.endswith("l"):
                return "T:long"
            return "T:int"
        if kind in _JAVA_FLOAT_LITERALS or kind == "real_literal":
            suffix = self.text(node).strip().lower()
            if suffix.endswith("f") and not suffix.startswith("0x"):
                return "T:float"
            if suffix.endswith("m"):
                return "T:decimal"
            return "T:double"
        if kind == "unary_expression":
            operand = self._named(node)
            operator = self.text(self._field(node, "operator")) or ""
            if operator == "!":
                return "T:boolean"
            return self.infer(operand[-1], nxt) if operand else None
        if kind == "postfix_unary_expression":  # C# ``x!``
            operand = self._named(node)
            return self.infer(operand[0], nxt) if operand else None
        if kind == "binary_expression":
            operator = (self.text(self._field(node, "operator")) or "").strip()
            if operator in _BOOL_OPERATORS:
                return "T:boolean"
            if operator == "+":
                left = self.infer(self._field(node, "left"), nxt)
                right = self.infer(self._field(node, "right"), nxt)
                if left in {"T:String", "T:string"} or right in {"T:String", "T:string"}:
                    return "T:String"
            return None
        if kind in {"declaration_expression"}:
            type_node = self._field(node, "type")
            if type_node is not None and type_node.type != "implicit_type":  # type: ignore[attr-defined]
                key = type_ref(self.text(type_node))
                return f"T:{key}" if key else None
            return None
        if kind == "method_invocation":  # Java
            obj = self._field(node, "object")
            base = "this" if obj is None else self.infer(obj, nxt)
            name = self.text(self._field(node, "name"))
            return self._extend(base, f"m:{name}/{self._arg_count_text(self._field(node, 'arguments'))}") if name else None
        if kind == "field_access":  # Java
            obj = self._field(node, "object")
            base = self.infer(obj, nxt)
            name = self.text(self._field(node, "field"))
            return self._extend(base, f"f:{name}") if name else None
        if kind == "invocation_expression":  # C#
            function = self._field(node, "function")
            args = self._field(node, "arguments")
            count = self._arg_count_text(args)
            if function is None:
                return None
            fkind = function.type  # type: ignore[attr-defined]
            if fkind == "member_access_expression":
                base = self.infer(self._field(function, "expression"), nxt)
                name = self._call_name(self._field(function, "name"))
            elif fkind in {"identifier", "generic_name"}:
                base = "this"
                name = self._call_name(function)
            elif fkind == "conditional_access_expression":
                binding = next((c for c in self._named(function) if c.type == "member_binding_expression"), None)
                if binding is None:
                    return None
                base = self.infer(self._field(function, "condition"), nxt)
                name = self._call_name(self._field(binding, "name"))
            else:
                return None
            return self._extend(base, f"m:{name}/{count}") if name else None
        if kind == "member_access_expression":  # C#
            base = self.infer(self._field(node, "expression"), nxt)
            name = self._call_name(self._field(node, "name"))
            return self._extend(base, f"f:{name}") if name else None
        return None

    def _split_texpr(self, texpr: str | None, source: str | None = None) -> tuple[str | None, str | None, str | None]:
        """texpr -> (receiver_type, receiver_type_source, chain)."""
        if not texpr:
            return None, None, None
        if "|" not in texpr:
            if texpr.startswith("T:"):
                key = texpr[2:]
                if not key or key.endswith("[]") or key in {"null"}:
                    return None, None, None
                return key, source, None
            return None, None, None  # a bare "S:Name" / "this" / "super" is already described by the receiver text
        return None, None, texpr

    def arg_types_of(self, args: object | None) -> str | None:
        if args is None:
            return None
        keys: list[str] = []
        for child in self._named(args):
            expression = child
            if child.type == "argument":  # type: ignore[attr-defined]
                if any(c.type == "name_colon" for c in child.named_children):  # type: ignore[attr-defined]
                    return None  # named arguments: positions are not parameter positions
                inner = self._named(child)
                expression = inner[-1] if inner else None
            texpr = self.infer(expression) if expression is not None else None
            if texpr == "this":
                texpr = f"T:{self.class_stack[-1]}" if self.class_stack and self.class_stack[-1] else None
            if texpr and texpr.startswith("T:") and "|" not in texpr:
                keys.append(texpr[2:].rsplit(".", 1)[-1])  # overloads are compared by simple type name
            else:
                keys.append("?")
        if not keys or all(key == "?" for key in keys):
            return None
        return ",".join(keys)

    # ------------------------------------------------------------------ receivers & records
    def _receiver(self, obj: object | None) -> tuple[str | None, str | None, str | None, str | None]:
        """(receiver text, receiver_type, receiver_type_source, chain) of the receiver expression of a call."""
        if obj is None:
            return None, None, None, None
        rec = self.text(obj)
        kind = obj.type  # type: ignore[attr-defined]
        if kind in {"this", "super", "base"}:
            return rec, None, None, None
        if kind == "identifier":
            found, texpr = self.lookup(rec)
            if found:
                rtype, _, chain = self._split_texpr(texpr)
                return rec, rtype, None, chain
            fexpr = self.field_texpr(rec)
            if fexpr is not _MISSING:
                rtype, _, chain = self._split_texpr(fexpr)
                return rec, rtype, "field_type" if rtype else None, chain
            return rec, None, None, None
        if kind in {"field_access", "member_access_expression"}:
            base = self._field(obj, "object" if kind == "field_access" else "expression")
            member = self._field(obj, "field" if kind == "field_access" else "name")
            if base is not None and base.type == "this" and member is not None and self.class_stack and self.class_stack[-1]:  # type: ignore[attr-defined]
                found = self._field_in(self.class_stack[-1], self.text(member), 0)
                if found is not _MISSING:
                    rtype, _, chain = self._split_texpr(found)
                    return rec, rtype, None, chain
        rtype, source, chain = self._split_texpr(self.infer(obj))
        return rec, rtype, source, chain

    def _emit(
        self,
        name: str,
        receiver: str | None,
        node: object,
        *,
        receiver_type: str | None = None,
        source: str | None = None,
        chain: str | None = None,
        args: object | None = None,
        call_kind: str | None = None,
    ) -> None:
        if not name:
            return
        arg_count = len(self._named(args)) if args is not None else None
        self.calls.append(
            self.record_cls(
                name=name,
                receiver=receiver,
                line=int(node.start_point[0]) + 1,  # type: ignore[attr-defined]
                start_byte=int(node.start_byte),  # type: ignore[attr-defined]
                end_byte=int(node.end_byte),  # type: ignore[attr-defined]
                receiver_type=receiver_type,
                is_tainted=False,
                assigned_from_fn=None,
                receiver_type_source=source,
                arg_count=arg_count,
                arg_types=self.arg_types_of(args),
                chain=chain,
                call_kind=call_kind,
            )
        )

    def _creation(self, node: object) -> None:
        type_node = self._field(node, "type")
        if type_node is None:
            return
        text = self.text(type_node).strip()
        clean = text.split("<")[0].strip().rstrip("?")
        if clean.startswith("global::"):
            clean = clean[len("global::"):]
        if not clean:
            return
        if "." in clean:
            receiver, name = clean.rsplit(".", 1)
        else:
            receiver, name = None, clean
        self._emit(name, receiver, node, args=self._field(node, "arguments"), call_kind="new")

    # ------------------------------------------------------------------ traversal
    def run(self, root: object) -> list[Any]:
        enter, exit_, act = 0, 1, 2
        stack: list[tuple[int, Any]] = [(enter, root)]
        while stack:
            kind, payload = stack.pop()
            if kind == exit_:
                self._exit(payload)
                continue
            if kind == act:
                payload()
                continue
            needs_exit, post = self._enter(payload)
            if needs_exit:
                stack.append((exit_, payload))
            for action in reversed(post):
                stack.append((act, action))
            for child in reversed(payload.named_children):
                stack.append((enter, child))
        return self.calls

    def _exit(self, node: object) -> None:
        kind = node.type  # type: ignore[attr-defined]
        if kind in self.class_nodes or self._is_anonymous_body(node):
            if self.class_stack:
                self.class_stack.pop()
        if kind in self.scope_nodes:
            if len(self.scopes) > 1:
                self.scopes.pop()

    def _enter(self, node: object) -> tuple[bool, list[Any]]:
        kind = node.type  # type: ignore[attr-defined]
        needs_exit = False
        post: list[Any] = []
        if kind in self.class_nodes:
            name_node = self._field(node, "name")
            self.class_stack.append(self.text(name_node) if name_node is not None else "")
            needs_exit = True
        elif self._is_anonymous_body(node):
            self.class_stack.append("")
            needs_exit = True
        if kind in self.scope_nodes:
            self.scopes.append({})
            needs_exit = True
            if kind in self.owner_nodes:
                self._declare_params(self._field(node, "parameters"))
            elif kind in _LAMBDA_NODES:
                self._declare_params(self._field(node, "parameters"))

        # ---- declarations
        if kind == "variable_declarator":
            parent = getattr(node, "parent", None)
            ptype = parent.type if parent is not None else ""
            owner = getattr(parent, "parent", None) if parent is not None else None
            is_local = ptype == "local_variable_declaration" or (
                ptype == "variable_declaration" and (owner is None or owner.type not in {"field_declaration", "event_field_declaration"})
            )
            if is_local:
                name_node = self._field(node, "name") or next(iter(self._named(node)), None)
                type_node = self._field(parent, "type")
                value = self._field(node, "value")
                if value is None and not self.java:
                    named = self._named(node)
                    value = named[1] if len(named) > 1 else None
                post.append(lambda n=name_node, t=type_node, v=value: self._declare_typed(t, n, v))
        elif kind in {"enhanced_for_statement", "foreach_statement"}:
            name_node = self._field(node, "name") if self.java else self._field(node, "left")
            if name_node is not None and name_node.type == "identifier":  # type: ignore[attr-defined]
                self._declare_typed(self._field(node, "type"), name_node, None)
        elif kind in {"catch_declaration", "catch_formal_parameter"}:
            name_node = self._field(node, "name")
            type_node = self._field(node, "type")
            if kind == "catch_formal_parameter":
                catch_type = next((c for c in self._named(node) if c.type == "catch_type"), None)
                parts = self._named(catch_type)
                type_node = parts[0] if len(parts) == 1 else None
            self._declare_typed(type_node, name_node, None)
        elif kind == "resource":
            name_node = self._field(node, "name")
            if name_node is not None:
                value = self._field(node, "value")
                post.append(lambda n=name_node, t=self._field(node, "type"), v=value: self._declare_typed(t, n, v))
        elif kind == "instanceof_expression":
            name_node = self._field(node, "name")
            if name_node is not None:
                self._declare_typed(self._field(node, "right"), name_node, None)
        elif kind == "type_pattern":
            named = self._named(node)
            if len(named) >= 2:
                self._declare_typed(named[0], named[-1], None)
        elif kind == "declaration_pattern":
            self._declare_typed(self._field(node, "type"), self._field(node, "name"), None)
        elif kind == "declaration_expression":
            self._declare_typed(self._field(node, "type"), self._field(node, "name"), None)

        # ---- calls
        if self.java:
            if kind == "method_invocation":
                name_node = self._field(node, "name")
                obj = self._field(node, "object")
                rec, rtype, source, chain = self._receiver(obj)
                self._emit(
                    self.text(name_node), rec, node, receiver_type=rtype, source=source, chain=chain,
                    args=self._field(node, "arguments"),
                )
            elif kind == "object_creation_expression":
                self._creation(node)
        else:
            if kind == "invocation_expression":
                self._csharp_invocation(node)
            elif kind == "object_creation_expression":
                self._creation(node)
        return needs_exit, post

    def _csharp_invocation(self, node: object) -> None:
        args = self._field(node, "arguments")
        function = self._field(node, "function") or (node.named_children[0] if getattr(node, "named_children", None) else None)  # type: ignore[attr-defined]
        if function is None:
            return
        kind = function.type  # type: ignore[attr-defined]
        if kind == "member_access_expression":
            name_node = self._field(function, "name")
            if name_node is None:
                return
            rec, rtype, source, chain = self._receiver(self._field(function, "expression"))
            self._emit(self._call_name(name_node), rec, node, receiver_type=rtype, source=source, chain=chain, args=args)
        elif kind in {"identifier", "generic_name"}:
            self._emit(self._call_name(function), None, node, args=args)
        elif kind == "conditional_access_expression":
            binding = next((c for c in self._named(function) if c.type == "member_binding_expression"), None)
            if binding is None:
                return
            name_node = self._field(binding, "name")
            if name_node is None:
                return
            condition = self._field(function, "condition")
            rec, rtype, source, chain = self._receiver(condition)
            self._emit(self._call_name(name_node), rec, node, receiver_type=rtype, source=source, chain=chain, args=args)


def extract_calls_jvm(root: object, raw: bytes, language_name: str, inheritance: dict[str, list[str]], record_cls: type) -> list[Any]:
    """CallRecords of a Java or C# file (see the module docstring)."""
    return JvmCallExtractor(root, raw, language_name, inheritance, record_cls).run(root)

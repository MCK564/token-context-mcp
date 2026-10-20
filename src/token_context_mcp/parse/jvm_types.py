"""Type-text helpers shared by the Java/C# parser and the lexical edge resolver (M13).

Java and C# are statically typed, so a call can be bound much more tightly than the dynamic-language heuristics allow
once three things are known: the (simple) type of the receiver, the number of arguments, and the *types* of the
arguments.  Everything here works on the *text* of declarations and signatures (no semantic model is available):

* ``clean_type``      - ``Map<String, List<Foo>>`` -> ``Map``, ``System.Text.StringBuilder`` -> ``StringBuilder``;
                        arrays/pointers/tuples are not receivers, so they clean to ``""``.
* ``type_key``        - like ``clean_type`` but keeps an array suffix (``String[]``) for overload scoring;
* ``type_ref``        - like ``type_key`` but keeps the enclosing type of a nested type (``Connection.Response``).
* ``split_params``    - the parameter list of a method signature (types, names, ``params``/varargs/optional flags).
* ``return_type``     - the declared return type of a method signature.
* ``property_type``   - the declared type of a C# property signature.
* ``arg_type_score``  - how well an argument of a known type fits a parameter type (higher is better).

All functions are pure and deterministic (a precondition of the index being byte-reproducible).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# modifiers that may precede a type in a declaration / parameter and are not part of it
_TYPE_MODIFIERS = frozenset(
    {
        "final", "readonly", "ref", "out", "in", "params", "this", "scoped", "const", "volatile", "static",
        "public", "private", "protected", "internal", "abstract", "virtual", "override", "sealed", "async", "new",
        "extern", "unsafe", "partial", "synchronized", "native", "default", "strictfp", "transient", "required",
        "readonly", "fixed", "implicit", "explicit", "operator", "event", "volatile", "sealed", "record", "mutable",
    }
)

# canonical keys of the primitive-like types of both languages (Java primitives + C# keywords + BCL names)
_CANONICAL: dict[str, str] = {
    "string": "string", "String": "string", "System.String": "string",
    "object": "object", "Object": "object",
    "bool": "bool", "boolean": "bool", "Boolean": "bool",
    "byte": "byte", "Byte": "byte", "sbyte": "sbyte", "SByte": "sbyte",
    "short": "short", "Short": "short", "Int16": "short", "ushort": "ushort", "UInt16": "ushort",
    "int": "int", "Integer": "int", "Int32": "int", "uint": "uint", "UInt32": "uint",
    "long": "long", "Long": "long", "Int64": "long", "ulong": "ulong", "UInt64": "ulong",
    "float": "float", "Float": "float", "Single": "float",
    "double": "double", "Double": "double",
    "decimal": "decimal", "Decimal": "decimal",
    "char": "char", "Character": "char", "Char": "char",
    "void": "void", "Void": "void",
}
_BOXED_NAMES = frozenset(
    {"Boolean", "Byte", "Short", "Integer", "Long", "Float", "Double", "Character", "Boolean", "SByte", "Int16",
     "UInt16", "Int32", "UInt32", "Int64", "UInt64", "Single", "Decimal", "Char"}
)
_NUMERIC_ORDER = ("byte", "sbyte", "short", "ushort", "char", "int", "uint", "long", "ulong", "float", "double", "decimal")
_NUMERIC_RANK = {name: rank for rank, name in enumerate(_NUMERIC_ORDER)}
_PRIMITIVE_KEYS = frozenset(_NUMERIC_ORDER) | {"bool"}

# well known supertypes of String (JDK / BCL) that are not in the repository hierarchy
_STRING_SUPERTYPES = frozenset(
    {
        "object", "CharSequence", "Comparable", "IComparable", "Serializable", "ICloneable", "IConvertible",
        "IEquatable", "IEnumerable", "Constable", "ConstantDesc", "Appendable",
    }
)

_ANNOTATION_RE = re.compile(r"@\w+(?:\.\w+)*")


def _strip_balanced(text: str, open_ch: str, close_ch: str) -> str:
    """Remove every balanced ``open_ch ... close_ch`` group of ``text`` (nested groups included)."""
    out: list[str] = []
    depth = 0
    for ch in text:
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            if depth:
                depth -= 1
            else:
                out.append(ch)
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def _strip_annotations(text: str) -> str:
    """Drop Java annotations (``@Nullable``, ``@Size(max = 3)``) and C# attribute lists (``[In, Out]``)."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "@" and i + 1 < n and (text[i + 1].isalpha() or text[i + 1] == "_"):
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] in "_."):
                j += 1
            k = j
            while k < n and text[k] == " ":
                k += 1
            if k < n and text[k] == "(":
                depth = 0
                while k < n:
                    if text[k] == "(":
                        depth += 1
                    elif text[k] == ")":
                        depth -= 1
                        if depth == 0:
                            k += 1
                            break
                    k += 1
                j = k
            i = j
            continue
        if ch == "[":
            # an attribute list never follows a type directly; array brackets do ("int[]", "T[,]")
            before = "".join(out).rstrip()
            if not before or before[-1] in ",(":
                depth = 0
                j = i
                while j < n:
                    if text[j] == "[":
                        depth += 1
                    elif text[j] == "]":
                        depth -= 1
                        if depth == 0:
                            j += 1
                            break
                    j += 1
                i = j
                continue
        out.append(ch)
        i += 1
    return "".join(out)


@lru_cache(maxsize=65536)
def _type_path(text: str) -> tuple[tuple[str, ...], str] | None:
    """(dotted segments, array suffix) of a declared type with annotations, modifiers, generics and nullability removed."""
    cleaned = _strip_annotations(text or "").strip()
    if not cleaned or cleaned == "var":
        return None
    pieces = [piece for piece in re.split(r"\s+", cleaned) if piece]
    while pieces and pieces[0] in _TYPE_MODIFIERS:
        pieces.pop(0)
    cleaned = " ".join(pieces)
    if not cleaned:
        return None
    if cleaned.startswith("("):  # C# tuple type
        return None
    cleaned = _strip_balanced(cleaned, "<", ">").strip()
    array = ""
    if cleaned.endswith("..."):
        cleaned, array = cleaned[:-3].strip(), "[]"
    while cleaned.endswith("]"):
        cut = cleaned.rfind("[")
        if cut < 0:
            return None
        cleaned, array = cleaned[:cut].strip(), "[]"
    cleaned = cleaned.rstrip("?*& ").strip()
    if cleaned.startswith("global::"):
        cleaned = cleaned[len("global::"):]
    segments = tuple(segment.strip().rstrip("?") for segment in cleaned.split("."))
    if not segments or not all(_IDENT_RE.match(segment) for segment in segments):
        return None
    return segments, array


def type_key(text: str) -> str:
    """Simple type name of a declared type, keeping an array suffix (``String[]``); ``""`` when it is not a plain type."""
    path = _type_path(text)
    if path is None:
        return ""
    segments, array = path
    return segments[-1] + array


def type_ref(text: str) -> str:
    """Like ``type_key`` but a nested type written with its enclosing type keeps it (``Connection.Response``): two
    nested types may share a simple name, and the qualifier is what tells them apart.  Only the last two segments are
    kept and only when the qualifier looks like a type (capitalised); the resolver decides whether it really is one."""
    path = _type_path(text)
    if path is None:
        return ""
    segments, array = path
    if len(segments) >= 2 and segments[-2][:1].isupper():
        return f"{segments[-2]}.{segments[-1]}{array}"
    return segments[-1] + array


def clean_type(text: str) -> str:
    """Simple type name usable as a *receiver type* (arrays are not: they carry no repository members)."""
    key = type_key(text)
    return "" if key.endswith("[]") else key


def extract_generic_args(text: str) -> list[str]:
    """Extract top-level generic argument strings from a type text like Map<K, List<V>> -> ['K', 'List<V>']."""
    cleaned = _strip_annotations(text or "").strip()
    idx = cleaned.find("<")
    if idx < 0 or not cleaned.endswith(">"):
        return []
    inner = cleaned[idx + 1 : -1].strip()
    if not inner:
        return []
    args: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in inner:
        if ch == "<":
            depth += 1
            cur.append(ch)
        elif ch == ">":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            arg = "".join(cur).strip()
            if arg:
                args.append(arg)
            cur = []
        else:
            cur.append(ch)
    if cur:
        arg = "".join(cur).strip()
        if arg:
            args.append(arg)
    return args


_COLLECTION_CONTAINERS = frozenset({
    "List", "IList", "IReadOnlyList", "Collection", "ICollection", "IReadOnlyCollection",
    "Set", "ISet", "IReadOnlySet", "HashSet", "TreeSet", "SortedSet",
    "Queue", "Deque", "Stack", "Iterable", "IEnumerable", "IAsyncEnumerable",
    "Stream", "Flux", "Observable",
})

_MAP_CONTAINERS = frozenset({
    "Map", "IDictionary", "IReadOnlyDictionary", "Dictionary", "SortedDictionary",
    "ConcurrentDictionary", "HashMap", "TreeMap", "LinkedHashMap",
})

_WRAPPER_CONTAINERS = frozenset({
    "Task", "ValueTask", "CompletableFuture", "Future", "Optional", "Nullable",
})


def element_type_of(text: str) -> str:
    """Infer the element type_key of a collection or array type text."""
    if not text:
        return ""
    key = type_key(text)
    if key.endswith("[]"):
        return key[:-2]
    # Check container
    cont = clean_type(text)
    if cont in _COLLECTION_CONTAINERS:
        gargs = extract_generic_args(text)
        if gargs:
            return type_key(gargs[0])
    elif cont in _MAP_CONTAINERS:
        gargs = extract_generic_args(text)
        if len(gargs) >= 2:
            return type_key(gargs[1])
    return ""


def unwrap_wrapper_type(text: str) -> str:
    """Unwrap Task<T>, ValueTask<T>, CompletableFuture<T>, Optional<T>, Nullable<T> -> T."""
    if not text:
        return ""
    cont = clean_type(text)
    if cont in _WRAPPER_CONTAINERS:
        gargs = extract_generic_args(text)
        if gargs:
            return type_key(gargs[0])
    return ""


@dataclass(frozen=True)
class Param:
    type: str  # type_key of the parameter ("" when unknown); element type for varargs is type[:-2]
    name: str
    varargs: bool = False
    optional: bool = False
    is_this: bool = False
    ref: str = ""  # type_ref of the parameter (keeps ``Outer`` of ``Outer.Inner``); only used to type the parameter as a receiver
    raw: str = ""  # raw type string including generic arguments (e.g. List<Item>)


def _find_param_list(signature: str) -> tuple[int, int] | None:
    """(start, end) offsets of the parameter list parentheses of a method/constructor signature."""
    text = signature
    # skip leading annotations / attribute lists
    i = 0
    n = len(text)
    while True:
        while i < n and text[i] == " ":
            i += 1
        if i < n and text[i] == "@":
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] in "_."):
                j += 1
            k = j
            while k < n and text[k] == " ":
                k += 1
            if k < n and text[k] == "(":
                depth = 0
                while k < n:
                    if text[k] == "(":
                        depth += 1
                    elif text[k] == ")":
                        depth -= 1
                        if depth == 0:
                            k += 1
                            break
                    k += 1
                j = k
            i = j
            continue
        if i < n and text[i] == "[":
            depth = 0
            j = i
            while j < n:
                if text[j] == "[":
                    depth += 1
                elif text[j] == "]":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                j += 1
            i = j
            continue
        break
    angle = 0
    start = -1
    for pos in range(i, n):
        ch = text[pos]
        if ch == "<":
            angle += 1
        elif ch == ">":
            angle = max(0, angle - 1)
        elif ch == "(" and angle == 0:
            start = pos
            break
        elif ch in "{=" and angle == 0:
            return None  # a property / field / expression body before any parameter list
    if start < 0:
        return None
    depth = 0
    quote = ""
    for pos in range(start, n):
        ch = text[pos]
        if quote:
            if ch == quote and text[pos - 1] != "\\":
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return start, pos
    return start, n  # truncated signature: use what is there


def _split_top_level(text: str, sep: str = ",") -> list[str]:
    parts: list[str] = []
    depth_round = depth_angle = depth_square = depth_curly = 0
    quote = ""
    current: list[str] = []
    prev = ""
    for ch in text:
        if quote:
            current.append(ch)
            if ch == quote and prev != "\\":
                quote = ""
            prev = ch
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "(":
            depth_round += 1
        elif ch == ")":
            depth_round = max(0, depth_round - 1)
        elif ch == "[":
            depth_square += 1
        elif ch == "]":
            depth_square = max(0, depth_square - 1)
        elif ch == "{":
            depth_curly += 1
        elif ch == "}":
            depth_curly = max(0, depth_curly - 1)
        elif ch == "<":
            depth_angle += 1
        elif ch == ">" and prev != "=":
            depth_angle = max(0, depth_angle - 1)
        if ch == sep and not (depth_round or depth_angle or depth_square or depth_curly):
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
        prev = ch
    parts.append("".join(current))
    return parts


@lru_cache(maxsize=65536)
def split_params(signature: str | None) -> tuple[Param, ...] | None:
    """Parameters of a method/constructor signature, or ``None`` when the text has no parameter list."""
    if not signature:
        return None
    located = _find_param_list(signature)
    if located is None:
        return None
    start, end = located
    inner = signature[start + 1 : end].strip()
    if not inner:
        return ()
    params: list[Param] = []
    for raw in _split_top_level(inner):
        text = raw.strip()
        if not text:
            continue
        text = _strip_annotations(text).strip()
        optional = False
        pieces = _split_top_level(text, "=")
        # "a == b" cannot appear before the default value, so the first "=" separates it
        if len(pieces) > 1:
            optional = True
            text = pieces[0].strip()
        varargs = "..." in text
        tokens = [t for t in re.split(r"\s+", text) if t]
        # C# generic types may contain spaces ("Dictionary<string, int> d") - merge by angle depth
        merged: list[str] = []
        depth = 0
        for token in tokens:
            if depth > 0 and merged:
                merged[-1] += " " + token
            else:
                merged.append(token)
            depth += token.count("<") - token.count(">")
        tokens = merged
        is_this = bool(tokens) and tokens[0] == "this" and len(tokens) > 1
        if "params" in tokens:
            varargs = True
        name = tokens[-1] if tokens else ""
        type_tokens = [t for t in tokens[:-1] if t not in _TYPE_MODIFIERS]
        if len(tokens) == 1:  # no type information (TypeScript-like or a bare name)
            params.append(Param("", name, varargs, optional, False))
            continue
        raw_t = " ".join(type_tokens)
        key = type_key(raw_t)
        ref = type_ref(raw_t)
        if varargs and key and not key.endswith("[]"):
            key += "[]"
            ref += "[]"
        params.append(Param(key, name.rstrip("."), varargs, optional, is_this, ref, raw_t))
    return tuple(params)


def arity_range(params: tuple[Param, ...] | None, *, instance_call: bool = True) -> tuple[int, int | None] | None:
    """(min, max) number of call arguments the parameters accept; ``max`` is ``None`` for variable arity."""
    if params is None:
        return None
    effective = list(params)
    if instance_call and effective and effective[0].is_this:
        # extension method called as ``receiver.M(args)``: the receiver is the first parameter
        effective = effective[1:]
    required = 0
    total = 0
    variable = False
    for p in effective:
        total += 1
        if p.varargs:
            variable = True
        elif not p.optional:
            required += 1
    if variable:
        return required, None
    return required, total


@lru_cache(maxsize=65536)
def return_type(signature: str | None, name: str) -> str:
    """``type_key`` of the declared return type of a method signature (``""`` for constructors and unknown shapes)."""
    if not signature:
        return ""
    located = _find_param_list(signature)
    if located is None:
        return ""
    head = signature[: located[0]]
    head = _strip_annotations(head).strip()
    # generic method type parameters follow the name ("Foo<T>") or precede the type ("<T> List<T> foo")
    head = head.strip()
    if not head.endswith(name) and name:
        # "Name<T>" - drop the generic list of the name
        trimmed = re.sub(r"<[^<>]*(?:<[^<>]*>[^<>]*)*>\s*$", "", head).strip()
        head = trimmed if trimmed.endswith(name) else head
    if not head.endswith(name):
        return ""
    head = head[: len(head) - len(name)].strip()
    if not head:
        return ""
    # a leading "<T extends X>" is the method's own type parameter list
    if head.startswith("<"):
        depth = 0
        for pos, ch in enumerate(head):
            if ch == "<":
                depth += 1
            elif ch == ">":
                depth -= 1
                if depth == 0:
                    head = head[pos + 1 :].strip()
                    break
    tokens: list[str] = []
    depth = 0
    for token in re.split(r"\s+", head):
        if not token:
            continue
        if depth > 0 and tokens:
            tokens[-1] += " " + token
        else:
            tokens.append(token)
        depth += token.count("<") - token.count(">")
    tokens = [t for t in tokens if t not in _TYPE_MODIFIERS]
    if not tokens:
        return ""
    return type_key(tokens[-1])


@lru_cache(maxsize=65536)
def return_type_full(signature: str | None, name: str) -> str:
    """Full return type text (including generics e.g. Task<Worker>) of a method signature."""
    if not signature:
        return ""
    located = _find_param_list(signature)
    if located is None:
        return ""
    head = signature[: located[0]]
    head = _strip_annotations(head).strip()
    head = head.strip()
    if not head.endswith(name) and name:
        trimmed = re.sub(r"<[^<>]*(?:<[^<>]*>[^<>]*)*>\s*$", "", head).strip()
        head = trimmed if trimmed.endswith(name) else head
    if not head.endswith(name):
        return ""
    head = head[: len(head) - len(name)].strip()
    if not head:
        return ""
    if head.startswith("<"):
        depth = 0
        for pos, ch in enumerate(head):
            if ch == "<":
                depth += 1
            elif ch == ">":
                depth -= 1
                if depth == 0:
                    head = head[pos + 1 :].strip()
                    break
    tokens: list[str] = []
    depth = 0
    for token in re.split(r"\s+", head):
        if not token:
            continue
        if depth > 0 and tokens:
            tokens[-1] += " " + token
        else:
            tokens.append(token)
        depth += token.count("<") - token.count(">")
    tokens = [t for t in tokens if t not in _TYPE_MODIFIERS]
    if not tokens:
        return ""
    return tokens[-1].strip()


@lru_cache(maxsize=65536)
def property_type(signature: str | None, name: str) -> str:
    """``type_key`` of a C# property / field signature (``public CultureInfo CultureInfo { get; set; }``)."""
    if not signature or not name:
        return ""
    head = signature.split("{", 1)[0].split("=>", 1)[0].split("=", 1)[0]
    head = _strip_annotations(head).strip().rstrip(";").strip()
    if not head.endswith(name):
        return ""
    head = head[: len(head) - len(name)].strip()
    tokens: list[str] = []
    depth = 0
    for token in re.split(r"\s+", head):
        if not token:
            continue
        if depth > 0 and tokens:
            tokens[-1] += " " + token
        else:
            tokens.append(token)
        depth += token.count("<") - token.count(">")
    tokens = [t for t in tokens if t not in _TYPE_MODIFIERS]
    if not tokens:
        return ""
    return type_key(tokens[-1])


def canonical(key: str) -> str:
    """Canonical key of a (possibly boxed / aliased) primitive-like type; other names are returned unchanged."""
    return _CANONICAL.get(key, key)


def is_type_parameter(key: str) -> bool:
    """Heuristic: single capital letter or ``T``-prefixed capitalised name (``T``, ``K``, ``TKey``, ``TResult``)."""
    base = key[:-2] if key.endswith("[]") else key
    return bool(re.fullmatch(r"[A-Z][0-9]?", base) or re.fullmatch(r"T[A-Z][A-Za-z0-9]*", base))


def arg_type_score(
    arg: str | None,
    param: str,
    *,
    ancestors: Callable[[str], list[str]],
    repo_types: Callable[[str], bool],
) -> int:
    """Fit of an argument of type ``arg`` (a ``type_key``; ``None``/``"?"`` unknown, ``"null"`` the null literal) to
    a parameter declared as ``param``.  Positive = compatible (higher = tighter), 0 = no information, negative =
    certainly incompatible.  Only relations that can be decided from the repository itself, from the primitives and
    from ``String`` are judged incompatible; anything involving other external types is neutral."""
    if not arg or arg == "?":
        return 0
    if not param:
        return 0
    if is_type_parameter(param):
        return 1 if arg != "void" else 0
    if arg == "null":
        return 1 if canonical(param) not in _PRIMITIVE_KEYS else -5
    arg_array = arg.endswith("[]")
    param_array = param.endswith("[]")
    if arg_array != param_array:
        # an array only converts to Object/Iterable-like external supertypes; a scalar never converts to an array
        if param_array:
            return -5
        return 1 if canonical(param) in {"object"} else 0
    base_arg = arg[:-2] if arg_array else arg
    base_param = param[:-2] if param_array else param
    if arg_array and (is_type_parameter(base_param) or canonical(base_param) == "object"):
        return 1
    ca, cp = canonical(base_arg), canonical(base_param)
    boxed_arg = base_arg in _BOXED_NAMES
    boxed_param = base_param in _BOXED_NAMES
    if ca == cp:
        if arg_array:
            return 7
        return 6 if boxed_arg == boxed_param else 5
    if cp == "object":
        return 1
    if ca in _PRIMITIVE_KEYS or cp in _PRIMITIVE_KEYS:
        if ca in _PRIMITIVE_KEYS and cp in _PRIMITIVE_KEYS:
            if ca in _NUMERIC_RANK and cp in _NUMERIC_RANK and _NUMERIC_RANK[ca] < _NUMERIC_RANK[cp]:
                # implicit widening (int -> long -> float -> double); smaller jumps fit tighter
                return max(2, 4 - (_NUMERIC_RANK[cp] - _NUMERIC_RANK[ca]) // 3)
            return -5
        # primitive vs reference type: only boxing (handled above) and Object/Number-like supertypes work
        other = base_param if ca in _PRIMITIVE_KEYS else base_arg
        if canonical(other) == "string" or repo_types(other):
            return -5
        return 0
    if ca == "string":
        if cp in {canonical(s) for s in _STRING_SUPERTYPES} or base_param in _STRING_SUPERTYPES:
            return 2
        return -5 if repo_types(base_param) else 0
    if cp == "string":
        return -5 if repo_types(base_arg) else 0
    if repo_types(base_arg) and repo_types(base_param):
        if base_arg == base_param:
            return 6
        if base_param in ancestors(base_arg):
            return 4
        return -5
    if repo_types(base_arg) and base_param in ancestors(base_arg):
        return 4
    return 0

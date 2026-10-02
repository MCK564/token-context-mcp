from __future__ import annotations

import posixpath
import re
from collections import defaultdict
from collections.abc import Callable
from functools import lru_cache
from typing import TYPE_CHECKING

from token_context_mcp.models import EdgeRecord, ExternalStubRecord, SymbolRecord
from token_context_mcp.parse import jvm_types as jt

if TYPE_CHECKING:
    from token_context_mcp.parse.treesitter import CallRecord

_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][$\w]*\b")

# Per-file budget of edge resolution (a guard against pathological files), counted in abstract work units
# (one unit per symbol scanned to find the enclosing symbol of a call, ``WORK_PER_CANDIDATE`` per candidate handed to
# the resolver) and NOT in wall-clock time: a time-based breaker made two builds of the same tree differ on a loaded
# machine (M12 review).  The largest file of the benchmark corpora needs ~2e5 units, so 4e6 never fires on real code.
FILE_EDGE_WORK_BUDGET = 4_000_000
WORK_PER_CANDIDATE = 20

RESOLVER_VERSION = 4  # 4: M13 Java/C# member resolution (types, overloads, hierarchy, chains); 3: M12

# Calibrated confidence scores per scope based on evals/out/m4/edge_eval_final.json
# Values rounded down to step 0.05. Scopes with n < 10 retain conservative default values.
SCOPE_CONFIDENCE: dict[str, float] = {
    "same_class": 0.95,
    "same_class_split": 0.85,
    "implicit_this": 0.90,
    "implicit_this_partial": 0.85,
    "overload_arity": 0.85,
    "overload_group": 0.70,
    "cha_inherited": 0.90,
    "attr_type": 0.95,
    "attr_type_inherited": 0.90,
    # M6.0: self.x = <typed constructor/method parameter>. Provisional; not yet
    # calibrated against gold (n < 10 at introduction) — recalibrate per the M4
    # methodology once evals/out/m6/edge_eval_attr_param.json has enough samples.
    "attr_param": 0.90,
    "exact_receiver_type": 0.95,
    "field_type": 0.85,
    "same_file": 0.90,
    "receiver_match": 0.90,
    "import_match": 0.90,
    "import_module_match": 0.75,
    "same_package": 0.75,
    "same_namespace": 0.80,
    "namespace_match": 0.80,
    "global": 0.40,
    "virtual_stub": 0.90,
}


def _namespace_ancestors(ns: str) -> list[str]:
    """Return self and enclosing namespace prefixes for C# (e.g. 'A.B.C' -> ['A.B.C', 'A.B', 'A'])."""
    parts = ns.split(".")
    return [".".join(parts[:i]) for i in range(len(parts), 0, -1)]


def _count_params(sig: str | None) -> int | None:
    if not sig:
        return None
    start = sig.find("(")
    end = sig.rfind(")")
    if start == -1 or end == -1 or end <= start:
        return None
    param_str = sig[start + 1 : end].strip()
    if not param_str:
        return 0
    count = 0
    depth = 0
    current_token: list[str] = []
    for ch in param_str:
        if ch in "([{<":
            depth += 1
            current_token.append(ch)
        elif ch in ")]}>":
            depth = max(0, depth - 1)
            current_token.append(ch)
        elif ch == "," and depth == 0:
            if "".join(current_token).strip():
                count += 1
            current_token = []
        else:
            current_token.append(ch)
    if "".join(current_token).strip():
        count += 1
    return count


def _try_resolve_overload(
    candidates: list[SymbolRecord],
    source: SymbolRecord,
    call_arg_count: int | None,
) -> tuple[SymbolRecord | None, str, float] | None:
    if not candidates or len(candidates) < 2:
        return None
    # E2: Only C#, Java, TS. Strictly NOT enabled for Python.
    is_overload_lang = (
        source.symbol_id.startswith(("c_sharp:", "java:", "typescript:", "tsx:"))
        or source.path.endswith((".cs", ".java", ".ts", ".tsx"))
    )
    if not is_overload_lang:
        return None

    # Check if all remaining candidates have the exact same qualified_name
    qnames = {c.qualified_name for c in candidates}
    if len(qnames) != 1:
        return None

    # 1. Overload arity match (matching parameter count with argument count)
    if call_arg_count is not None:
        arity_matches = [
            c for c in candidates
            if _count_params(c.signature) == call_arg_count
        ]
        if len(arity_matches) == 1:
            return arity_matches[0], "overload_arity", SCOPE_CONFIDENCE.get("overload_arity", 0.85)

    # 2. Overload group match (smallest start_line)
    best = min(candidates, key=lambda c: c.start_line)
    return best, "overload_group", SCOPE_CONFIDENCE.get("overload_group", 0.70)



def _extract_repo_return_types(symbols: list[SymbolRecord]) -> dict[str, str]:
    repo_return_types: dict[str, str] = {}
    for s in symbols:
        if s.kind in {"function", "method"} and s.signature:
            m = re.search(r"->\s*([A-Za-z_][A-Za-z0-9_]*)", s.signature)
            if m:
                ret = m.group(1)
                if ret not in _BUILTIN_RECEIVERS and ret not in {
                    "None", "Any", "void", "bool", "int", "str", "float",
                    "dict", "list", "set", "tuple", "bytes",
                }:
                    if s.name not in repo_return_types:
                        repo_return_types[s.name] = ret
                    elif repo_return_types[s.name] != ret:
                        repo_return_types[s.name] = ""
    return repo_return_types


def _get_ancestors(cls_name: str, inheritance_map: dict[str, list[str]] | None) -> list[str]:
    if not inheritance_map or not cls_name:
        return []
    short_name = cls_name.rsplit(".", 1)[-1]
    parents = inheritance_map.get(cls_name) or inheritance_map.get(short_name) or []
    ancestors: list[str] = []
    queue = list(parents)
    visited = set(queue)
    while queue:
        curr = queue.pop(0)
        ancestors.append(curr)
        curr_short = curr.rsplit(".", 1)[-1]
        next_parents = inheritance_map.get(curr) or inheritance_map.get(curr_short) or []
        for p in next_parents:
            if p not in visited:
                visited.add(p)
                queue.append(p)
    return ancestors


# --------------------------------------------------------------------------------------------------------------------
# M13: Java / C# member resolution.  Both languages are statically typed, so a call can be bound much more tightly than
# the dynamic-language heuristics below allow: the receiver's declared type (or an evaluated receiver chain), the
# number of arguments and the types of the arguments pick *the* overload, and the class hierarchy finds inherited
# members.  Python / JS / TS never enter this code (``_is_jvm_source``), so their results are unchanged.
# --------------------------------------------------------------------------------------------------------------------
_JVM_TYPE_KINDS = frozenset({"class", "struct", "interface", "enum", "record", "annotation"})
_JVM_CALLABLE_KINDS = frozenset({"method", "function"})
_JVM_PRIMITIVE_LIKE = frozenset(
    {"byte", "sbyte", "short", "ushort", "int", "uint", "long", "ulong", "float", "double", "decimal", "char", "bool", "boolean", "string", "object", "void"}
)

SCOPE_CONFIDENCE.update(
    {
        "overload_types": 0.85,  # same-arity overloads told apart by the types of the arguments
        "chain_type": 0.85,  # receiver type evaluated from a call chain (a.b().c()) through declared return types
        "extension_method": 0.75,  # C# extension method found through the receiver's type
    }
)


def _is_jvm_source(source: SymbolRecord) -> bool:
    return source.symbol_id.startswith(("c_sharp:", "java:")) or source.path.endswith((".cs", ".java"))


def _jvm_is_member(candidate: SymbolRecord, owner: str) -> bool:
    """``candidate`` is declared *directly* in type ``owner`` (a nested type's members are not members of the outer type)."""
    qualified = candidate.qualified_name
    return qualified == f"{owner}.{candidate.name}" or qualified.endswith(f".{owner}.{candidate.name}")


def _enclosing_prefixes(source: SymbolRecord) -> list[str]:
    """Qualified names of the types lexically enclosing ``source``, innermost first (``A.B.m`` -> ``A.B``, ``A``)."""
    qualified = source.qualified_name
    if source.kind in _JVM_TYPE_KINDS:
        prefix = qualified
    elif "." in qualified:
        prefix = qualified.rsplit(".", 1)[0]
    else:
        return []
    prefixes = [prefix]
    while "." in prefix:
        prefix = prefix.rsplit(".", 1)[0]
        prefixes.append(prefix)
    return prefixes


class _JvmContext:
    """Repository-wide facts of Java/C# resolution, built once per ``build_lexical_edges`` call."""

    def __init__(self, symbols: list[SymbolRecord], by_name: dict[str, list[SymbolRecord]], class_hierarchy: dict[str, list[str]] | None):
        self.by_name = by_name
        self.class_hierarchy = class_hierarchy
        self.type_names = {s.name for s in symbols if s.kind in _JVM_TYPE_KINDS and _is_jvm_source(s)}
        self.type_paths: dict[str, set[str]] = defaultdict(set)
        for s in symbols:
            if s.kind in _JVM_TYPE_KINDS and _is_jvm_source(s):
                self.type_paths[s.name].add(s.path)
        self._ancestors: dict[str, list[str]] = {}
        self._chains: dict[tuple[str, str, str], str | None] = {}

    def ancestors(self, name: str) -> list[str]:
        cached = self._ancestors.get(name)
        if cached is None:
            cached = _get_ancestors(name, self.class_hierarchy)
            self._ancestors[name] = cached
        return cached

    def is_type(self, name: str) -> bool:
        return name in self.type_names

    def home_paths(self, type_name: str | None) -> set[str] | None:
        """Files declaring the type ``type_name`` (a name may be shared by several nested types)."""
        if not type_name:
            return None
        return self.type_paths.get(type_name.rsplit(".", 1)[-1])


def _jvm_levels(
    candidates: list[SymbolRecord], owner: str, ctx: _JvmContext, *, ancestors_only: bool = False
) -> list[list[SymbolRecord]]:
    """Members of ``owner`` and of its ancestors named like the call, nearest type first (one list per type).
    ``owner`` may be written ``Outer.Inner``; the hierarchy is keyed by simple names."""
    ancestors = ctx.ancestors(owner.rsplit(".", 1)[-1])
    owners = ancestors if ancestors_only else [owner, *ancestors]
    levels: list[list[SymbolRecord]] = []
    for type_name in owners:
        members = [c for c in candidates if _jvm_is_member(c, type_name)]
        # a type's methods win over a same-named property; a delegate-typed property is invoked like a method
        members = [c for c in members if c.kind in _JVM_CALLABLE_KINDS] or [c for c in members if c.kind == "property"]
        if members:
            levels.append(members)
    return levels


def _java_package(path: str, file_namespaces: dict[str, list[str]] | None) -> str | None:
    """Declared ``package`` of a Java file (``file_namespaces`` carries it); ``None`` when unknown (or not Java)."""
    if not file_namespaces or not path.endswith(".java"):
        return None
    packages = file_namespaces.get(path)
    return packages[0] if packages else None


def _java_wildcard_match(imp: str, candidate: SymbolRecord, file_namespaces: dict[str, list[str]] | None) -> bool:
    """``import a.b.*;`` (a package) and ``import static a.b.C.*;`` (the members of a class) against ``candidate``."""
    if not imp.endswith(".*") or not candidate.path.endswith(".java"):
        return False
    prefix = imp[:-2]
    if _java_package(candidate.path, file_namespaces) == prefix:
        return True
    owner = prefix.rsplit(".", 1)[-1]
    return candidate.qualified_name.startswith(f"{owner}.") and candidate.path.endswith(prefix.replace(".", "/") + ".java")


def _jvm_norm_type(ref: str, ctx: _JvmContext) -> str:
    """A receiver type written ``Qualifier.Name`` keeps its qualifier only when that is a type of the repository
    (``Connection.Response``); a package or namespace in front of the name is dropped."""
    if "." not in ref:
        return ref
    qualifier, simple = ref.rsplit(".", 1)
    return ref if ctx.is_type(qualifier.rsplit(".", 1)[-1]) else simple


def _jvm_is_library_nested(ref: str, source: SymbolRecord, ctx: _JvmContext) -> bool:
    """Java ``Map.Entry``: the qualifier is a capitalised name that is no type of the repository, so it is a library
    class and the nested type is the library's (Java packages are lower case; C# namespaces are not, hence Java only)."""
    if "." not in ref or not source.path.endswith(".java"):
        return False
    qualifier = ref.rsplit(".", 1)[0].rsplit(".", 1)[-1]
    return qualifier[:1].isupper() and not ctx.is_type(qualifier)


def _jvm_param_key(candidate: SymbolRecord) -> tuple | None:
    params = jt.split_params(candidate.signature)
    if params is None:
        return None
    return tuple((jt.canonical(p.type) if p.type else "?", p.varargs) for p in params)


def _jvm_accepts(candidate: SymbolRecord, count: int | None, instance: bool) -> bool:
    if count is None:
        return True
    arity = jt.arity_range(jt.split_params(candidate.signature), instance_call=instance)
    if arity is None:
        return True
    low, high = arity
    return low <= count and (high is None or count <= high)


def _jvm_score(candidate: SymbolRecord, keys: list[str], ctx: _JvmContext, instance: bool) -> int | None:
    params = jt.split_params(candidate.signature)
    if params is None:
        return 0
    plist = list(params)
    if instance and plist and plist[0].is_this:
        plist = plist[1:]
    total = 0
    used_varargs = False
    ancestors = ctx.ancestors
    for index, key in enumerate(keys):
        if index < len(plist):
            param = plist[index]
        elif plist and plist[-1].varargs:
            param = plist[-1]
        else:
            return None
        if param.varargs:
            used_varargs = True
            element = param.type[:-2] if param.type.endswith("[]") else param.type
            score = jt.arg_type_score(key, element, ancestors=ancestors, repo_types=ctx.is_type)
            if index == len(plist) - 1 and len(keys) == len(plist):
                score = max(score, jt.arg_type_score(key, param.type, ancestors=ancestors, repo_types=ctx.is_type))
        else:
            score = jt.arg_type_score(key, param.type, ancestors=ancestors, repo_types=ctx.is_type)
        total += score
    return total - (1 if used_varargs else 0)


def _jvm_declaring_type(member: SymbolRecord) -> tuple[str, str]:
    """(qualified owner, package directory for Java) - two members with the same owner name and package are members of the
    same type (C# partial classes share the owner name across files)."""
    owner = member.qualified_name.rsplit(".", 1)[0] if "." in member.qualified_name else ""
    return owner, member.path.rsplit("/", 1)[0] if member.path.endswith(".java") else ""


def _jvm_pick(
    levels: list[list[SymbolRecord]],
    count: int | None,
    arg_types: str | None,
    ctx: _JvmContext,
    *,
    instance: bool = True,
    narrow: Callable[[list[SymbolRecord]], list[SymbolRecord]] | None = None,
    avoid: str | None = None,
    home: set[str] | None = None,
) -> tuple[SymbolRecord, str] | None:
    """The overload a call binds to, as (symbol, how) with ``how`` in single / arity / types / group; ``None`` when
    members of *different* types that share a simple name cannot be told apart.

    ``levels`` are the members found per type, nearest type first.  An override (same parameter types further up the
    hierarchy) is the same method, so the nearest declaration wins.  Then: the call's argument count, then the
    argument types, finally the first declared overload (``group``).  ``avoid`` is the calling method: when nothing
    decides between the overloads, a call is taken to delegate to a *sibling* overload rather than to recurse (the
    ``f(String)`` -> ``f(Evaluator)`` idiom), which is the only case where the caller is skipped.
    """
    unique: dict[tuple, tuple[int, SymbolRecord]] = {}
    for depth, members in enumerate(levels):
        if len({_jvm_declaring_type(m) for m in members}) > 1:
            if home:
                # same-named types (``Token.Tag`` / ``Tag``): the one declared next to the receiver's own type is the
                # one it extends - a nested class names its siblings first (JLS 6.4.1)
                at_home = [m for m in members if m.path in home]
                if at_home:
                    members = at_home
            if len({_jvm_declaring_type(m) for m in members}) > 1 and narrow is not None:
                members = narrow(members) or members
            if len({_jvm_declaring_type(m) for m in members}) > 1:
                return None  # several types of the same name declare it: cannot say which one is meant
        for member in sorted(members, key=lambda m: m.start_line):
            key = _jvm_param_key(member) or ("#", member.symbol_id)
            if key not in unique:
                unique[key] = (depth, member)
    pool = sorted(unique.values(), key=lambda item: (item[0], item[1].start_line))
    if not pool:
        return None
    if len(pool) == 1:
        return pool[0][1], "single"
    accepted = [item for item in pool if _jvm_accepts(item[1], count, instance)]
    if len(accepted) == 1 and count is not None:
        return accepted[0][1], "arity"
    if accepted:
        pool = accepted
    keys = arg_types.split(",") if arg_types else None
    if keys and count is not None and len(keys) == count:
        scored = [(_jvm_score(item[1], keys, ctx, instance), item) for item in pool]
        scored = [(score, item) for score, item in scored if score is not None]
        if scored:
            best = max(score for score, _ in scored)
            winners = [item for score, item in scored if score == best]
            if len(winners) == 1 and best >= 0:
                return winners[0][1], "types"
            if best >= 0:
                pool = winners
    if avoid is not None and len(pool) > 1:
        siblings = [item for item in pool if item[1].symbol_id != avoid]
        if siblings:
            pool = siblings
    best_item = min(pool, key=lambda item: (item[0], item[1].start_line))
    return best_item[1], "group"


_JVM_HOW_SCOPE = {"arity": "overload_arity", "types": "overload_types", "group": "overload_group"}


def _jvm_result(
    levels: list[list[SymbolRecord]],
    own_scope: str | Callable[[SymbolRecord], str],
    owner: str | None,
    count: int | None,
    arg_types: str | None,
    ctx: _JvmContext,
    *,
    instance: bool = True,
    narrow: Callable[[list[SymbolRecord]], list[SymbolRecord]] | None = None,
    avoid: str | None = None,
    home_of: str | None = None,
) -> tuple[SymbolRecord | None, str, float]:
    """Resolution outcome for the members ``levels`` of a receiver type (``owner``; ``None`` = inherited-only lookup);
    ``home_of`` names the receiver's own type (the hierarchy is walked from it)."""
    picked = _jvm_pick(levels, count, arg_types, ctx, instance=instance, narrow=narrow, avoid=avoid, home=ctx.home_paths(home_of))
    base = own_scope if isinstance(own_scope, str) else "member"
    if picked is None:
        return None, f"{base}_ambiguous", 0.10
    symbol, how = picked
    if how == "single":
        if owner is not None and _jvm_is_member(symbol, owner):
            scope = own_scope(symbol) if callable(own_scope) else own_scope
        else:
            scope = "cha_inherited"
    else:
        scope = _JVM_HOW_SCOPE[how]
    return symbol, scope, SCOPE_CONFIDENCE.get(scope, 0.85)


def _jvm_extension(
    candidates: list[SymbolRecord],
    receiver_type: str,
    count: int | None,
    arg_types: str | None,
    ctx: _JvmContext,
) -> tuple[SymbolRecord | None, str, float] | None:
    """C# extension method (``static R M(this T receiver, ...)``) applicable to a receiver of a known type."""
    found: list[SymbolRecord] = []
    receiver_ancestors = set(ctx.ancestors(receiver_type))
    for c in candidates:
        if c.kind not in _JVM_CALLABLE_KINDS:
            continue
        params = jt.split_params(c.signature)
        if not params or not params[0].is_this:
            continue
        first = params[0].type
        compatible = (
            first == receiver_type
            or first in receiver_ancestors
            or jt.canonical(first) == "object"
            or (ctx.is_type(receiver_type) and jt.is_type_parameter(first))
        )
        if compatible and _jvm_accepts(c, count, True):
            found.append(c)
    if not found:
        return None
    picked = _jvm_pick([found], count, arg_types, ctx, instance=True)
    if picked is None:
        return None, "extension_method_ambiguous", 0.10
    symbol, how = picked
    scope = "extension_method" if how == "single" else _JVM_HOW_SCOPE[how]
    return symbol, scope, SCOPE_CONFIDENCE.get(scope, 0.75)


def _resolve_jvm_member(
    source: SymbolRecord,
    candidates: list[SymbolRecord],
    *,
    receiver: str | None,
    receiver_type: str | None,
    receiver_type_source: str | None,
    count: int | None,
    arg_types: str | None,
    ctx: _JvmContext,
    narrow: Callable[[list[SymbolRecord]], list[SymbolRecord]],
) -> tuple[SymbolRecord | None, str, float] | None:
    """Typed member resolution for an invocation in Java/C# code; ``None`` = not decidable here (the generic
    resolution - imports, namespaces, free functions - takes over)."""
    prefixes = _enclosing_prefixes(source)
    rec = (receiver or "").strip()

    if rec in {"super", "base"}:
        if not prefixes:
            return None
        levels = _jvm_levels(candidates, prefixes[0], ctx, ancestors_only=True)
        if not levels:
            return None
        return _jvm_result(levels, "cha_inherited", None, count, arg_types, ctx, narrow=narrow, avoid=source.symbol_id, home_of=prefixes[0])

    if rec == "this":
        if not prefixes:
            return None
        levels = _jvm_levels(candidates, prefixes[0], ctx)
        if not levels:
            return None
        return _jvm_result(levels, "same_class", prefixes[0], count, arg_types, ctx, narrow=narrow, avoid=source.symbol_id, home_of=prefixes[0])

    if receiver_type:
        if receiver_type_source == "field_type":
            own = "field_type"
        elif receiver_type_source == "chain_type":
            own = "chain_type"
        elif rec.startswith("this."):
            own = "attr_type"
        else:
            own = "exact_receiver_type"
        if _jvm_is_library_nested(receiver_type, source, ctx):
            return None, "external_receiver_type", 0.10
        simple = receiver_type.rsplit(".", 1)[-1]
        owner_type = _jvm_norm_type(receiver_type, ctx)
        levels = _jvm_levels(candidates, owner_type, ctx)
        if not levels and owner_type != simple:
            owner_type = simple  # ``Outer.Inner`` where Inner is inherited into Outer: look it up by its own name
            levels = _jvm_levels(candidates, owner_type, ctx)
        if levels:
            return _jvm_result(levels, own, owner_type, count, arg_types, ctx, narrow=narrow, avoid=source.symbol_id, home_of=owner_type)
        extension = _jvm_extension(candidates, simple, count, arg_types, ctx)
        if extension is not None:
            return extension
        # the receiver's type is known and declares no such member: guessing from the variable's *name* (the
        # heuristic of the dynamic languages) would only invent edges
        return None, "type_member_unmatched" if ctx.is_type(simple) else "external_receiver_type", 0.10

    if not rec:
        for prefix in prefixes:
            levels = _jvm_levels(candidates, prefix, ctx)
            if levels:
                return _jvm_result(
                    levels,
                    lambda symbol: "implicit_this_partial" if symbol.path != source.path and not any(
                        m.path == source.path for m in levels[0]
                    ) else "implicit_this",
                    prefix,
                    count,
                    arg_types,
                    ctx,
                    narrow=narrow,
                    avoid=source.symbol_id,
                    home_of=prefix,
                )
        return None

    if re.fullmatch(r"[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*", rec):
        last = rec.rsplit(".", 1)[-1]
        if ctx.is_type(last):
            for owner in ([rec] if "." in rec else []) + [last]:
                levels = _jvm_levels(candidates, owner, ctx)
                if levels:
                    return _jvm_result(levels, "receiver_match", owner, count, arg_types, ctx, instance=False, narrow=narrow, avoid=source.symbol_id, home_of=owner)
    return None


def _jvm_eval_chain(chain: str, source: SymbolRecord, ctx: _JvmContext) -> str | None:
    """Type (simple name) the receiver expression described by ``chain`` evaluates to, or ``None``.

    Roots: ``T:Type`` (known), ``S:Name`` (a repository type referenced statically), ``this`` (the enclosing classes,
    innermost first), ``super``.  Steps: ``m:name/argc`` (declared return type of the method) and ``f:name`` (declared
    type of a C# property).  Overloads that agree on the return type are fine; disagreement fails the chain."""
    prefixes = _enclosing_prefixes(source)
    cache_key = (chain, prefixes[0] if prefixes else "", "")
    if cache_key in ctx._chains:
        return ctx._chains[cache_key]
    result = _jvm_eval_chain_uncached(chain, prefixes, ctx)
    ctx._chains[cache_key] = result
    return result


def _jvm_eval_chain_uncached(chain: str, prefixes: list[str], ctx: _JvmContext) -> str | None:
    parts = chain.split("|")
    root = parts[0]
    specs: list[tuple[str, bool]] | None = None
    current: str | None = None
    if root.startswith("T:"):
        current = _jvm_norm_type(root[2:], ctx)
    elif root.startswith("S:"):
        current = root[2:] if ctx.is_type(root[2:]) else None
    elif root == "this":
        specs = [(prefix, False) for prefix in prefixes]
    elif root == "super" and prefixes:
        specs = [(prefixes[0], True)]
    if current is None and specs is None:
        return None
    for step in parts[1:]:
        kind, _, rest = step.partition(":")
        owners = specs if specs is not None else [(current or "", False)]
        specs = None
        if kind == "m":
            name, _, argc = rest.rpartition("/")
            pool = [c for c in ctx.by_name.get(name, ()) if c.kind in _JVM_CALLABLE_KINDS]
            count = int(argc) if argc.isdigit() else None
        elif kind == "f":
            name, count = rest, None
            pool = [c for c in ctx.by_name.get(name, ()) if c.kind == "property"]
        else:
            return None
        if not pool:
            return None
        levels: list[list[SymbolRecord]] = []
        for owner, ancestors_only in owners:
            levels = _jvm_levels(pool, owner, ctx, ancestors_only=ancestors_only)
            if levels:
                break
        if not levels:
            return None
        members = levels[0]
        if kind == "m":
            fitting = [m for m in members if _jvm_accepts(m, count, True)]
            members = fitting or members
            types = {jt.clean_type(jt.return_type(m.signature, m.name)) for m in members}
        else:
            types = {jt.clean_type(jt.property_type(m.signature, m.name)) for m in members}
        types.discard("")
        if len(types) != 1:
            return None
        found = next(iter(types))
        if found in _JVM_PRIMITIVE_LIKE or jt.is_type_parameter(found):
            return None
        current = found
    return current


def build_lexical_edges(
    symbols: list[SymbolRecord],
    source_by_path: dict[str, str],
    *,
    max_edges_per_symbol: int = 100,
    calls_by_path: dict[str, list[CallRecord]] | None = None,
    imports_by_path: dict[str, list[str]] | None = None,
    class_hierarchy: dict[str, list[str]] | None = None,
    external_stubs: list[ExternalStubRecord] | None = None,
    file_namespaces: dict[str, list[str]] | None = None,
    js_module_bindings: dict[str, dict[str, str]] | None = None,
) -> list[EdgeRecord]:
    by_name: dict[str, list[SymbolRecord]] = defaultdict(list)
    symbols_by_path: dict[str, list[SymbolRecord]] = defaultdict(list)
    for symbol in symbols:
        by_name[symbol.name].append(symbol)
        symbols_by_path[symbol.path].append(symbol)

    stubs_by_member: dict[str, list[ExternalStubRecord]] = defaultdict(list)
    if external_stubs:
        for stub in external_stubs:
            stubs_by_member[stub.member_name].append(stub)

    edges: list[EdgeRecord] = []
    imports_map = imports_by_path or {}
    repo_return_types = _extract_repo_return_types(symbols)
    jvm_ctx: _JvmContext | None = None

    if calls_by_path is not None:
        # Use AST-extracted calls for precise edge resolution
        for path, calls in calls_by_path.items():
            path_symbols = symbols_by_path.get(path, [])
            if not path_symbols:
                continue

            sorted_symbols = sorted(path_symbols, key=lambda s: (s.start_byte, -s.end_byte))
            file_work = 0
            file_timed_out = False

            for call in calls:
                enclosing = [
                    s for s in sorted_symbols
                    if s.start_byte <= call.start_byte <= s.end_byte
                ]
                if not enclosing:
                    continue
                source = min(enclosing, key=lambda s: s.end_byte - s.start_byte)

                # deterministic per-file work budget (see FILE_EDGE_WORK_BUDGET)
                file_work += len(sorted_symbols)
                if not file_timed_out and file_work > FILE_EDGE_WORK_BUDGET:
                    file_timed_out = True

                if file_timed_out:
                    edges.append(
                        EdgeRecord(
                            source_symbol_id=source.symbol_id,
                            target_symbol_id=None,
                            target_name=call.name,
                            edge_kind="call",
                            status="ambiguous",
                            backend="lexical",
                            confidence=0.10,
                            source_path=source.path,
                            source_line=call.line,
                            evidence=["ast_call", "edge_work_budget"],
                        )
                    )
                    continue

                file_mod_bindings = js_module_bindings.get(source.path) if js_module_bindings else None
                jvm_call = _is_jvm_source(source)
                if jvm_call:
                    # M13: Java/C# keep the caller among the candidates: ``f(int)`` calling ``f(String)`` must not
                    # be mistaken for a call to ``f(int)`` itself (the edge to oneself is dropped below)
                    candidates = list(by_name.get(call.name, []))
                    if len(candidates) == 1 and candidates[0].symbol_id == source.symbol_id:
                        continue
                    if jvm_ctx is None:
                        jvm_ctx = _JvmContext(symbols, by_name, class_hierarchy)
                else:
                    candidates = [c for c in by_name.get(call.name, []) if c.symbol_id != source.symbol_id]
                if not candidates and file_mod_bindings and call.name in file_mod_bindings:
                    bound_target = file_mod_bindings[call.name]
                    if "." in bound_target and (bound_target.startswith(".") or "/" in bound_target):
                        _, orig_name = bound_target.rsplit(".", 1)
                        candidates = [c for c in by_name.get(orig_name, []) if c.symbol_id != source.symbol_id]

                file_work += WORK_PER_CANDIDATE * len(candidates)
                effective_receiver_type = getattr(call, "receiver_type", None)
                effective_type_source = getattr(call, "receiver_type_source", None)
                if effective_receiver_type is None and getattr(call, "assigned_from_fn", None):
                    fn_src = call.assigned_from_fn
                    if fn_src and repo_return_types.get(fn_src):
                        effective_receiver_type = repo_return_types[fn_src]
                if jvm_call and effective_receiver_type is None and getattr(call, "chain", None):
                    chain_type = _jvm_eval_chain(call.chain, source, jvm_ctx) if jvm_ctx is not None else None
                    if chain_type:
                        effective_receiver_type = chain_type
                        effective_type_source = "chain_type"

                # Virtual External Stub Resolution
                matched_stub = None
                if external_stubs and call.name in stubs_by_member:
                    matched_stub = _resolve_external_stub(
                        source=source,
                        name=call.name,
                        receiver=call.receiver,
                        receiver_type=effective_receiver_type,
                        imports=imports_map.get(path, []),
                        stubs=stubs_by_member[call.name],
                        class_hierarchy=class_hierarchy,
                    )

                if matched_stub:
                    evidence = ["ast_call", "virtual_stub", f"stub:{matched_stub.package}.{matched_stub.export_path}.{matched_stub.member_name}"]
                    if call.receiver:
                        evidence.append(f"receiver:{call.receiver}")
                    if effective_receiver_type:
                        evidence.append(f"type:{effective_receiver_type}")
                    edges.append(
                        EdgeRecord(
                            source_symbol_id=source.symbol_id,
                            target_symbol_id=None,
                            target_stub_id=matched_stub.stub_id,
                            target_name=call.name,
                            edge_kind="call",
                            status="resolved",
                            backend="virtual_stub",
                            confidence=SCOPE_CONFIDENCE.get("virtual_stub", 0.90),
                            source_path=source.path,
                            source_line=call.line,
                            evidence=evidence,
                        )
                    )
                    continue

                if not candidates:
                    continue

                target, scope, confidence = _resolve_candidate(
                    source,
                    candidates,
                    receiver=call.receiver,
                    receiver_type=effective_receiver_type,
                    receiver_type_source=effective_type_source,
                    is_tainted=getattr(call, "is_tainted", False),
                    imports=imports_map.get(path, []),
                    class_hierarchy=class_hierarchy,
                    call_arg_count=getattr(call, "arg_count", None),
                    file_namespaces=file_namespaces,
                    module_bindings=file_mod_bindings,
                    call_name=call.name,
                    arg_types=getattr(call, "arg_types", None),
                    call_kind=getattr(call, "call_kind", None),
                    jvm=jvm_ctx if jvm_call else None,
                )
                if jvm_call and target is not None and target.symbol_id == source.symbol_id:
                    continue  # a recursive call is not an edge (the baseline never recorded one either)
                status = "resolved" if target else "ambiguous"
                evidence = ["ast_call", f"scope:{scope}"]
                if call.receiver:
                    evidence.append(f"receiver:{call.receiver}")
                if effective_receiver_type:
                    evidence.append(f"type:{effective_receiver_type}")
                if getattr(call, "is_tainted", False):
                    evidence.append("tainted_poly_receiver")


                edges.append(
                    EdgeRecord(
                        source_symbol_id=source.symbol_id,
                        target_symbol_id=target.symbol_id if target else None,
                        target_name=call.name,
                        edge_kind="call",
                        status=status,
                        backend="lexical",
                        confidence=confidence,
                        source_path=source.path,
                        source_line=call.line,
                        evidence=evidence,
                    )
                )
        return _deduplicate(edges)

    # Fallback to regex identifier scanning (backward compatibility)
    for source in symbols:
        source_text = source_by_path.get(source.path, "")
        body = _slice_by_byte(source_text, source.start_byte, source.end_byte)
        count = 0
        for match in _IDENTIFIER_RE.finditer(body):
            if count >= max_edges_per_symbol:
                break
            name = match.group(0)
            candidates = [candidate for candidate in by_name.get(name, []) if candidate.symbol_id != source.symbol_id]
            if not candidates:
                continue
            line = source.start_line + body[: match.start()].count("\n")
            target, scope, confidence = _resolve_candidate(
                source,
                candidates,
                receiver=None,
                imports=imports_map.get(source.path, []),
                class_hierarchy=class_hierarchy,
            )
            status = "resolved" if target else "ambiguous"
            edge_kind = "call" if body[match.end() :].lstrip().startswith("(") else "reference"
            evidence = ["identifier_match", f"scope:{scope}"]
            edges.append(
                EdgeRecord(
                    source_symbol_id=source.symbol_id,
                    target_symbol_id=target.symbol_id if target else None,
                    target_name=name,
                    edge_kind=edge_kind,
                    status=status,
                    backend="lexical",
                    confidence=confidence,
                    source_path=source.path,
                    source_line=line,
                    evidence=evidence,
                )
            )
            count += 1
    return _deduplicate(edges)


_BUILTIN_RECEIVERS = {
    "os", "sys", "re", "json", "time", "math", "uuid", "shutil", "pathlib", "logging",
    "logger", "log", "tomllib", "hashlib", "sqlite3", "pathspec", "pytest", "io",
    "dict", "list", "set", "tuple", "str", "bytes", "bytearray",
    "raw", "os.environ", "payload", "manifest", "usage", "agent", "topic",
    "i", "d", "data", "resp", "response", "params", "args", "kwargs", "settings",
}

_GENERIC_METHOD_NAMES = {
    "get", "set", "run", "close", "save", "load", "update", "read", "write",
    "execute", "process", "format", "render", "parse", "connect", "handle",
    "start", "stop", "reset", "clear", "build", "create", "delete", "send",
    "items", "keys", "values", "pop", "append", "extend", "strip", "split", "join",
    "search", "match", "sub", "findall", "finditer",
}


@lru_cache(maxsize=65536)
def _path_segments(path_str: str) -> list[str]:
    # cached (M7): called once per (import, candidate) pair, i.e. up to millions of times per index run;
    # the returned list is shared and must not be mutated by callers.
    p = path_str.replace("\\", "/")
    filename = p.rsplit("/", 1)[-1]
    if "." in filename:
        p = p[: -(len(filename) - filename.rfind("."))]
    return [s for s in p.split("/") if s]


@lru_cache(maxsize=16384)
def _import_parts(imp: str) -> tuple[str | None, list[str] | None, list[str]]:
    """(member name, module segments of ``a.b.Name``, segments of the whole import); shared, read-only."""
    member_part: str | None = None
    mod_segs: list[str] | None = None
    if "." in imp:
        mod_part, member_part = imp.rsplit(".", 1)
        mod_segs = [s for s in mod_part.replace(".", "/").split("/") if s]
    imp_segs = [s for s in imp.replace(".", "/").split("/") if s]
    return member_part, mod_segs, imp_segs


def _matches_js_module(source_path: str, target_mod: str, candidate_path: str) -> bool:
    """Normalize relative JS/TS module imports and match against candidate file (E8)."""
    s_path = source_path.replace("\\", "/")
    c_path = candidate_path.replace("\\", "/")
    if target_mod.startswith("."):
        source_dir = posixpath.dirname(s_path)
        norm_target = posixpath.normpath(posixpath.join(source_dir, target_mod))
        exts = [
            "", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
            "/index.js", "/index.mjs", "/index.cjs", "/index.ts", "/index.tsx"
        ]
        expected = {norm_target + ext for ext in exts}
        return c_path in expected
    else:
        cand_segs = c_path.split("/")
        return target_mod in cand_segs or c_path.startswith(target_mod)


def _import_matches_candidate(imp: str, candidate: SymbolRecord, source_path: str | None = None) -> bool:
    """Check if an import string accurately matches a candidate symbol's module or path."""
    if not imp:
        return False

    if source_path and imp.startswith("."):
        if _matches_js_module(source_path, imp, candidate.path):
            return True

    cand_segs = _path_segments(candidate.path)
    if not cand_segs:
        return False

    # 1. from a.b import CandidateName -> imp is "a.b.CandidateName"
    member_part, mod_segs, imp_segs = _import_parts(imp)
    if mod_segs is not None:
        if member_part == candidate.name:
            if len(cand_segs) >= len(mod_segs) and cand_segs[-len(mod_segs) :] == mod_segs:
                return True
    elif imp == candidate.name:
        return True

    # 2. Module import matches candidate file path exactly (as segment suffix)
    if not imp_segs:
        return False

    # Check exact segment suffix match
    if len(cand_segs) >= len(imp_segs) and cand_segs[-len(imp_segs) :] == imp_segs:
        return True

    # Check package __init__
    if cand_segs[-1] == "__init__":
        pkg_segs = cand_segs[:-1]
        if len(pkg_segs) >= len(imp_segs) and pkg_segs[-len(imp_segs) :] == imp_segs:
            return True

    return False


def _resolve_candidate(
    source: SymbolRecord,
    candidates: list[SymbolRecord],
    receiver: str | None = None,
    receiver_type: str | None = None,
    receiver_type_source: str | None = None,
    is_tainted: bool = False,
    imports: list[str] | None = None,
    class_hierarchy: dict[str, list[str]] | None = None,
    call_arg_count: int | None = None,
    file_namespaces: dict[str, list[str]] | None = None,
    module_bindings: dict[str, str] | None = None,
    call_name: str | None = None,
    arg_types: str | None = None,
    call_kind: str | None = None,
    jvm: _JvmContext | None = None,
) -> tuple[SymbolRecord | None, str, float]:
    imports_list = imports or []

    is_jvm = _is_jvm_source(source)
    if is_jvm and jvm is None:
        jvm = _JvmContext(list(candidates), {}, class_hierarchy)

    def is_member(c: SymbolRecord, owner: str) -> bool:
        """``c`` is declared in ``owner``.  Java/C#: directly (a nested type's member is not a member of the outer
        type); the dynamic languages keep the historical three-way match."""
        if is_jvm:
            return _jvm_is_member(c, owner)
        return (
            c.qualified_name == f"{owner}.{c.name}"
            or c.qualified_name.startswith(f"{owner}.")
            or c.qualified_name.endswith(f".{owner}.{c.name}")
        )

    def in_class(c: SymbolRecord, class_prefix: str) -> bool:
        if is_jvm:
            return c.qualified_name == f"{class_prefix}.{c.name}"
        return c.qualified_name.startswith(f"{class_prefix}.")

    def pick(group: list[SymbolRecord], *, instance: bool = True) -> tuple[SymbolRecord | None, str, float] | None:
        """Overload choice among ``group`` (``None`` = cannot choose)."""
        if not is_jvm:
            return _try_resolve_overload(group, source, call_arg_count)
        if not group or len({c.qualified_name for c in group}) != 1 or jvm is None:
            return None
        picked = _jvm_pick([group], call_arg_count, arg_types, jvm, instance=instance, narrow=narrow, avoid=source.symbol_id)
        if picked is None:
            return None
        symbol, how = picked
        scope = _JVM_HOW_SCOPE.get(how, "overload_group")
        return symbol, scope, SCOPE_CONFIDENCE[scope]

    is_csharp = source.symbol_id.startswith("c_sharp:") or source.path.endswith(".cs")
    src_ancestors: set[str] = set()
    using_namespaces: set[str] = set()
    if is_csharp and file_namespaces:
        for ns in file_namespaces.get(source.path, []):
            src_ancestors.update(_namespace_ancestors(ns))
        using_namespaces = set(imports_list)

    def narrow(group: list[SymbolRecord]) -> list[SymbolRecord]:
        """Members of several same-named types: keep those of the type the caller can see (same file, same package,
        imported, same / used C# namespace)."""
        in_file = [c for c in group if c.path == source.path]
        if in_file:
            return in_file
        source_package = _java_package(source.path, file_namespaces)
        if source_package:  # Java: the package, not the directory (``src/main`` and ``src/test`` share packages)
            in_dir = [c for c in group if _java_package(c.path, file_namespaces) == source_package]
        else:
            directory = source.path.rsplit("/", 1)[0]
            in_dir = [c for c in group if c.path.rsplit("/", 1)[0] == directory]
        if in_dir:
            return in_dir
        if imports_list:
            imported = [
                c for c in group
                if any(_import_matches_candidate(imp, c, source.path) or _java_wildcard_match(imp, c, file_namespaces) for imp in imports_list)
            ]
            if imported:
                return imported
        if is_csharp and file_namespaces:
            same_ns = [c for c in group if any(ns in src_ancestors for ns in file_namespaces.get(c.path, []))]
            if same_ns:
                return same_ns
            used_ns = [c for c in group if any(ns in using_namespaces for ns in file_namespaces.get(c.path, []))]
            if used_ns:
                return used_ns
        return group

    # E6: Prefer class/struct/interface symbols over constructor symbols
    type_kinds = {"class", "struct", "interface", "record"} if is_jvm else {"class", "struct", "interface"}
    if any(c.kind in type_kinds for c in candidates):
        candidates = [c for c in candidates if c.kind != "constructor"]

    typed_pool = candidates
    if is_jvm and call_kind == "new":
        # an instantiation binds to a type (or its constructors), never to a method / property of the same name
        instantiable = [c for c in candidates if c.kind in _JVM_TYPE_KINDS or c.kind == "constructor"]
        if instantiable:
            candidates = typed_pool = instantiable
    elif is_jvm:
        # an invocation binds to a method, never to a class / enum that merely shares the name; a C# property of a
        # delegate type (``Func<T, bool> CanResolve { get; }``) is invoked like a method, so typed lookup keeps those
        typed_pool = [c for c in candidates if c.kind in _JVM_CALLABLE_KINDS or c.kind == "property"] or candidates
        invocable = [c for c in candidates if c.kind in _JVM_CALLABLE_KINDS]
        if invocable:
            candidates = invocable

    # Defensive Heuristic: Tainted variable (reassigned >= 2 times or assigned in branch)
    if is_tainted:
        return None, "tainted_poly_receiver", 0.10

    # M13: typed member resolution for Java/C# invocations (before the name-based "builtin receiver" skip below:
    # ``data.foo()`` on a variable of a repository type named ``data`` is not a call on a standard-library object)
    if is_jvm and jvm is not None and call_kind != "new":
        typed = _resolve_jvm_member(
            source,
            typed_pool,
            receiver=receiver,
            receiver_type=receiver_type,
            receiver_type_source=receiver_type_source,
            count=call_arg_count,
            arg_types=arg_types,
            ctx=jvm,
            narrow=narrow,
        )
        if typed is not None:
            return typed

    # Fast skip for known built-in / standard library receivers when calling generic methods
    if receiver:
        rec_clean = receiver.strip()
        if rec_clean in _BUILTIN_RECEIVERS or (receiver_type and receiver_type in _BUILTIN_RECEIVERS):
            # Check if this receiver is an explicitly imported internal module
            has_internal_import = any(_import_matches_candidate(imp, c, source.path) for imp in imports_list for c in candidates if c.path != source.path)
            if not has_internal_import and module_bindings and rec_clean in module_bindings:
                target_mod = module_bindings[rec_clean]
                if "." in target_mod and not target_mod.startswith("."):
                    target_mod = target_mod.split(".")[0]
                has_internal_import = any(_matches_js_module(source.path, target_mod, c.path) for c in candidates if c.path != source.path)
            if not has_internal_import:
                return None, "builtin_receiver_skipped", 0.10

    # 1. Receiver is self / this / cls -> resolve within class if possible
    if receiver in {"self", "this", "cls"}:
        if "." in source.qualified_name:
            class_prefix = source.qualified_name.rsplit(".", 1)[0]
            same_class = [
                c for c in candidates
                if c.path == source.path and in_class(c, class_prefix)
            ]
            if len(same_class) == 1:
                return same_class[0], "same_class", SCOPE_CONFIDENCE.get("same_class", 0.95)
            if len(same_class) > 1:
                ov = pick(same_class)
                if ov is not None:
                    return ov
                return None, "same_class_ambiguous", 0.10

            # Class Hierarchy Analysis (CHA) lookup for inherited method
            if class_hierarchy:
                ancestors = _get_ancestors(class_prefix, class_hierarchy)
                for ancestor in ancestors:
                    ancestor_matches = [
                        c for c in candidates
                        if is_member(c, ancestor)
                    ]
                    if len(ancestor_matches) == 1:
                        return ancestor_matches[0], "cha_inherited", SCOPE_CONFIDENCE.get("cha_inherited", 0.90)
                    if len(ancestor_matches) > 1:
                        ov = pick(ancestor_matches)
                        if ov is not None:
                            return ov
                        return None, "cha_ambiguous", 0.10

            # Receiver this Cross-File Resolution (M12.1.3):
            # In JS/TS, methods of class X can be split across multiple files.
            # Add a fallback query for candidates matching c.qualified_name.startswith(f"{class_prefix}.")
            # across all files, labeled with scope same_class_split and confidence 0.85.
            # Guard with is_js_ts check so Python is never touched.
            if source.symbol_id.startswith(("javascript:", "typescript:", "tsx:")) or source.path.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")):
                split_class = [
                    c for c in candidates
                    if c.qualified_name.startswith(f"{class_prefix}.")
                ]
                if len(split_class) == 1:
                    return split_class[0], "same_class_split", SCOPE_CONFIDENCE.get("same_class_split", 0.85)
                if len(split_class) > 1:
                    ov = pick(split_class)
                    if ov is not None:
                        return ov
                    return None, "same_class_split_ambiguous", 0.10

        # Fallback to same file
        same_file = [c for c in candidates if c.path == source.path]
        if len(same_file) == 1:
            return same_file[0], "same_file", SCOPE_CONFIDENCE.get("same_file", 0.85)
        if len(same_file) > 1:
            ov = pick(same_file)
            if ov is not None:
                return ov
            return None, "same_file_ambiguous", 0.10

    # 1b. Receiver is an instance attribute (self.x, this.x, cls.x)
    if receiver and any(receiver.startswith(prefix) for prefix in ("self.", "this.", "cls.")):
        if receiver_type and receiver_type not in _BUILTIN_RECEIVERS:
            # M6.0: an attribute type inferred from a typed constructor/method parameter
            # (self.x = <typed param>) is tracked under its own scope so its precision can
            # be calibrated independently of the pre-existing attr_type sources
            # (annotated assignment / constructor call).
            attr_scope = "attr_param" if receiver_type_source == "attr_param" else "attr_type"
            type_matches = [
                c for c in candidates
                if is_member(c, receiver_type)
            ]
            if len(type_matches) == 1:
                return type_matches[0], attr_scope, SCOPE_CONFIDENCE.get(attr_scope, 0.90)
            if len(type_matches) > 1:
                same_file_type = [c for c in type_matches if c.path == source.path]
                if len(same_file_type) == 1:
                    return same_file_type[0], attr_scope, SCOPE_CONFIDENCE.get(attr_scope, 0.90)
                ov = pick(same_file_type or type_matches)
                if ov is not None:
                    return ov
                return None, "attr_type_ambiguous", 0.10

            # Try CHA on receiver_type
            if class_hierarchy:
                ancestors = _get_ancestors(receiver_type, class_hierarchy)
                for ancestor in ancestors:
                    ancestor_matches = [
                        c for c in candidates
                        if is_member(c, ancestor)
                    ]
                    if len(ancestor_matches) == 1:
                        return ancestor_matches[0], "attr_type_inherited", SCOPE_CONFIDENCE.get("attr_type_inherited", 0.90)
            return None, "attr_type_unmatched", 0.10

        # Receiver was an instance attribute but receiver_type could not be resolved:
        # DO NOT fall back to global or generic methods!
        return None, "unresolved_receiver", 0.10

    # 2. Inferred receiver type from parameter type hint, single-assignment, or class field
    if receiver_type and receiver_type not in _BUILTIN_RECEIVERS:
        rec_scope = "field_type" if receiver_type_source == "field_type" else "exact_receiver_type"
        type_matches = [
            c for c in candidates
            if is_member(c, receiver_type)
        ]
        if len(type_matches) == 1:
            return type_matches[0], rec_scope, SCOPE_CONFIDENCE.get(rec_scope, 0.90)
        if len(type_matches) > 1:
            same_file_type = [c for c in type_matches if c.path == source.path]
            if len(same_file_type) == 1:
                return same_file_type[0], rec_scope, SCOPE_CONFIDENCE.get(rec_scope, 0.90)
            ov = pick(same_file_type or type_matches)
            if ov is not None:
                return ov[0], rec_scope, SCOPE_CONFIDENCE.get(rec_scope, 0.85)
            return None, f"{rec_scope}_ambiguous", 0.10

        # Try CHA on receiver_type
        if class_hierarchy:
            ancestors = _get_ancestors(receiver_type, class_hierarchy)
            for ancestor in ancestors:
                ancestor_matches = [
                    c for c in candidates
                    if is_member(c, ancestor)
                ]
                if len(ancestor_matches) == 1:
                    return ancestor_matches[0], "cha_inherited", SCOPE_CONFIDENCE.get("cha_inherited", 0.90)

    # 3. Receiver is an explicit identifier (not self/cls/this)
    if receiver and receiver not in {"self", "this", "cls"}:
        # Match static class or module calls (e.g., Worker.build)
        receiver_matches = [
            c for c in candidates
            if is_member(c, receiver)
        ]
        if len(receiver_matches) == 1:
            return receiver_matches[0], "receiver_match", SCOPE_CONFIDENCE.get("receiver_match", 0.90)
        if len(receiver_matches) > 1:
            same_file_rec = [c for c in receiver_matches if c.path == source.path]
            if len(same_file_rec) == 1:
                return same_file_rec[0], "same_file", SCOPE_CONFIDENCE.get("same_file", 0.85)
            ov = pick(same_file_rec)
            if ov is not None:
                return ov
            if imports_list:
                import_rec = [
                    c for c in receiver_matches
                    if any(_import_matches_candidate(imp, c) for imp in imports_list)
                ]
                if len(import_rec) == 1:
                    return import_rec[0], "import_match", SCOPE_CONFIDENCE.get("import_match", 0.85)
                ov = pick(import_rec)
                if ov is not None:
                    return ov

            # E3: C# Namespace resolution for receiver matches
            if is_csharp and file_namespaces:
                same_ns_rec = [
                    c for c in receiver_matches
                    if any(c_ns in src_ancestors for c_ns in file_namespaces.get(c.path, []))
                ]
                if len(same_ns_rec) == 1:
                    return same_ns_rec[0], "same_namespace", SCOPE_CONFIDENCE.get("same_namespace", 0.80)
                if len(same_ns_rec) > 1:
                    ov = pick(same_ns_rec)
                    if ov is not None:
                        return ov[0], "same_namespace", SCOPE_CONFIDENCE.get("same_namespace", 0.80)

                ns_match_rec = [
                    c for c in receiver_matches
                    if any(c_ns in using_namespaces for c_ns in file_namespaces.get(c.path, []))
                ]
                if len(ns_match_rec) == 1:
                    return ns_match_rec[0], "namespace_match", SCOPE_CONFIDENCE.get("namespace_match", 0.80)
                if len(ns_match_rec) > 1:
                    ov = pick(ns_match_rec)
                    if ov is not None:
                        return ov[0], "namespace_match", SCOPE_CONFIDENCE.get("namespace_match", 0.80)

            ov = pick(receiver_matches)
            if ov is not None:
                return ov
            return None, "receiver_ambiguous", 0.10

        # Receiver might be an imported module name
        matched_imports = [imp for imp in imports_list if receiver in imp.split(".")]
        if matched_imports:
            imp_cands = [
                c for c in candidates
                if any(_import_matches_candidate(imp, c) for imp in matched_imports)
            ]
            if len(imp_cands) == 1:
                return imp_cands[0], "import_module_match", SCOPE_CONFIDENCE.get("import_module_match", 0.75)
            if len(imp_cands) > 1:
                ov = pick(imp_cands)
                if ov is not None:
                    return ov
                return None, "import_module_ambiguous", 0.10

        # In C#, receiver might match candidate's namespace (e.g. MyNamespace.DataStore)
        if is_csharp and file_namespaces:
            ns_cands = [
                c for c in candidates
                if any(
                    c_ns == receiver
                    or c_ns.endswith(f".{receiver}")
                    or receiver == c_ns.split(".")[-1]
                    or receiver in c_ns.split(".")
                    for c_ns in file_namespaces.get(c.path, [])
                )
            ]
            if len(ns_cands) == 1:
                return ns_cands[0], "namespace_match", SCOPE_CONFIDENCE.get("namespace_match", 0.80)
            if len(ns_cands) > 1:
                same_file_ns = [c for c in ns_cands if c.path == source.path]
                if len(same_file_ns) == 1:
                    return same_file_ns[0], "same_namespace", SCOPE_CONFIDENCE.get("same_namespace", 0.80)
                ov = pick(same_file_ns or ns_cands)
                if ov is not None:
                    return ov[0], "namespace_match", SCOPE_CONFIDENCE.get("namespace_match", 0.80)
                return None, "namespace_ambiguous", 0.10

        # E8: JS CommonJS require & ES6 import module match (e.g. const X = require('./x'); X.foo())
        if module_bindings and receiver in module_bindings:
            target_mod = module_bindings[receiver]
            if "." in target_mod and not target_mod.startswith("."):
                target_mod = target_mod.split(".")[0]
            mod_cands = [
                c for c in candidates
                if _matches_js_module(source.path, target_mod, c.path)
            ]
            if len(mod_cands) == 1:
                return mod_cands[0], "import_module_match", SCOPE_CONFIDENCE.get("import_module_match", 0.75)
            if len(mod_cands) > 1:
                same_file_mod = [c for c in mod_cands if c.path == source.path]
                if len(same_file_mod) == 1:
                    return same_file_mod[0], "same_file", SCOPE_CONFIDENCE.get("same_file", 0.85)
                ov = pick(mod_cands)
                if ov is not None:
                    return ov[0], "import_module_match", SCOPE_CONFIDENCE.get("import_module_match", 0.75)
                return None, "import_module_ambiguous", 0.10

        # Check if candidate is a method of an imported/same-file class and receiver name matches class name:
        # e.g., receiver="store" matches class="SQLiteStore" or "MemoryStore" (when imported)
        if imports_list or any(c.path == source.path for c in candidates):
            imported_class_matches = []
            for c in candidates:
                if "." in c.qualified_name:
                    cls_name = c.qualified_name.rsplit(".", 1)[0].rsplit(".", 1)[-1]
                    is_available = any(
                        imp == cls_name or imp.endswith(f".{cls_name}") or _import_matches_candidate(imp, c)
                        for imp in imports_list
                    ) or (c.path == source.path)
                    if is_available:
                        rec_clean = receiver.lower().replace("self.", "")
                        cls_clean = cls_name.lower()
                        # Match when variable name is a meaningful substring of class name
                        if rec_clean and (rec_clean in cls_clean or cls_clean in rec_clean):
                            if len(rec_clean) >= 3 and rec_clean not in _BUILTIN_RECEIVERS:
                                imported_class_matches.append(c)

            if len(imported_class_matches) == 1:
                return imported_class_matches[0], "exact_receiver_type", SCOPE_CONFIDENCE.get("exact_receiver_type", 0.85)
            if len(imported_class_matches) > 1:
                return None, "receiver_type_ambiguous", 0.10

        # Receiver was explicit but could not be matched:
        # DO NOT fall back to global search for a method on an unknown receiver!
        return None, "unresolved_receiver", 0.10

    # E1: Implicit this (C#, Java) for calls without receiver inside a class method
    if not receiver and (source.symbol_id.startswith(("c_sharp:", "java:")) or source.path.endswith((".cs", ".java"))):
        if "." in source.qualified_name:
            class_prefix = source.qualified_name.rsplit(".", 1)[0]
            # 1. Candidate C.name same path
            same_class = [
                c for c in candidates
                if c.path == source.path and in_class(c, class_prefix)
            ]
            if len(same_class) == 1:
                return same_class[0], "implicit_this", SCOPE_CONFIDENCE.get("implicit_this", 0.90)
            if len(same_class) > 1:
                ov = pick(same_class)
                if ov is not None:
                    return ov
                return None, "implicit_this_ambiguous", 0.10

            # 2. C.name in other files (partial class)
            same_class_partial = [
                c for c in candidates
                if c.path != source.path and in_class(c, class_prefix)
            ]
            if len(same_class_partial) == 1:
                return same_class_partial[0], "implicit_this_partial", SCOPE_CONFIDENCE.get("implicit_this_partial", 0.85)
            if len(same_class_partial) > 1:
                ov = pick(same_class_partial)
                if ov is not None:
                    return ov
                return None, "implicit_this_partial_ambiguous", 0.10

            # 3. CHA up to parent class
            if class_hierarchy:
                ancestors = _get_ancestors(class_prefix, class_hierarchy)
                for ancestor in ancestors:
                    ancestor_matches = [
                        c for c in candidates
                        if is_member(c, ancestor)
                    ]
                    if len(ancestor_matches) == 1:
                        return ancestor_matches[0], "cha_inherited", SCOPE_CONFIDENCE.get("cha_inherited", 0.90)
                    if len(ancestor_matches) > 1:
                        ov = pick(ancestor_matches)
                        if ov is not None:
                            return ov
                        return None, "cha_ambiguous", 0.10

    # 4. Direct candidate resolution: same_file -> imported -> same_package -> global
    # (Only for free function calls, direct identifier invocations without receiver)
    same_file = [candidate for candidate in candidates if candidate.path == source.path]
    if len(same_file) == 1:
        return same_file[0], "same_file", SCOPE_CONFIDENCE.get("same_file", 0.85)
    if len(same_file) > 1:
        ov = pick(same_file)
        if ov is not None:
            return ov
        return None, "same_file_ambiguous", 0.10

    if imports_list:
        imported_cands = [
            c for c in candidates
            if any(_import_matches_candidate(imp, c, source.path) for imp in imports_list)
            or (is_jvm and any(_java_wildcard_match(imp, c, file_namespaces) for imp in imports_list))
        ]
        if len(imported_cands) == 1:
            return imported_cands[0], "import_match", SCOPE_CONFIDENCE.get("import_match", 0.85)
        if len(imported_cands) > 1:
            ov = pick(imported_cands)
            if ov is not None:
                return ov
            return None, "import_ambiguous", 0.10

    # E8: JS/TS destructuring require & import match (e.g. const { a } = require('./x'); a())
    target_lookup_name = call_name or (candidates[0].name if candidates else None)
    if module_bindings and target_lookup_name and target_lookup_name in module_bindings:
        bound_target = module_bindings[target_lookup_name]
        if "." in bound_target and (bound_target.startswith(".") or "/" in bound_target):
            target_mod, orig_name = bound_target.rsplit(".", 1)
        else:
            target_mod, orig_name = bound_target, target_lookup_name
        mod_cands = [
            c for c in candidates
            if c.name == orig_name and _matches_js_module(source.path, target_mod, c.path)
        ]
        if len(mod_cands) == 1:
            return mod_cands[0], "import_match", SCOPE_CONFIDENCE.get("import_match", 0.90)
        if len(mod_cands) > 1:
            ov = pick(mod_cands)
            if ov is not None:
                return ov[0], "import_match", SCOPE_CONFIDENCE.get("import_match", 0.90)
            return None, "import_ambiguous", 0.10

    # E3: C# Namespace resolution for free calls
    if is_csharp and file_namespaces:
        same_ns_cands = [
            c for c in candidates
            if any(c_ns in src_ancestors for c_ns in file_namespaces.get(c.path, []))
        ]
        if len(same_ns_cands) == 1:
            return same_ns_cands[0], "same_namespace", SCOPE_CONFIDENCE.get("same_namespace", 0.80)
        if len(same_ns_cands) > 1:
            ov = pick(same_ns_cands)
            if ov is not None:
                return ov[0], "same_namespace", SCOPE_CONFIDENCE.get("same_namespace", 0.80)

        ns_match_cands = [
            c for c in candidates
            if any(c_ns in using_namespaces for c_ns in file_namespaces.get(c.path, []))
        ]
        if len(ns_match_cands) == 1:
            return ns_match_cands[0], "namespace_match", SCOPE_CONFIDENCE.get("namespace_match", 0.80)
        if len(ns_match_cands) > 1:
            ov = pick(ns_match_cands)
            if ov is not None:
                return ov[0], "namespace_match", SCOPE_CONFIDENCE.get("namespace_match", 0.80)

    source_package = source.path.rsplit("/", 1)[0]
    java_package = _java_package(source.path, file_namespaces)
    if java_package:
        same_package = [c for c in candidates if _java_package(c.path, file_namespaces) == java_package]
    else:
        same_package = [candidate for candidate in candidates if candidate.path.rsplit("/", 1)[0] == source_package]
    if len(same_package) == 1:
        if same_package[0].name not in _GENERIC_METHOD_NAMES:
            return same_package[0], "same_package", SCOPE_CONFIDENCE.get("same_package", 0.75)
    if len(same_package) > 1:
        ov = pick(same_package)
        if ov is not None:
            return ov
        return None, "same_package_ambiguous", 0.10

    # Restrict global fallback:
    # 1. Never fallback for generic method names (get, set, run, etc.)
    # 2. Never fallback for class methods (must be top-level function or class)
    if len(candidates) == 1:
        cand = candidates[0]
        if cand.name not in _GENERIC_METHOD_NAMES:
            is_class_method = ("." in cand.qualified_name) and (cand.kind in {"method", "function"})
            if not is_class_method:
                return cand, "global", SCOPE_CONFIDENCE.get("global", 0.40)
    if len(candidates) > 1:
        ov = pick(candidates)
        if ov is not None:
            return ov

    return None, "global_ambiguous", 0.10



def _slice_by_byte(text: str, start_byte: int, end_byte: int) -> str:
    raw = text.encode("utf-8")
    return raw[start_byte:end_byte].decode("utf-8", errors="replace")


def _deduplicate(edges: list[EdgeRecord]) -> list[EdgeRecord]:
    seen: set[tuple[str, str | None, int | None, str, str]] = set()
    unique: list[EdgeRecord] = []
    for edge in edges:
        key = (edge.source_symbol_id, edge.target_symbol_id, edge.target_stub_id, edge.target_name, edge.edge_kind)
        if key not in seen:
            seen.add(key)
            unique.append(edge)
    return unique


def _resolve_external_stub(
    source: SymbolRecord,
    name: str,
    receiver: str | None,
    receiver_type: str | None,
    imports: list[str],
    stubs: list[ExternalStubRecord],
    class_hierarchy: dict[str, list[str]] | None = None,
) -> ExternalStubRecord | None:
    if not stubs:
        return None

    # 1. Receiver matches package name or module name (e.g. requests.get, pytest.raises)
    if receiver and receiver not in {"self", "this", "cls"}:
        rec_matches = [
            s for s in stubs
            if s.package == receiver
            or s.export_path == receiver
            or f"{s.package}.{s.export_path}".startswith(f"{receiver}.")
        ]
        if len(rec_matches) == 1:
            return rec_matches[0]

    # 2. Receiver is self / this / cls (e.g. self.assertEqual in unittest.TestCase)
    if receiver in {"self", "this", "cls"}:
        if "." in source.qualified_name:
            class_prefix = source.qualified_name.rsplit(".", 1)[0]
            ancestors = [class_prefix]
            if class_hierarchy:
                ancestors.extend(_get_ancestors(class_prefix, class_hierarchy))

            for s in stubs:
                for anc in ancestors:
                    anc_short = anc.rsplit(".", 1)[-1]
                    if anc_short == s.export_path or anc == s.export_path:
                        return s
                    if s.package == "unittest" and ("TestCase" in anc_short or anc_short.startswith("Test")):
                        if any(imp.startswith("unittest") for imp in imports):
                            return s

    # 3. Receiver type matches export_path (e.g. model.model_dump where receiver_type is BaseModel or inherits BaseModel)
    if receiver_type:
        type_ancestors = [receiver_type]
        if class_hierarchy:
            type_ancestors.extend(_get_ancestors(receiver_type, class_hierarchy))
        for s in stubs:
            for t_anc in type_ancestors:
                t_short = t_anc.rsplit(".", 1)[-1]
                if t_short == s.export_path or t_anc == s.export_path:
                    return s

    # 4. Direct call without receiver, or receiver matches package (e.g. raises(...) from pytest)
    if receiver is None or receiver in {s.package for s in stubs}:
        imported_stubs = [
            s for s in stubs
            if any(
                imp == s.package
                or imp == f"{s.package}.{s.export_path}"
                or imp == f"{s.package}.{s.member_name}"
                or imp.endswith(f".{s.member_name}")
                for imp in imports
            )
        ]
        if len(imported_stubs) == 1:
            return imported_stubs[0]

    return None


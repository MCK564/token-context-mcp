"""Context packet (M6.2): a deterministic, budget-aware view of one symbol and its 1-hop neighbourhood.

``build_context_packet`` is a pure function: it performs no I/O and depends only on its
arguments, so the same inputs always produce the same JSON byte for byte.  The service side
(``RetrievalService.packet_inputs``) gathers the raw material; the composite workflow
(``inspect_symbol(view="full")``) wraps the packet in an envelope and enforces the response-wide
budget with :func:`trim_packet`.

Budget accounting is done in UTF-8 bytes of the JSON that is actually returned
(``json.dumps(..., sort_keys=True, ensure_ascii=False)``, the same serialisation as
``RetrievalService._payload_tokens``) so section costs add up exactly to what the wire carries.

Fill strategy (see docs/CHANGELOG 0.2.0):

* Pass 1 walks the sections ``target -> callees -> callers -> more -> context``.  Every section owns
  a share of the budget; what a section does not use is carried to the next one.
* Pass 2 hands the remaining budget to the sections that were still cut, in the same order.
* Response-level shedding (:func:`trim_packet`) removes ``more -> context -> callers -> callees ->
  target lines`` until the whole response fits.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

from token_context_mcp.retrieve.token_budget import estimate_tokens

# Tuned on the 8 dev tasks only (M6.2 step 6, grid in evals/out/m6/packet_tuning_dev_grid.json) and frozen
# by the "freeze packet constants" commit; the held-out split is measured once after that commit.
DEFAULT_SHARES: dict[str, float] = {
    "target": 0.30,
    "callees": 0.25,
    "callers": 0.25,
    "more": 0.08,
    "context": 0.12,
}
CALLERS_K = 15
SECTION_ORDER: tuple[str, ...] = ("target", "callees", "callers", "more", "context")

# Shared edge filter (packet, reach_ceiling and every M6.4 metric).
CALLEE_MIN_CONFIDENCE = 0.6
CALLER_MIN_CONFIDENCE = 0.5


def payload_tokens(value: Any) -> int:
    """Same measure as ``RetrievalService._payload_tokens`` (kept in sync by a test)."""
    return estimate_tokens(json.dumps(value, sort_keys=True, ensure_ascii=False))


def _jbytes(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def _row_bytes(row: Any) -> int:
    # +2 for the ", " list separator of default json.dumps
    return _jbytes(row) + 2


def is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.startswith("tests/") or "/tests/" in normalized


def is_eval_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.startswith("evals/") or "/evals/" in normalized


def path_group(path: str) -> int:
    """Caller priority group: regular code (0), evals (1), tests (2)."""
    if is_test_path(path):
        return 2
    if is_eval_path(path):
        return 1
    return 0


@dataclass(frozen=True)
class Neighbor:
    """One 1-hop relation (or class sibling) that can be rendered as a packet row."""

    ref: str
    path: str
    line: int
    decl: str  # compact declaration, e.g. "f name"
    signature: str | None  # None when the file changed after indexing
    confidence: float | None
    relation: str  # "callee" | "caller" | "method"

    @property
    def loc(self) -> str:
        return f"{self.path}:{self.line}"

    def signature_row(self) -> list[Any]:
        return [self.ref, self.loc, self.signature, None if self.confidence is None else round(self.confidence, 2)]

    def method_row(self) -> list[Any]:
        return [self.ref, self.loc, self.signature]

    def more_row(self) -> list[Any]:
        label = self.relation
        if self.relation == "caller" and is_test_path(self.path):
            label = "test"
        return [self.ref, self.loc, self.decl, label]


@dataclass(frozen=True)
class PacketInputs:
    """Raw material for :func:`build_context_packet`; gathered without budget constraints."""

    target_ref: str
    target_symbol_id: str
    path: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int
    source_lines: tuple[str, ...] | None  # body lines, first line = start_line; None if unavailable
    signature_line_count: int = 1
    docstring_line: int | None = None  # file line number of the first docstring line
    call_lines: tuple[int, ...] = ()  # file lines that call a filtered callee
    skeleton: tuple[tuple[int, int, str], ...] = ()  # class targets: (line, end_line, text)
    callees: tuple[Neighbor, ...] = ()
    callers: tuple[Neighbor, ...] = ()
    imports: tuple[str, ...] = ()
    class_methods: tuple[Neighbor, ...] = ()
    file_sha: dict[str, str] = field(default_factory=dict)  # path -> sha256 (12 chars)
    warnings: tuple[str, ...] = ()
    raw_edge_count: int = 0
    retained_edge_count: int = 0
    # memo for derived, pure values (priority order, per-size render cost); never part of equality
    _cache: dict[Any, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def is_class(self) -> bool:
        return self.kind == "class"

    @property
    def relation_count(self) -> int:
        return len(self.callees) + len(self.callers)


# --------------------------------------------------------------------------------------
# target section
# --------------------------------------------------------------------------------------

def target_priority(inputs: PacketInputs) -> list[int]:
    cached = inputs._cache.get("priority")
    if cached is None:
        cached = inputs._cache["priority"] = _target_priority(inputs)
    return cached


def _target_priority(inputs: PacketInputs) -> list[int]:
    """Indices into ``source_lines`` ordered by how much they matter (kept set = a prefix).

    Essentials first: signature lines, the first docstring line, every line that calls a filtered
    callee.  Then the remaining non-blank lines by distance to the nearest essential line, then blank
    lines.  A truncated target therefore always keeps the calls that explain the callee list.
    """
    lines = inputs.source_lines or ()
    n = len(lines)
    essentials: list[int] = list(range(min(inputs.signature_line_count, n)))
    seen = set(essentials)
    if inputs.docstring_line is not None:
        idx = inputs.docstring_line - inputs.start_line
        if 0 <= idx < n and idx not in seen:
            essentials.append(idx)
            seen.add(idx)
    for line_no in sorted(set(inputs.call_lines)):
        idx = line_no - inputs.start_line
        if 0 <= idx < n and idx not in seen:
            essentials.append(idx)
            seen.add(idx)
    inf = n + 1
    dist = [inf] * n
    last = None
    for i in range(n):
        if i in seen:
            last = i
        if last is not None:
            dist[i] = i - last
    last = None
    for i in range(n - 1, -1, -1):
        if i in seen:
            last = i
        if last is not None:
            dist[i] = min(dist[i], last - i)
    rest = [i for i in range(n) if i not in seen]
    rest.sort(key=lambda i: (lines[i].strip() == "", dist[i], i))
    return essentials + rest


def _numbered(inputs: PacketInputs, idx: int) -> str:
    return f"{inputs.start_line + idx}: {(inputs.source_lines or ())[idx].rstrip()}"


def _line_bytes(text: str) -> int:
    # JSON string body (without the surrounding quotes) plus the escaped "\n" separator.
    return len(json.dumps(text, ensure_ascii=False).encode("utf-8")) - 2 + 2


def _ranges_of_omitted(inputs: PacketInputs, kept: set[int]) -> list[list[int]]:
    lines = inputs.source_lines or ()
    ranges: list[list[int]] = []
    i = 0
    n = len(lines)
    while i < n:
        if i in kept:
            i += 1
            continue
        j = i
        while j + 1 < n and (j + 1) not in kept:
            j += 1
        if any(lines[k].strip() for k in range(i, j + 1)):  # blank-only gaps carry no information
            ranges.append([inputs.start_line + i, inputs.start_line + j])
        i = j + 1
    return ranges


def render_target(inputs: PacketInputs, n_lines: int | None) -> dict[str, Any]:
    """Render the target section keeping the first ``n_lines`` priority lines (None = complete body)."""
    span = f"{inputs.path}:{inputs.start_line}-{inputs.end_line}"
    base: dict[str, Any] = {"symbol_id": inputs.target_ref, "span": span}
    if inputs.is_class:
        entries = list(inputs.skeleton)
        keep = len(entries) if n_lines is None else max(0, min(n_lines, len(entries)))
        if not entries:
            base.update({"content": None, "truncated_lines": None})
            return base
        content = "\n".join(f"{line}: {text}" for line, _end, text in entries[:keep])
        cut = [[line, end] for line, end, _text in entries[keep:]]
        base.update({"content": content or None, "truncated_lines": cut or None})
        return base
    lines = inputs.source_lines
    if lines is None:
        base.update({"content": None, "truncated_lines": None})
        return base
    if n_lines is None or n_lines >= len(lines):
        base.update({"content": "\n".join(text.rstrip() for text in lines).strip(), "truncated_lines": None})
        return base
    order = target_priority(inputs)
    kept = set(order[: max(0, n_lines)])
    if not kept:
        base.update({"content": None, "truncated_lines": [[inputs.start_line, inputs.end_line]]})
        return base
    content = "\n".join(_numbered(inputs, i) for i in sorted(kept))
    base.update({"content": content, "truncated_lines": _ranges_of_omitted(inputs, kept) or None})
    return base


def target_cost(inputs: PacketInputs, n_lines: int | None) -> int:
    """JSON bytes of ``render_target(inputs, n_lines)`` (memoised: the fill loops ask for the same sizes often)."""
    key = ("cost", n_lines)
    cost = inputs._cache.get(key)
    if cost is None:
        cost = inputs._cache[key] = _jbytes(render_target(inputs, n_lines))
    return cost


def _target_total_units(inputs: PacketInputs) -> int:
    if inputs.is_class:
        return len(inputs.skeleton)
    return len(inputs.source_lines or ())


def _fit_target(inputs: PacketInputs, cap_bytes: int) -> int | None:
    """Largest ``n_lines`` (or None = complete) whose rendered section fits ``cap_bytes``."""
    total = _target_total_units(inputs)
    if total == 0:
        return None
    if target_cost(inputs, None) <= cap_bytes:
        return None
    lo, hi = 0, total - 1  # find the largest n with cost <= cap (cost is near-monotone in n)
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if target_cost(inputs, mid) <= cap_bytes:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    # cost is only near-monotone (adding a line can merge two omitted ranges): extend greedily
    while best + 1 < total and target_cost(inputs, best + 1) <= cap_bytes:
        best += 1
    return best


# --------------------------------------------------------------------------------------
# row sections
# --------------------------------------------------------------------------------------

def _prefix_fit(row_costs: list[int], cap_bytes: int, limit: int | None = None) -> int:
    used = 0
    count = 0
    for cost in row_costs:
        if limit is not None and count >= limit:
            break
        if used + cost > cap_bytes:
            break
        used += cost
        count += 1
    return count


class _State:
    """Mutable fill state of one build (never leaves this module)."""

    def __init__(self, inputs: PacketInputs, callers_k: int) -> None:
        self.inputs = inputs
        self.callers_k = callers_k
        self.n_target: int | None = None  # None = complete
        self.n_callees = 0
        self.n_callers = 0
        self.n_more = 0
        self.n_ctx = 0
        rows = inputs._cache.get("rows")
        if rows is None:
            callee_rows = [n.signature_row() for n in inputs.callees]
            caller_rows = [n.signature_row() for n in inputs.callers]
            ctx_rows: list[Any] = [*inputs.imports, *[m.method_row() for m in inputs.class_methods]]
            rows = inputs._cache["rows"] = (
                callee_rows,
                caller_rows,
                ctx_rows,
                [_row_bytes(r) for r in callee_rows],
                [_row_bytes(r) for r in caller_rows],
                [_row_bytes(r) for r in ctx_rows],
            )
        (self._callee_rows, self._caller_rows, self._ctx_rows,
         self._callee_costs, self._caller_costs, self._ctx_costs) = rows

    # ---- derived lists ------------------------------------------------------------
    def more_pool(self) -> list[Neighbor]:
        return [*self.inputs.callees[self.n_callees:], *self.inputs.callers[self.n_callers:]]

    def more_rows(self) -> list[list[Any]]:
        return [n.more_row() for n in self.more_pool()]

    def section_bytes(self, section: str) -> int:
        if section == "target":
            return target_cost(self.inputs, self.n_target)
        if section == "callees":
            return sum(self._callee_costs[: self.n_callees])
        if section == "callers":
            return sum(self._caller_costs[: self.n_callers])
        if section == "more":
            return sum(_row_bytes(r) for r in self.more_rows()[: self.n_more])
        return sum(self._ctx_costs[: self.n_ctx])

    def is_cut(self, section: str) -> bool:
        if section == "target":
            return self.n_target is not None
        if section == "callees":
            return self.n_callees < len(self._callee_rows)
        if section == "callers":
            return self.n_callers < min(self.callers_k, len(self._caller_rows))
        if section == "more":
            return self.n_more < len(self.more_pool())
        return self.n_ctx < len(self._ctx_rows)

    def fill(self, section: str, cap_bytes: int) -> None:
        cap = max(0, cap_bytes)
        if section == "target":
            self.n_target = _fit_target(self.inputs, cap)
        elif section == "callees":
            self.n_callees = _prefix_fit(self._callee_costs, cap)
        elif section == "callers":
            self.n_callers = _prefix_fit(self._caller_costs, cap, self.callers_k)
        elif section == "more":
            rows = self.more_rows()
            self.n_more = _prefix_fit([_row_bytes(r) for r in rows], cap)
        else:
            self.n_ctx = _prefix_fit(self._ctx_costs, cap)

    # ---- output -------------------------------------------------------------------
    def packet(self) -> dict[str, Any]:
        inputs = self.inputs
        callees = [inputs.callees[i].signature_row() for i in range(self.n_callees)]
        callers = [inputs.callers[i].signature_row() for i in range(self.n_callers)]
        more_pool = self.more_pool()
        more = [n.more_row() for n in more_pool[: self.n_more]]
        n_imports = len(inputs.imports)
        imports = list(inputs.imports[: min(self.n_ctx, n_imports)])
        methods = [m.method_row() for m in inputs.class_methods[: max(0, self.n_ctx - n_imports)]]
        target = render_target(inputs, self.n_target)
        paths = {inputs.path}
        paths.update(inputs.callees[i].path for i in range(self.n_callees))
        paths.update(inputs.callers[i].path for i in range(self.n_callers))
        paths.update(n.path for n in more_pool[: self.n_more])
        paths.update(m.path for m in inputs.class_methods[: max(0, self.n_ctx - n_imports)])
        files = {p: inputs.file_sha[p] for p in sorted(paths) if p in inputs.file_sha}
        packet: dict[str, Any] = {
            "target": target,
            "callees": callees,
            "callers": callers,
            "more": more,
            "context": {"imports": imports, "class_methods": methods},
            "files": files,
            "used_tokens": {},
            "omitted": {
                "callees": 0,
                "callers": 0,
                "more": len(more_pool) - self.n_more,
                "class_methods": len(inputs.class_methods) - len(methods),
                "imports": n_imports - len(imports),
            },
        }
        return _finish(packet)


def _finish(packet: dict[str, Any]) -> dict[str, Any]:
    packet["used_tokens"] = {
        "target": payload_tokens(packet["target"]),
        "callees": payload_tokens(packet["callees"]),
        "callers": payload_tokens(packet["callers"]),
        "more": payload_tokens(packet["more"]),
        "context": payload_tokens(packet["context"]),
    }
    return packet


def build_context_packet(
    inputs: PacketInputs,
    budget_tokens: int,
    shares: dict[str, float] | None = None,
    callers_k: int | None = None,
) -> dict[str, Any]:
    """Build the packet so that ``payload_tokens(packet) <= budget_tokens`` whenever that is possible."""
    callers_k = CALLERS_K if callers_k is None else callers_k  # read at call time so evals can tune it
    shares = dict(DEFAULT_SHARES if shares is None else shares)
    total_share = sum(shares.get(s, 0.0) for s in SECTION_ORDER) or 1.0
    shares = {s: shares.get(s, 0.0) / total_share for s in SECTION_ORDER}
    budget_bytes = max(0, int(budget_tokens)) * 4
    # Bytes outside the section shares: files map, used_tokens, omitted, key names.  Estimated from an
    # empty build, then corrected by re-fitting against the exact size (at most a few rounds).
    reserve = _jbytes(_empty_frame(inputs)) + 24 * max(1, len({p for p in inputs.file_sha}))
    best: dict[str, Any] | None = None
    best_tokens = -1
    last: dict[str, Any] = {}
    for _ in range(8):
        last = _build_once(inputs, max(0, budget_bytes - reserve), shares, callers_k)
        used = payload_tokens(last)
        if used <= budget_tokens:
            if used > best_tokens:
                best, best_tokens = last, used
            slack = budget_tokens - used
            if slack <= 6:
                break
            reserve = max(0, reserve - (slack * 4 - 8))  # spend what is left over, then re-verify
        else:
            if best is not None:
                break  # tightening overshot: keep the best fitting build
            reserve += (used - budget_tokens) * 4 + 4
    return best if best is not None else last


def _empty_frame(inputs: PacketInputs) -> dict[str, Any]:
    frame = _State(inputs, CALLERS_K)
    frame.n_target = 0
    return frame.packet()


def _build_once(inputs: PacketInputs, budget_bytes: int, shares: dict[str, float], callers_k: int) -> dict[str, Any]:
    state = _State(inputs, callers_k)
    alloc = {s: int(budget_bytes * shares[s]) for s in SECTION_ORDER}
    carry = 0
    for section in SECTION_ORDER:  # pass 1: proportional fill with carry-over
        cap = alloc[section] + carry
        state.fill(section, cap)
        carry = max(0, cap - state.section_bytes(section))
    for _round in range(3):  # pass 2: hand the remainder to whatever is still cut, in order
        leftover = budget_bytes - sum(state.section_bytes(s) for s in SECTION_ORDER)
        progressed = False
        for section in SECTION_ORDER:
            if leftover <= 0:
                break
            if not state.is_cut(section):
                continue
            before = state.section_bytes(section)
            snapshot = (state.n_target, state.n_callees, state.n_callers, state.n_more, state.n_ctx)
            state.fill(section, before + leftover)
            after_total = sum(state.section_bytes(s) for s in SECTION_ORDER)
            if after_total > budget_bytes:  # a refill can grow `more` bookkeeping; undo if it overshoots
                state.n_target, state.n_callees, state.n_callers, state.n_more, state.n_ctx = snapshot
                continue
            if snapshot != (state.n_target, state.n_callees, state.n_callers, state.n_more, state.n_ctx):
                progressed = True
            leftover = budget_bytes - after_total
        if not progressed:
            break
    return state.packet()


# --------------------------------------------------------------------------------------
# response-level shedding
# --------------------------------------------------------------------------------------

def trim_packet(inputs: PacketInputs, packet: dict[str, Any], excess_tokens: int) -> bool:
    """Shed content until at least ``excess_tokens`` tokens are removed (or nothing is left).

    Order (M6.2 step 5): ``more`` -> ``context`` (class methods, then imports) -> ``callers`` ->
    ``callees`` -> target lines.  Rows cut here cannot move to ``more`` any more, so they are counted in
    ``omitted``.  Returns False when nothing was left to remove.
    """
    need_bytes = max(1, excess_tokens) * 4
    freed = 0
    changed = False

    def pop_rows(rows: list[Any], omitted_key: str | None) -> None:
        nonlocal freed, changed
        while rows and freed < need_bytes:
            freed += _row_bytes(rows.pop())
            changed = True
            if omitted_key is not None:
                packet["omitted"][omitted_key] += 1

    pop_rows(packet["more"], "more")
    ctx = packet["context"]
    pop_rows(ctx["class_methods"], "class_methods")
    pop_rows(ctx["imports"], "imports")
    pop_rows(packet["callers"], "callers")
    pop_rows(packet["callees"], "callees")
    if freed < need_bytes:
        cur = packet["target"]
        total = _target_total_units(inputs)
        if cur.get("content") is not None and total:
            current_n = _current_target_units(packet["target"], total)
            before = _jbytes(cur)
            n = current_n
            while n > 0 and before - target_cost(inputs, n) < need_bytes - freed:
                n -= 1
            packet["target"] = render_target(inputs, n)
            freed += max(0, before - _jbytes(packet["target"]))
            changed = True
    if changed:
        used_paths = _used_paths(packet)
        packet["files"] = {p: sha for p, sha in packet["files"].items() if p in used_paths}
        _finish(packet)
    return changed


def _current_target_units(target: dict[str, Any], total: int) -> int:
    content = target.get("content")
    if content is None:
        return 0
    if target.get("truncated_lines") is None and not _looks_numbered(content):
        return total
    return content.count("\n") + 1


def _looks_numbered(content: str) -> bool:
    head = content.split("\n", 1)[0]
    prefix, sep, _ = head.partition(": ")
    return bool(sep) and prefix.isdigit()


def _used_paths(packet: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    target_span = packet["target"]["span"]
    paths.add(target_span.rsplit(":", 1)[0])
    for key in ("callees", "callers", "more"):
        for row in packet[key]:
            paths.add(row[1].rsplit(":", 1)[0])
    for row in packet["context"]["class_methods"]:
        paths.add(row[1].rsplit(":", 1)[0])
    return paths


def packet_is_truncated(packet: dict[str, Any]) -> bool:
    return bool(packet["target"].get("truncated_lines")) or any(v > 0 for v in packet["omitted"].values())


def ceil_div(a: int, b: int) -> int:  # pragma: no cover - tiny helper kept for readability in tests
    return math.ceil(a / b)

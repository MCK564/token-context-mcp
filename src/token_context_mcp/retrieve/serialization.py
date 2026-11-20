"""Token-efficient serialization and result finalization (P1)."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Literal

from token_context_mcp.mcp_compat import CallToolResult, TextContent

OutputMode = Literal["auto", "structured", "text", "compact_text", "legacy_dual"]


def serialize_compact(payload: dict[str, Any]) -> str:
    """Serialize dictionary payload to compact JSON without whitespace overhead."""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _compact_header(payload: dict[str, Any]) -> str:
    """Format the compact envelope header line for a repo-scoped payload."""
    parts = [f"repo={payload.get('repo_id')}"]
    if payload.get("freshness") is not None:
        parts.append(f"freshness={payload.get('freshness')}")
    if payload.get("truncated"):
        parts.append("truncated=true")
    if payload.get("ledger_rev") is not None:
        parts.append(f"ledger_rev={payload['ledger_rev']}")
    warnings = payload.get("warnings") or []
    if warnings:
        parts.append(f"warnings={','.join(str(w) for w in warnings)}")
    return " ".join(parts)


def _format_prior_evidence_lines(pe: Any) -> list[str]:
    """Render ledger prior_evidence summary into compact lines."""
    if not isinstance(pe, dict):
        return []
    head = [f"prior_evidence: status={pe.get('status')} match={pe.get('match')}"]
    if pe.get("recheck_from") is not None:
        head.append(f"recheck_from={pe['recheck_from']}")
    lines = [" ".join(head)]
    for ans in pe.get("answers") or []:
        if isinstance(ans, (list, tuple)) and len(ans) >= 4:
            lines.append(f"  answer: [{ans[0]}] {ans[1]}:{ans[2]} ({ans[3]})")
    for step in pe.get("steps") or []:
        if isinstance(step, (list, tuple)) and len(step) >= 5:
            lines.append(f"  step: {step[0]} -> {step[1]} @ {step[2]}:{step[3]} ({step[4]})")
    for decoy in pe.get("decoys") or []:
        if isinstance(decoy, (list, tuple)) and len(decoy) >= 2:
            lines.append(f"  decoy: {decoy[0]} ({decoy[1]})")
    return lines


def _render_edge_line(edge: dict[str, Any]) -> str:
    """Render a single graph edge dictionary as a dense line."""
    src = edge.get("source_symbol_id", "")
    tgt = edge.get("target_symbol_id") or edge.get("target_name") or ""
    kind = edge.get("edge_kind", "")
    status = edge.get("status", "")
    conf = edge.get("confidence")
    conf_str = f" {conf:.2f}" if isinstance(conf, (int, float)) else ""
    loc = f"{edge.get('source_path', '')}:{edge.get('source_line', 0)}"
    return f"  {src} -[{kind}:{status}{conf_str}]-> {tgt} ({loc})"


def _append_omitted_and_security(lines: list[str], data: dict[str, Any]) -> None:
    """Append shared omitted_count / omitted_symbol_ids / injection_hits lines if present."""
    omitted = data.get("omitted_count")
    if isinstance(omitted, int) and omitted > 0:
        total = data.get("total_matches")
        lines.append(f"omitted={omitted} total={total}" if total is not None else f"omitted={omitted}")
    if data.get("omitted_symbol_ids"):
        lines.append(f"omitted_ids={','.join(str(x) for x in data['omitted_symbol_ids'])}")
    if data.get("injection_hits"):
        lines.append(f"injection_hits={','.join(str(x) for x in data['injection_hits'])}")


def _render_repo_map_lines(data: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    digests = data.get("file_digests") or {}
    files_map = data.get("files")
    if isinstance(files_map, dict):
        for path, entries in files_map.items():
            digest = f" [{digests[path]}]" if path in digests else ""
            lines.append(f"@ {path}{digest}")
            for entry in entries:
                s = str(entry)
                lines.append("  " + (s.replace(":L", " L", 1) if ":L" in s else s))
    elif isinstance(data.get("symbols"), list):
        grouped: dict[str, list[str]] = {}
        for item in data["symbols"]:
            if isinstance(item, (list, tuple)) and len(item) >= 3:
                loc = str(item[1])
                path, _, line = loc.rpartition(":")
                path = path or loc
                role = f" {item[3]}" if len(item) > 3 and item[3] else ""
                grouped.setdefault(path, []).append(f"  {item[0]} L{line} {item[2]}{role}")
            elif isinstance(item, dict):
                sym = item.get("symbol", item)
                if not isinstance(sym, dict):
                    continue
                path = str(sym.get("path") or "<unknown>")
                roles = sym.get("roles") or []
                role_tag = f" [{','.join(str(r) for r in roles)}]" if roles else ""
                sig = f" | {sym['signature']}" if sym.get("signature") else ""
                grouped.setdefault(path, []).append(
                    f"  {sym.get('symbol_id', '')} L{sym.get('start_line', 0)} "
                    f"{sym.get('kind', '')} {sym.get('name', '')}{role_tag}{sig}"
                )
        for path, sym_lines in grouped.items():
            digest = f" [{digests[path]}]" if path in digests else ""
            lines.append(f"@ {path}{digest}")
            lines.extend(sym_lines)
    lines.extend(_format_prior_evidence_lines(data.get("prior_evidence")))
    _append_omitted_and_security(lines, data)
    return lines


def _render_file_skeleton_lines(data: dict[str, Any]) -> list[str]:
    lines = [
        f"# {data.get('path', '')} (imports={data.get('imports', 0)}, imported_by={data.get('imported_by', 0)})"
    ]
    for item in data.get("skeleton") or []:
        if not isinstance(item, dict):
            continue
        start = item.get("start_line", 0)
        end = item.get("end_line", start)
        content = item.get("content")
        text = "<stale>" if content is None else str(content)
        lines.append(f"L{start}-L{end}: {text}")
    _append_omitted_and_security(lines, data)
    return lines


def _render_search_source_lines(data: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for match in data.get("matches") or []:
        if not isinstance(match, dict):
            continue
        sid = match.get("symbol_id") or "<module>"
        start = match.get("start_line", 0)
        end = match.get("end_line", start)
        snippet = "<stale>" if match.get("snippet") is None else str(match.get("snippet"))
        lines.append(f"[{sid}] {match.get('path', '')}:{start}-{end} | {snippet}")
        extra_lines = match.get("lines") or []
        for extra in extra_lines[1:]:
            if isinstance(extra, (list, tuple)) and len(extra) == 2:
                lines.append(f"  L{extra[0]}: {extra[1]}")
    neighbors = data.get("neighbors") or []
    if neighbors:
        lines.append("neighbors:")
        for row in neighbors:
            if isinstance(row, (list, tuple)) and len(row) >= 6:
                lines.append(f"  {row[3]}: [{row[0]}] {row[1]} | {row[2]} (score={row[4]})")
            else:
                lines.append(f"  {row}")
    lines.extend(_format_prior_evidence_lines(data.get("prior_evidence")))
    _append_omitted_and_security(lines, data)
    return lines


def _render_find_symbols_lines(data: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for sym in data.get("symbols") or []:
        if not isinstance(sym, dict):
            continue
        lines.append(
            f"{sym.get('symbol_id', '')} | {sym.get('kind', '')} {sym.get('name', '')} | "
            f"{sym.get('path', '')}:{sym.get('start_line', 0)}-{sym.get('end_line', 0)} | {sym.get('signature', '')}"
        )
    lines.extend(_format_prior_evidence_lines(data.get("prior_evidence")))
    _append_omitted_and_security(lines, data)
    return lines


def _render_module_dependents_lines(data: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if data.get("matched_paths"):
        lines.append(f"paths: {', '.join(str(p) for p in data['matched_paths'])}")
    imports = data.get("imports") or []
    imported_by = data.get("imported_by") or []
    lines.append(f"imports: {', '.join(str(x) for x in imports) if imports else '(none)'}")
    lines.append(f"imported_by: {', '.join(str(x) for x in imported_by) if imported_by else '(none)'}")
    _append_omitted_and_security(lines, data)
    return lines


def _render_impact_slice_lines(data: dict[str, Any]) -> list[str]:
    head = (
        f"root={data.get('root_symbol_id')} dir={data.get('direction')} "
        f"depth={data.get('depth')} visited={data.get('nodes_visited')}"
    )
    if data.get("node_limit_reached"):
        head += " node_limit_reached=true"
    lines = [head]
    for sym in data.get("symbols") or []:
        if isinstance(sym, dict):
            lines.append(
                f"  {sym.get('symbol_id', '')} | {sym.get('kind', '')} {sym.get('name', '')} | "
                f"{sym.get('path', '')}:{sym.get('start_line', 0)}-{sym.get('end_line', 0)}"
            )
    for edge in data.get("edges") or []:
        if isinstance(edge, dict):
            lines.append(_render_edge_line(edge))
    omitted_syms = data.get("omitted_count", 0) or 0
    omitted_edges = data.get("omitted_edge_count", 0) or 0
    if omitted_syms or omitted_edges:
        lines.append(f"omitted_symbols={omitted_syms} omitted_edges={omitted_edges}")
    return lines


def _render_symbol_context_lines(data: dict[str, Any]) -> list[str]:
    lines = [f"root={data.get('root_symbol_id')}"]
    for packet in data.get("symbols") or []:
        if not isinstance(packet, dict):
            continue
        sym = packet.get("symbol") or {}
        lines.append(
            f"[{sym.get('symbol_id', '')}] {sym.get('kind', '')} {sym.get('name', '')} | "
            f"{sym.get('path', '')}:{sym.get('start_line', 0)}-{sym.get('end_line', 0)}"
        )
        win = packet.get("body_window")
        if isinstance(win, dict):
            lines.append(
                f"window=L{win.get('start_line')}-L{win.get('end_line')}/{win.get('total_lines')} "
                f"next={win.get('next_offset')}"
            )
        if packet.get("content") is not None:
            lines.append(str(packet["content"]))
        elif packet.get("warnings"):
            lines.append(f"warnings={','.join(str(w) for w in packet['warnings'])}")
    for edge in data.get("edges") or []:
        if isinstance(edge, dict):
            lines.append(_render_edge_line(edge))
    for key in ("root_body_tokens_needed", "root_body_lines", "min_budget_tokens", "root_body_hint"):
        if data.get(key) is not None:
            lines.append(f"{key}={data[key]}")
    omitted_edges = data.get("omitted_edge_count", 0) or 0
    if omitted_edges:
        lines.append(f"omitted_edges={omitted_edges}")
    _append_omitted_and_security(lines, data)
    return lines


def _render_inspect_symbol_lines(data: dict[str, Any]) -> list[str]:
    status = data.get("status")
    query = data.get("query", "")
    if status == "not_found":
        return [f"status=not_found query={query} | {data.get('message', '')}"]
    if status == "ambiguous":
        lines = [f"status=ambiguous query={query} candidates={data.get('candidate_count', 0)}"]
        for cand in data.get("candidates") or []:
            if isinstance(cand, dict):
                lines.append(
                    f"  {cand.get('symbol_id', '')} | {cand.get('kind', '')} {cand.get('name', '')} | "
                    f"{cand.get('path', '')}:{cand.get('start_line', 0)}"
                )
        return lines
    sym = data.get("symbol") or {}
    end_line = sym.get("end_line", sym.get("start_line", 0))
    lines = [
        f"status={status} [{sym.get('symbol_id', '')}] {sym.get('kind', '')} {sym.get('name', '')} | "
        f"{sym.get('path', '')}:{sym.get('start_line', 0)}-{end_line}"
    ]
    if sym.get("signature"):
        lines.append(f"sig: {sym['signature']}")
    if data.get("content") is not None:
        lines.append(str(data["content"]))
    for rel in data.get("relationships") or []:
        if isinstance(rel, (list, tuple)):
            lines.append("  rel: " + " ".join(str(x) for x in rel))
        elif isinstance(rel, dict):
            lines.append(f"  {rel.get('source')} -[{rel.get('kind')}]-> {rel.get('target')}")
    packet = data.get("packet")
    if isinstance(packet, dict):
        target = packet.get("target") or {}
        if target.get("span"):
            lines.append(f"target: {target['span']}")
        if target.get("content") is not None:
            lines.append(str(target["content"]))
        for rel_key in ("callees", "callers", "more"):
            rows = packet.get(rel_key) or []
            if rows:
                lines.append(f"{rel_key}:")
                for row in rows:
                    lines.append("  " + (" | ".join(str(x) for x in row if x is not None) if isinstance(row, (list, tuple)) else str(row)))
        ctx = packet.get("context") or {}
        for sub_key in ("class_methods", "imports"):
            rows = ctx.get(sub_key) or []
            if rows:
                lines.append(f"{sub_key}:")
                for row in rows:
                    lines.append("  " + (" | ".join(str(x) for x in row) if isinstance(row, (list, tuple)) else str(row)))
    if data.get("retry_hint"):
        lines.append(f"retry_hint: {serialize_compact(data['retry_hint'])}")
    _append_omitted_and_security(lines, data)
    return lines


def _render_status_lines(data: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    counts = [
        f"{label}={data[key]}"
        for key, label in (("files_indexed", "files"), ("symbols_indexed", "symbols"), ("edges_indexed", "edges"))
        if data.get(key) is not None
    ]
    if counts:
        lines.append(" ".join(counts))
    counters = [
        f"{label}={data[key]}"
        for key, label in (("pending_path_count", "pending"), ("added_path_count", "added"))
        if data.get(key) is not None
    ]
    if data.get("commit_sha"):
        counters.append(f"commit={str(data['commit_sha'])[:12]}")
    if data.get("head_changed_since_index") is not None:
        counters.append(f"head_changed={str(data['head_changed_since_index']).lower()}")
    if counters:
        lines.append(" ".join(counters))
    imp_parts = [f"{k}={data[k]}" for k in ("imports", "imported_by") if data.get(k) is not None]
    if imp_parts:
        lines.append(" ".join(imp_parts))
    if data.get("symbols_with_roles") is not None:
        lines.append(f"symbols_with_roles={data['symbols_with_roles']}")
    if data.get("role_counts"):
        lines.append("roles: " + ", ".join(f"{k}={v}" for k, v in data["role_counts"].items()))
    if data.get("entry_points"):
        lines.append(f"entry_points: {serialize_compact(data['entry_points'])}")
    for list_key in ("pending_paths", "added_paths", "changed_non_indexed", "index_warnings"):
        vals = data.get(list_key)
        if vals:
            lines.append(f"{list_key}: {', '.join(str(v) for v in vals)}")
    if data.get("network_policy_status"):
        lines.append(f"network_policy_status={data['network_policy_status']}")
    return lines


def _strip_empty(mapping: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in mapping.items()
        if k not in ("schema_version", "index_run_id", "completeness", "estimator_version")
        and v is not None
        and v != []
        and v != {}
    }


def render_compact_text(payload: dict[str, Any]) -> str:
    """Render an MCP tool payload into dense line-oriented text without JSON envelope boilerplate."""
    error = payload.get("error")
    if isinstance(error, dict):
        return f"ERROR {error.get('code', 'error')}: {error.get('message', '')}"
    if error:
        return f"ERROR error: {error}"

    data = payload.get("data")
    if "repo_id" not in payload or not isinstance(data, dict):
        if "repo_ids" in payload:
            repos = ", ".join(str(r) for r in payload.get("repo_ids") or []) or "(none)"
            lines = [f"repos: {repos}"]
            if payload.get("truncated"):
                lines.append("truncated=true")
            profiles = payload.get("budget_profiles")
            if isinstance(profiles, dict) and profiles:
                lines.append(f"profiles: {serialize_compact(profiles)}")
            return "\n".join(lines)
        cleaned = _strip_empty(payload)
        if cleaned.get("truncated") is False:
            cleaned.pop("truncated", None)
        return serialize_compact(cleaned)

    lines = [_compact_header(payload)]
    if "files" in data or "rank_mode" in data or "format" in data:
        lines.extend(_render_repo_map_lines(data))
    elif "skeleton" in data:
        lines.extend(_render_file_skeleton_lines(data))
    elif "matches" in data:
        lines.extend(_render_search_source_lines(data))
    elif "symbols" in data and "total_matches" in data:
        lines.extend(_render_find_symbols_lines(data))
    elif "imports" in data and "imported_by" in data and isinstance(data.get("imports"), list):
        lines.extend(_render_module_dependents_lines(data))
    elif "direction" in data and "nodes_visited" in data:
        lines.extend(_render_impact_slice_lines(data))
    elif "root_symbol_id" in data and "symbols" in data:
        lines.extend(_render_symbol_context_lines(data))
    elif "status" in data and "query" in data:
        lines.extend(_render_inspect_symbol_lines(data))
    elif "files_indexed" in data or "pending_path_count" in data:
        lines.extend(_render_status_lines(data))
    else:
        cleaned_data = _strip_empty(data)
        if cleaned_data:
            lines.append(serialize_compact(cleaned_data))
    return "\n".join(lines)


def summarize_payload(payload: dict[str, Any]) -> str:
    """Produce concise, token-efficient metadata summary (< 200 chars) for structured-capable clients."""
    error = payload.get("error")
    if isinstance(error, dict):
        return f"error: {error.get('code')} - {error.get('message')}"

    parts = [f"repo_id={payload.get('repo_id')}", f"freshness={payload.get('freshness')}"]
    if payload.get("truncated"):
        parts.append("truncated=true")
    warnings = payload.get("warnings") or []
    if warnings:
        parts.append(f"warnings={len(warnings)}")

    data = payload.get("data")
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, list):
                parts.append(f"{key}={len(value)}")
            elif isinstance(value, (int, float, str, bool)) and key not in ("query", "pattern"):
                parts.append(f"{key}={value}")

    return " ".join(parts)


def normalize_line_endings(data: Any) -> Any:
    """Recursively normalize CRLF to LF in strings within data structures."""
    if isinstance(data, str):
        return data.replace("\r\n", "\n")
    elif isinstance(data, list):
        return [normalize_line_endings(item) for item in data]
    elif isinstance(data, dict):
        return {key: normalize_line_endings(value) for key, value in data.items()}
    return data


class ResultFinalizer:
    """Formats CallToolResult according to configured output mode without duplicate payloads."""

    def __init__(
        self,
        output_mode: OutputMode = "structured",
        max_wire_bytes: int = 1048576,
        client_name: Callable[[], str | None] | None = None,
    ) -> None:
        self.output_mode = output_mode
        self.max_wire_bytes = max_wire_bytes
        self._client_name = client_name

    @property
    def effective_mode(self) -> str:
        """The mode used right now: ``auto`` resolved against the client seen so far."""
        from token_context_mcp.client_profile import resolve_output_mode

        name = self._client_name() if self._client_name is not None else None
        return resolve_output_mode(self.output_mode, name)

    def finalize(self, payload: dict[str, Any], output_mode: OutputMode | None = None) -> CallToolResult:
        payload = normalize_line_endings(payload)
        if output_mode is not None and output_mode != "auto":
            mode = output_mode
        else:
            mode = self.effective_mode

        if mode == "structured":
            # Primary mode: summary in text (< 200 chars) and full payload in structured_content
            return CallToolResult(
                content=[TextContent(type="text", text=summarize_payload(payload))],
                structured_content=payload,
            )
        elif mode == "text":
            # Text-only client mode: compact JSON in content, empty structured_content
            compact_text = serialize_compact(payload)
            return CallToolResult(
                content=[TextContent(type="text", text=compact_text)],
            )
        elif mode == "compact_text":
            return CallToolResult(
                content=[TextContent(type="text", text=render_compact_text(payload))],
            )
        else:
            # legacy_dual: both content and structured_content have full payload
            compact_text = serialize_compact(payload)
            return CallToolResult(
                content=[TextContent(type="text", text=compact_text)],
                structured_content=payload,
            )

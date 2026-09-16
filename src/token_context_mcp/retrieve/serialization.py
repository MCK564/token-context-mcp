"""Token-efficient serialization and result finalization (P1)."""
from __future__ import annotations

import json
from typing import Any, Literal
from mcp.types import CallToolResult, TextContent

OutputMode = Literal["structured", "text", "legacy_dual"]


def serialize_compact(payload: dict[str, Any]) -> str:
    """Serialize dictionary payload to compact JSON without whitespace overhead."""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


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


class ResultFinalizer:
    """Formats CallToolResult according to configured output mode without duplicate payloads."""

    def __init__(self, output_mode: OutputMode = "structured", max_wire_bytes: int = 1048576) -> None:
        self.output_mode = output_mode
        self.max_wire_bytes = max_wire_bytes

    def finalize(self, payload: dict[str, Any], output_mode: OutputMode | None = None) -> CallToolResult:
        mode = output_mode or self.output_mode

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
        else:
            # legacy_dual: both content and structured_content have full payload
            compact_text = serialize_compact(payload)
            return CallToolResult(
                content=[TextContent(type="text", text=compact_text)],
                structured_content=payload,
            )

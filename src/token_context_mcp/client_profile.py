"""Per-client behaviour: output mode ``auto`` and schema profiles (M9.2, M9.3).

Nothing here changes what a tool does. ``auto`` only chooses where the payload travels (structuredContent or
the text block) and the ``gemini_safe`` profile only rewrites the JSON Schemas advertised in ``tools/list``.
"""
from __future__ import annotations

import copy
import json
import threading
from dataclasses import dataclass
from typing import Any

OUTPUT_MODES = ("auto", "structured", "text", "legacy_dual")
SCHEMA_PROFILES = ("auto", "default", "gemini_safe")

# Clients verified (docs/CLIENT_MATRIX.md) to hand ``structuredContent`` to the model.  Lower-case names.
STRUCTURED_OK_CLIENTS: frozenset[str] = frozenset({"claude-code"})

_GEMINI_MARKERS = ("gemini", "antigravity")


@dataclass
class ClientState:
    """What the server learned about its client. One stdio connection per process, so one instance."""

    name: str | None = None
    version: str | None = None
    lock: threading.Lock = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.lock = threading.Lock()

    def update(self, name: str | None, version: str | None) -> None:
        with self.lock:
            if name:
                self.name = name
            if version:
                self.version = version


def resolve_output_mode(requested: str, client_name: str | None) -> str:
    """``auto`` -> ``structured`` for a known-good client, otherwise ``text`` (never ``legacy_dual``)."""
    if requested != "auto":
        return requested
    if client_name and client_name.strip().lower() in STRUCTURED_OK_CLIENTS:
        return "structured"
    return "text"


def resolve_schema_profile(requested: str, client_name: str | None) -> str:
    if requested != "auto":
        return requested
    lowered = (client_name or "").lower()
    return "gemini_safe" if any(marker in lowered for marker in _GEMINI_MARKERS) else "default"


# --- schema profile --------------------------------------------------------------------------------------------

def _non_null(branches: list[Any]) -> list[Any]:
    return [b for b in branches if not (isinstance(b, dict) and b.get("type") == "null")]


def _resolve_ref(ref: str, defs: dict[str, Any]) -> Any:
    name = ref.rsplit("/", 1)[-1]
    return defs.get(name, {})


def _clean(node: Any, defs: dict[str, Any], depth: int = 0) -> Any:
    if isinstance(node, list):
        return [_clean(item, defs, depth) for item in node]
    if not isinstance(node, dict):
        return node
    node = dict(node)
    if "$ref" in node and depth < 8:
        resolved = copy.deepcopy(_resolve_ref(node.pop("$ref"), defs))
        merged = {**resolved, **node}
        return _clean(merged, defs, depth + 1)
    if isinstance(node.get("anyOf"), list):
        branches = _non_null(node["anyOf"])
        rest = {k: v for k, v in node.items() if k != "anyOf"}
        if len(branches) == 1:
            merged = {**_clean(branches[0], defs, depth), **rest}
            if merged.get("default", 0) is None:
                del merged["default"]
            return merged
        node = {**rest, "anyOf": [_clean(b, defs, depth) for b in branches]}
    if isinstance(node.get("type"), list):
        kinds = [k for k in node["type"] if k != "null"]
        node["type"] = kinds[0] if len(kinds) == 1 else (kinds[0] if kinds else "string")
    if "default" in node and node["default"] is None:
        del node["default"]
    if "properties" in node and isinstance(node["properties"], dict):
        node["properties"] = {k: _ensure_type(_clean(v, defs, depth)) for k, v in node["properties"].items()}
    if node.get("type") == "array":
        node["items"] = _ensure_type(_clean(node["items"], defs, depth)) if "items" in node else {"type": "string"}
    elif "items" in node:
        node["items"] = _clean(node["items"], defs, depth)
    for key in ("anyOf", "oneOf", "allOf"):
        if isinstance(node.get(key), list):
            node[key] = [_ensure_type(_clean(b, defs, depth)) for b in node[key]]
    if "additionalProperties" in node and isinstance(node["additionalProperties"], dict):
        node["additionalProperties"] = _clean(node["additionalProperties"], defs, depth)
    node.pop("$defs", None)
    return node


def _ensure_type(node: Any) -> Any:
    if isinstance(node, dict) and not any(k in node for k in ("type", "anyOf", "oneOf", "allOf", "enum", "const")):
        return {**node, "type": "string"}
    return node


def apply_schema_profile(schema: dict[str, Any], profile: str, tool_name: str = "") -> dict[str, Any]:
    """Return the schema advertised for ``profile``. ``default`` returns the input unchanged."""
    if profile != "gemini_safe":
        return schema
    defs = schema.get("$defs", {}) if isinstance(schema, dict) else {}
    cleaned = _clean(copy.deepcopy(schema), defs)
    if tool_name == "memory_put":
        props = cleaned.get("properties", {})
        if "value" in props:
            props["value"] = {"title": props["value"].get("title", "Value"), "type": "string",
                              "description": "Value to store; JSON text is parsed."}
    return cleaned


def coerce_memory_value(value: Any, profile: str) -> Any:
    """gemini_safe declares memory_put.value as a string; parse JSON text back, keep the string on failure."""
    if profile != "gemini_safe" or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        return value

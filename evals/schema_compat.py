"""Inspect JSON Schemas of MCP tools and repository artifacts for LLM client compatibility (M0 baseline).

Flags schemas for:
  - $defs / $ref
  - anyOf with null
  - type as array (e.g. ['string', 'null'])
  - property missing type
  - array missing items
"""
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from token_context_mcp.client_profile import apply_schema_profile
from token_context_mcp.config import default_config_path
from token_context_mcp.server import build_server


@dataclass
class SchemaIssue:
    schema_source: str
    tool_or_file: str
    json_path: str
    issue_type: str
    detail: str


def check_schema_node(node: Any, source: str, name: str, path: str = "") -> list[SchemaIssue]:
    issues: list[SchemaIssue] = []

    if not isinstance(node, dict):
        if isinstance(node, list):
            for i, item in enumerate(node):
                issues.extend(check_schema_node(item, source, name, f"{path}[{i}]"))
        return issues

    # 1. $ref and $defs
    if "$ref" in node:
        issues.append(SchemaIssue(
            schema_source=source,
            tool_or_file=name,
            json_path=path or "$",
            issue_type="ref_used",
            detail=f"Found $ref to: {node['$ref']}",
        ))
    if "$defs" in node:
        issues.append(SchemaIssue(
            schema_source=source,
            tool_or_file=name,
            json_path=f"{path}.$defs" if path else "$defs",
            issue_type="defs_declared",
            detail=f"Declared $defs with {len(node['$defs'])} definitions",
        ))

    # 2. anyOf containing null
    if "anyOf" in node and isinstance(node["anyOf"], list):
        has_null = any(
            isinstance(sub, dict) and sub.get("type") == "null"
            for sub in node["anyOf"]
        )
        if has_null:
            issues.append(SchemaIssue(
                schema_source=source,
                tool_or_file=name,
                json_path=f"{path}.anyOf" if path else "anyOf",
                issue_type="anyof_null",
                detail="anyOf includes {'type': 'null'} (nullable union)",
            ))

    # 3. type as array
    node_type = node.get("type")
    if isinstance(node_type, list):
        issues.append(SchemaIssue(
            schema_source=source,
            tool_or_file=name,
            json_path=f"{path}.type" if path else "type",
            issue_type="array_type",
            detail=f"type declared as list: {node_type}",
        ))

    # 4. array missing items
    if node_type == "array" and "items" not in node:
        issues.append(SchemaIssue(
            schema_source=source,
            tool_or_file=name,
            json_path=path or "$",
            issue_type="array_missing_items",
            detail="Schema type is 'array' but 'items' schema is missing",
        ))

    # 5. property missing type
    if "properties" in node and isinstance(node["properties"], dict):
        for prop_name, prop_val in node["properties"].items():
            prop_path = f"{path}.properties.{prop_name}" if path else f"properties.{prop_name}"
            if isinstance(prop_val, dict):
                has_type_indicator = (
                    "type" in prop_val
                    or "$ref" in prop_val
                    or "anyOf" in prop_val
                    or "oneOf" in prop_val
                    or "allOf" in prop_val
                )
                if not has_type_indicator:
                    issues.append(SchemaIssue(
                        schema_source=source,
                        tool_or_file=name,
                        json_path=prop_path,
                        issue_type="property_missing_type",
                        detail=f"Property '{prop_name}' has no 'type', '$ref', or anyOf/oneOf",
                    ))

    # Recursively traverse children
    for key, val in node.items():
        child_path = f"{path}.{key}" if path else key
        issues.extend(check_schema_node(val, source, name, child_path))

    return issues


def inspect_all_schemas(
    config_path: Path | None = None,
    enable_extensions: bool = True,
    schemas_dir: Path | None = None,
    schema_profile: str = "default",
) -> dict[str, Any]:
    issues: list[SchemaIssue] = []
    cfg_p = config_path or default_config_path()

    # 1. Inspect MCP tool schemas
    server = build_server(cfg_p, enable_extensions=enable_extensions)
    tools = asyncio.run(server.list_tools())

    tool_counts: dict[str, int] = {}
    for tool in tools:
        t_dict = tool.model_dump(mode="json", by_alias=True)
        input_schema = t_dict.get("inputSchema") or t_dict.get("parameters") or {}
        input_schema = apply_schema_profile(input_schema, schema_profile, tool.name)
        tool_issues = check_schema_node(input_schema, source="mcp_tool", name=tool.name)
        tool_counts[tool.name] = len(tool_issues)
        issues.extend(tool_issues)

    # 2. Inspect static schema files in schemas/
    static_counts: dict[str, int] = {}
    s_dir = schemas_dir or (Path(__file__).parent.parent / "schemas")
    # Static files are documentation of what the server returns, never sent to a client: a profile audit skips them.
    if s_dir.exists() and schema_profile == "default":
        for json_file in sorted(s_dir.glob("*.json")):
            try:
                with json_file.open("r", encoding="utf-8") as f:
                    schema_data = json.load(f)
                file_issues = check_schema_node(schema_data, source="schema_file", name=json_file.name)
                static_counts[json_file.name] = len(file_issues)
                issues.extend(file_issues)
            except Exception as e:
                pass

    issue_dicts = [asdict(i) for i in issues]

    # Group by issue type
    by_type: dict[str, int] = {}
    for i in issues:
        by_type[i.issue_type] = by_type.get(i.issue_type, 0) + 1

    return {
        "tools_scanned": len(tools),
        "static_schemas_scanned": len(static_counts),
        "total_issues": len(issues),
        "issues_by_type": by_type,
        "tool_issue_counts": tool_counts,
        "static_schema_counts": static_counts,
        "issues": issue_dicts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit MCP tool schemas and static schemas for LLM client compatibility.")
    parser.add_argument("--config", default=None, help="Path to repos.toml configuration")
    parser.add_argument("--schema-profile", choices=["default", "gemini_safe"], default="default", help="Apply this tools/list schema profile before auditing")
    parser.add_argument("--no-extensions", action="store_true", help="Exclude extended tools")
    parser.add_argument("--output", default=None, help="Path to save JSON compatibility report")

    args = parser.parse_args()
    cfg_p = Path(args.config).expanduser().resolve() if args.config else None

    report = inspect_all_schemas(
        config_path=cfg_p, enable_extensions=not args.no_extensions, schema_profile=args.schema_profile
    )
    report["schema_profile"] = args.schema_profile

    print("=== MCP Schema Compatibility Audit ===")
    print(f"Scanned {report['tools_scanned']} tools and {report['static_schemas_scanned']} schema files.")
    print(f"Total compatibility flags: {report['total_issues']}\n")

    print("Flags by category:")
    for k, v in sorted(report["issues_by_type"].items()):
        print(f"  - {k:<25}: {v}")

    print("\nTools with flags:")
    for tool_name, count in sorted(report["tool_issue_counts"].items()):
        if count > 0:
            print(f"  - {tool_name:<25}: {count} flag(s)")

    if args.output:
        out_p = Path(args.output).expanduser().resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with out_p.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"\nSaved schema compatibility report to {out_p}")


if __name__ == "__main__":
    main()

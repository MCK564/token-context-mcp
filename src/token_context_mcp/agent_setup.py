"""Helpers for installing Lean Selective agent rules and client MCP setup."""
from __future__ import annotations

import dataclasses
import json
import re
import sys
from pathlib import Path
from typing import Any

from token_context_mcp.config import default_config_path, load_config, save_config

RULE_BEGIN_MARKER = "<!-- BEGIN TOKEN-CONTEXT-LEAN-RULE -->"
RULE_END_MARKER = "<!-- END TOKEN-CONTEXT-LEAN-RULE -->"

LEAN_RULE_BODY = """# Token-Context MCP: Lean Selective
Call `token-context` MCP directly (skip `.json` schema reads unless a call errors):
- `search_source(repo_id, query, profile="locate", max_tokens=1280, limit=15)`
- `get_file_skeleton(repo_id, path, include_private=false, max_tokens=1536)`
- `inspect_symbol(repo_id, query, view="full", budget_tokens=1536)`
- `get_impact_slice(repo_id, symbol_id, direction="both", depth=2, max_tokens=1536)`
- `get_repo_map(repo_id, query=None, budget_tokens=1024, format="grouped")`

1. Known path -> `get_file_skeleton` (signatures) or direct `read_file` (<300 lines); skip `list_repositories`/`get_repo_map`/`search_source`. Unknown path or impact -> 1 call (`search_source`/`inspect_symbol`/`get_impact_slice`).
2. Anti-Double-Read: when `get_file_skeleton`/`inspect_symbol` returns `freshness=fresh` & `truncated=false` with needed info, stop — never `read_file` the whole file (only 20-60 line windows if needed).
3. Skip repeat `get_index_status` (`freshness` is in every reply); keep `trajectory_record`/`memory_put` opt-in.
"""

_MARKED_BLOCK_RE = re.compile(
    re.escape(RULE_BEGIN_MARKER) + r".*?" + re.escape(RULE_END_MARKER) + r"\r?\n?",
    re.DOTALL,
)
_UNMARKED_SECTION_RE = re.compile(
    r"(?m)^# Token-Context MCP: Lean Selective\b.*?(?=\n^# |\Z)",
    re.DOTALL,
)


def _format_marked_block(body: str) -> str:
    return f"{RULE_BEGIN_MARKER}\n{body.strip()}\n{RULE_END_MARKER}\n"


def upsert_marked_rule(target_file: Path, body: str = LEAN_RULE_BODY) -> str:
    """Insert or idempotently update the Lean Selective rule block inside ``target_file``."""
    block = _format_marked_block(body)
    if not target_file.exists():
        target_file.parent.mkdir(parents=True, exist_ok=True)
        header = "# Gemini Global Rules\n\n" if target_file.name.upper() == "GEMINI.MD" else ""
        target_file.write_text(f"{header}{block}", encoding="utf-8")
        return "created"

    existing = target_file.read_text(encoding="utf-8")
    if RULE_BEGIN_MARKER in existing and RULE_END_MARKER in existing:
        updated = _MARKED_BLOCK_RE.sub(lambda _: block, existing, count=1)
    elif "# Token-Context MCP: Lean Selective" in existing:
        updated = _UNMARKED_SECTION_RE.sub(lambda _: block.rstrip("\n"), existing, count=1)
        if not updated.endswith("\n"):
            updated += "\n"
    else:
        sep = "" if (not existing or existing.endswith("\n\n")) else ("\n" if existing.endswith("\n") else "\n\n")
        updated = f"{existing}{sep}{block}"

    target_file.write_text(updated, encoding="utf-8")
    return "updated"


def _write_workspace_rule(workspace_dir: Path, body: str = LEAN_RULE_BODY) -> tuple[Path, str]:
    rule_path = workspace_dir / ".agents" / "rules" / "token-context-lean.md"
    status = "updated" if rule_path.exists() else "created"
    rule_path.parent.mkdir(parents=True, exist_ok=True)
    rule_path.write_text(body.strip() + "\n", encoding="utf-8")
    return rule_path, status


def upsert_antigravity_mcp_config(
    mcp_config_path: Path,
    config_path: Path,
    *,
    python_executable: str | None = None,
    output_mode: str = "compact_text",
    enable_admin_tools: bool = False,
) -> str:
    """Register or update the ``token-context`` entry in Antigravity ``mcp_config.json``."""
    existed = mcp_config_path.exists()
    data: dict[str, Any] = {}
    if existed:
        raw_text = mcp_config_path.read_text(encoding="utf-8").strip()
        if raw_text:
            parsed = json.loads(raw_text)
            if not isinstance(parsed, dict):
                raise ValueError(f"Expected JSON object in {mcp_config_path}")
            data = parsed

    mcp_servers = data.get("mcpServers")
    if not isinstance(mcp_servers, dict):
        mcp_servers = {}
        data["mcpServers"] = mcp_servers

    existing_entry = mcp_servers.get("token-context")
    merged_entry: dict[str, Any] = dict(existing_entry) if isinstance(existing_entry, dict) else {}

    exe = python_executable or sys.executable
    args = [
        "-m",
        "token_context_mcp",
        "serve",
        "--transport",
        "stdio",
        "--config",
        str(config_path),
        "--schema-profile",
        "gemini_safe",
        "--output-mode",
        output_mode,
    ]
    if enable_admin_tools:
        args.append("--enable-admin-tools")

    merged_entry["command"] = exe
    merged_entry["args"] = args
    mcp_servers["token-context"] = merged_entry

    mcp_config_path.parent.mkdir(parents=True, exist_ok=True)
    mcp_config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return "updated" if existed else "created"


def install_lean_rules(
    *,
    config_path: Path | None = None,
    home_dir: Path | None = None,
    global_gemini: bool = True,
    global_claude: bool = False,
    registered_repos: bool = True,
    workspace_dirs: list[Path] | None = None,
    set_compact_text: bool = True,
    install_antigravity_mcp: bool = False,
    enable_admin_tools: bool = False,
) -> dict[str, Any]:
    """Install Lean Selective agent rules, configure ``compact_text``, and optionally register MCP."""
    cfg_path = (config_path or default_config_path()).resolve()
    home = (home_dir or Path.home()).resolve()

    cfg = load_config(cfg_path)
    if set_compact_text and cfg.server.output_mode != "compact_text":
        cfg = dataclasses.replace(cfg, server=dataclasses.replace(cfg.server, output_mode="compact_text"))
        save_config(cfg_path, cfg)

    updated_files: list[dict[str, str]] = []
    skipped_repos: list[str] = []
    seen_rule_paths: set[Path] = set()

    if global_gemini:
        target = (home / ".gemini" / "GEMINI.md").resolve()
        action = upsert_marked_rule(target)
        updated_files.append({"path": str(target), "kind": "global_gemini", "status": action})

    if global_claude:
        target = (home / ".claude" / "CLAUDE.md").resolve()
        action = upsert_marked_rule(target)
        updated_files.append({"path": str(target), "kind": "global_claude", "status": action})

    if registered_repos:
        for repo_id, repo in sorted(cfg.repositories.items()):
            root = repo.root
            if not root.is_dir():
                skipped_repos.append(repo_id)
                continue
            rule_path = (root / ".agents" / "rules" / "token-context-lean.md").resolve()
            if rule_path in seen_rule_paths:
                continue
            seen_rule_paths.add(rule_path)
            written_path, action = _write_workspace_rule(root)
            updated_files.append({"path": str(written_path), "kind": f"repo:{repo_id}", "status": action})

    for ws in workspace_dirs or []:
        ws_path = Path(ws).resolve()
        if not ws_path.is_dir():
            skipped_repos.append(str(ws))
            continue
        rule_path = (ws_path / ".agents" / "rules" / "token-context-lean.md").resolve()
        if rule_path in seen_rule_paths:
            continue
        seen_rule_paths.add(rule_path)
        written_path, action = _write_workspace_rule(ws_path)
        updated_files.append({"path": str(written_path), "kind": "workspace", "status": action})

    mcp_config_updated: str | None = None
    if install_antigravity_mcp:
        mcp_path = (home / ".gemini" / "config" / "mcp_config.json").resolve()
        eff_mode = "compact_text" if set_compact_text else load_config(cfg_path).server.output_mode
        if eff_mode == "auto":
            eff_mode = "text"
        mcp_action = upsert_antigravity_mcp_config(
            mcp_path,
            cfg_path,
            output_mode=eff_mode,
            enable_admin_tools=enable_admin_tools,
        )
        mcp_config_updated = str(mcp_path)
        updated_files.append({"path": mcp_config_updated, "kind": "antigravity_mcp", "status": mcp_action})

    final_cfg = load_config(cfg_path)
    return {
        "config_path": str(cfg_path),
        "output_mode": final_cfg.server.output_mode,
        "updated_files": updated_files,
        "skipped_repos": skipped_repos,
        "mcp_config_updated": mcp_config_updated,
    }

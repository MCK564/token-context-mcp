from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from token_context_mcp.agent_setup import (
    RULE_BEGIN_MARKER,
    RULE_END_MARKER,
    install_lean_rules,
)
from token_context_mcp.cli import build_parser, main as cli_main
from token_context_mcp.client_profile import OUTPUT_MODES, resolve_output_mode
from token_context_mcp.config import DEFAULT_BUDGET_PROFILES, load_config, save_config
from token_context_mcp.index.runner import build_index
from token_context_mcp.kernel import format_error
from token_context_mcp.ledger.service import LedgerService
from token_context_mcp.models import AppConfig, LedgerConfig, RepositoryConfig, ServerConfig
from token_context_mcp.output_schemas import TOOL_OUTPUT_SCHEMAS
from token_context_mcp.retrieve.serialization import ResultFinalizer, render_compact_text
from token_context_mcp.retrieve.service import RetrievalError, RetrievalService
from token_context_mcp.retrieve.token_budget import estimate_tokens
from token_context_mcp.retrieve.workflows import CompositeWorkflowEngine
from token_context_mcp.security.content_policy import is_hard_denied
from token_context_mcp.server import build_server


def _build_multi_symbol_repo(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "multi_repo"
    src = root / "src"
    src.mkdir(parents=True)
    for mod_idx in range(4):
        lines = [f"def helper_{mod_idx}_{fn_idx}(x: int) -> int:\n    return x + {fn_idx}\n" for fn_idx in range(8)]
        if mod_idx == 0:
            lines.append("from src.mod_1 import helper_1_0\n")
            lines.append("def entry_main(val: int) -> int:\n    return helper_1_0(val) + helper_0_0(val)\n")
        (src / f"mod_{mod_idx}.py").write_text("\n".join(lines), encoding="utf-8")

    cfg_path = tmp_path / "cfg" / "repos.toml"
    repo_cfg = RepositoryConfig(repo_id="demo", root=root.resolve())
    save_config(
        cfg_path,
        AppConfig(
            repositories={"demo": repo_cfg},
            server=ServerConfig(),
            ledger=LedgerConfig(enabled=True),
        ),
    )
    build_index(repo_cfg, cfg_path.parent / "indexes", network_policy="declared-deny-not-enforced")
    return root, cfg_path


def test_hard_deny_backup_virtualenvs_and_allow_legitimate_paths(tmp_path: Path) -> None:
    blocked = [
        ".venv_backup_20261013/Scripts/foo.py",
        ".venv311/lib/a.py",
        "venv-old/a.py",
        "venv_bak/a.py",
        "sub/.venv_test/x.py",
    ]
    for path in blocked:
        assert is_hard_denied(path) is True, path

    allowed = [
        "src/vendor/foo.py",
        "src/env_loader.py",
    ]
    for path in allowed:
        assert is_hard_denied(path) is False, path

    # End-to-end indexing verification: backup venv directories must never enter the index.
    root = tmp_path / "repo"
    (root / ".venv_backup_20261013" / "Scripts").mkdir(parents=True)
    (root / ".venv_backup_20261013" / "Scripts" / "foo.py").write_text("def venv_fn():\n    return 1\n", encoding="utf-8")
    (root / ".venv311" / "lib").mkdir(parents=True)
    (root / ".venv311" / "lib" / "a.py").write_text("def venv311_fn():\n    return 2\n", encoding="utf-8")
    (root / "venv-old").mkdir(parents=True)
    (root / "venv-old" / "a.py").write_text("def old_fn():\n    return 3\n", encoding="utf-8")
    (root / "src" / "vendor").mkdir(parents=True)
    (root / "src" / "vendor" / "foo.py").write_text("def vendor_fn():\n    return 4\n", encoding="utf-8")
    (root / "src" / "env_loader.py").write_text("def load_env():\n    return {}\n", encoding="utf-8")

    cfg_path = tmp_path / "cfg" / "repos.toml"
    repo_cfg = RepositoryConfig(repo_id="demo", root=root.resolve())
    save_config(cfg_path, AppConfig(repositories={"demo": repo_cfg}, server=ServerConfig()))
    manifest = build_index(repo_cfg, cfg_path.parent / "indexes", network_policy="declared-deny-not-enforced")
    assert manifest["files_indexed"] == 2

    svc = RetrievalService(load_config(cfg_path), cfg_path)
    assert svc.find_symbols("demo", pattern="venv_*")["data"]["symbols"] == []
    assert len(svc.find_symbols("demo", pattern="vendor_fn")["data"]["symbols"]) == 1
    assert len(svc.find_symbols("demo", pattern="load_env")["data"]["symbols"]) == 1


def test_budget_profiles_and_compact_text_config_and_cli(tmp_path: Path) -> None:
    assert DEFAULT_BUDGET_PROFILES["locate"]["budget_tokens"] == 1280
    assert DEFAULT_BUDGET_PROFILES["locate"]["limit"] == 20
    assert DEFAULT_BUDGET_PROFILES["orient"]["budget_tokens"] == 1024
    assert DEFAULT_BUDGET_PROFILES["orient"]["format"] == "compact"
    assert DEFAULT_BUDGET_PROFILES["impact"]["budget_tokens"] == 1536
    assert DEFAULT_BUDGET_PROFILES["impact"]["max_nodes"] == 120
    assert DEFAULT_BUDGET_PROFILES["impact"]["depth"] == 2
    assert DEFAULT_BUDGET_PROFILES["read"]["budget_tokens"] == 1536
    assert DEFAULT_BUDGET_PROFILES["read"]["include_body"] is True

    assert "compact_text" in OUTPUT_MODES
    assert resolve_output_mode("compact_text", None) == "compact_text"
    assert resolve_output_mode("compact_text", "claude-code") == "compact_text"

    cfg_path = tmp_path / "repos.toml"
    save_config(cfg_path, AppConfig(repositories={}, server=ServerConfig(output_mode="compact_text")))
    assert load_config(cfg_path).server.output_mode == "compact_text"

    args = build_parser().parse_args(["serve", "--output-mode", "compact_text"])
    assert args.output_mode == "compact_text"


def test_repo_map_grouped_format_omits_digests_by_default_and_shrinks_json(tmp_path: Path) -> None:
    _, cfg_path = _build_multi_symbol_repo(tmp_path)
    svc = RetrievalService(load_config(cfg_path), cfg_path)

    compact = svc.repo_map("demo", format="compact", budget_tokens=1024)
    grouped = svc.repo_map("demo", format="grouped", budget_tokens=1024)

    assert grouped["data"]["format"] == "grouped"
    assert "files" in grouped["data"]
    assert "symbols" not in grouped["data"]
    assert "file_digests" not in grouped["data"]
    assert "file_digests" not in compact["data"]
    assert grouped["budget"]["estimated_tokens"] <= 1024
    assert all(isinstance(path, str) and isinstance(entries, list) for path, entries in grouped["data"]["files"].items())
    assert all(isinstance(item, str) and ":L" in item for entries in grouped["data"]["files"].values() for item in entries)

    compact_len = len(json.dumps(compact, separators=(",", ":")))
    grouped_len = len(json.dumps(grouped, separators=(",", ":")))
    assert grouped_len < compact_len

    with_digests = svc.repo_map("demo", format="grouped", budget_tokens=1024, include_digests=True)
    assert with_digests["data"]["file_digests"]

    with pytest.raises(RetrievalError):
        svc.repo_map("demo", format="invalid")  # type: ignore[arg-type]


def test_status_slim_vs_verbose(tmp_path: Path) -> None:
    root, cfg_path = _build_multi_symbol_repo(tmp_path)
    (root / "src" / "new_unindexed.py").write_text("def brand_new():\n    return 42\n", encoding="utf-8")

    svc = RetrievalService(load_config(cfg_path), cfg_path)
    slim = svc.status("demo", verbose=False)
    full = svc.status("demo", verbose=True)

    assert slim["freshness"] == "stale"
    assert "edge_precision" not in slim
    assert "edge_precision" in full

    slim_data = slim["data"]
    for omitted_key in (
        "derived_defaults",
        "role_counts",
        "entry_points",
        "symbols_with_roles",
        "imports",
        "imported_by",
        "added_paths",
        "changed_non_indexed",
        "network_policy_status",
        "generated_at",
        "index_schema_version",
    ):
        assert omitted_key not in slim_data

    assert slim_data["files_indexed"] == full["data"]["files_indexed"]
    assert slim_data["symbols_indexed"] == full["data"]["symbols_indexed"]
    assert slim_data["edges_indexed"] == full["data"]["edges_indexed"]
    assert slim_data["pending_path_count"] == 0
    assert slim_data["added_path_count"] == 1
    assert len(json.dumps(slim, separators=(",", ":"))) < len(json.dumps(full, separators=(",", ":")))


def test_compact_text_finalizer_reduces_tokens_across_tools(tmp_path: Path) -> None:
    _, cfg_path = _build_multi_symbol_repo(tmp_path)
    cfg = load_config(cfg_path)
    svc = RetrievalService(cfg, cfg_path)
    wf = CompositeWorkflowEngine(svc)

    # Record a confirmed ledger card so prior_evidence renders in repo_map & search_source.
    entry_sym = svc.find_symbols("demo", pattern="entry_main")["data"]["symbols"][0]
    ledger = LedgerService(cfg, cfg_path)
    ledger.trajectory_record(
        repo_id="demo",
        query="entry main helper",
        answers=[f"{entry_sym['symbol_id']}@{entry_sym['start_line']}"],
        run_id="r1",
    )
    ledger.trajectory_record(
        repo_id="demo",
        query="entry main helper",
        answers=[f"{entry_sym['symbol_id']}@{entry_sym['start_line']}"],
        run_id="r2",
    )

    payloads = [
        svc.repo_map("demo", query="entry main helper", format="compact", budget_tokens=1024),
        svc.repo_map("demo", query="entry main helper", format="grouped", budget_tokens=1024),
        svc.file_skeleton("demo", path="src/mod_0.py", max_tokens=1024),
        svc.search_source("demo", query="entry_main helper", profile="locate"),
        svc.find_symbols("demo", pattern="helper_0_*", profile="locate"),
        svc.module_dependents("demo", path="src/mod_0.py"),
        svc.impact_slice("demo", symbol_id=entry_sym["symbol_id"], profile="impact"),
        svc.symbol_context("demo", symbol_id=entry_sym["symbol_id"], profile="read"),
        wf.inspect_symbol("demo", query="entry_main", view="normal"),
        svc.status("demo", verbose=False),
        svc.list_repositories(),
        format_error("unknown_repo_id", "call list_repositories first"),
    ]

    compact_finalizer = ResultFinalizer(output_mode="compact_text")
    text_finalizer = ResultFinalizer(output_mode="text")

    for payload in payloads:
        res_compact = compact_finalizer.finalize(payload)
        res_text = text_finalizer.finalize(payload)
        assert res_compact.structured_content is None
        compact_str = res_compact.content[0].text
        text_str = res_text.content[0].text
        assert compact_str.strip()
        assert estimate_tokens(compact_str) < estimate_tokens(text_str)

    # Spot-check specific compact_text structural lines.
    assert render_compact_text(format_error("unknown_repo_id", "missing")) == "ERROR unknown_repo_id: missing"
    grouped_text = compact_finalizer.finalize(payloads[1]).content[0].text
    assert "@ src/mod_0.py" in grouped_text
    assert "prior_evidence:" in grouped_text
    skel_text = compact_finalizer.finalize(payloads[2]).content[0].text
    assert "# src/mod_0.py (imports=" in skel_text
    assert "L1-L" in skel_text


def test_mcp_server_get_index_status_defaults_slim_and_compact_text_mode(tmp_path: Path) -> None:
    _, cfg_path = _build_multi_symbol_repo(tmp_path)

    from jsonschema import Draft202012Validator

    srv_struct = build_server(cfg_path)
    slim = asyncio.run(srv_struct.call_tool("get_index_status", {"repo_id": "demo"}))
    assert slim.structured_content is not None
    assert "derived_defaults" not in slim.structured_content["data"]
    assert "role_counts" not in slim.structured_content["data"]
    assert "edge_precision" not in slim.structured_content
    assert "added_path_count" in slim.structured_content["data"]
    Draft202012Validator(TOOL_OUTPUT_SCHEMAS["get_index_status"]).validate(slim.structured_content)

    full = asyncio.run(srv_struct.call_tool("get_index_status", {"repo_id": "demo", "verbose": True}))
    assert "derived_defaults" in full.structured_content["data"]
    assert "role_counts" in full.structured_content["data"]
    assert "edge_precision" in full.structured_content
    Draft202012Validator(TOOL_OUTPUT_SCHEMAS["get_index_status"]).validate(full.structured_content)

    grouped = asyncio.run(srv_struct.call_tool("get_repo_map", {"repo_id": "demo", "format": "grouped"}))
    assert "files" in grouped.structured_content["data"]
    Draft202012Validator(TOOL_OUTPUT_SCHEMAS["get_repo_map"]).validate(grouped.structured_content)

    srv_compact = build_server(cfg_path, output_mode="compact_text")
    compact_res = asyncio.run(srv_compact.call_tool("get_repo_map", {"repo_id": "demo", "format": "grouped"}))
    assert compact_res.structured_content is None
    assert compact_res.content[0].text.startswith("repo=demo freshness=fresh")
    assert "@ src/mod_" in compact_res.content[0].text


def test_install_lean_rules_idempotent_and_mcp_config(tmp_path: Path) -> None:
    repo_dir = tmp_path / "my_repo"
    repo_dir.mkdir(parents=True)
    cfg_path = tmp_path / "cfg" / "repos.toml"
    save_config(
        cfg_path,
        AppConfig(
            repositories={"demo": RepositoryConfig(repo_id="demo", root=repo_dir.resolve())},
            server=ServerConfig(output_mode="text"),
        ),
    )

    home_dir = tmp_path / "home"
    gemini_rule = home_dir / ".gemini" / "GEMINI.md"
    gemini_rule.parent.mkdir(parents=True)
    gemini_rule.write_text("# Gemini Global Rules\n- Keep responses concise.\n", encoding="utf-8")

    mcp_cfg = home_dir / ".gemini" / "config" / "mcp_config.json"
    mcp_cfg.parent.mkdir(parents=True)
    mcp_cfg.write_text(
        json.dumps({"mcpServers": {"other-server": {"command": "echo"}}}, indent=2),
        encoding="utf-8",
    )

    res1 = install_lean_rules(
        config_path=cfg_path,
        home_dir=home_dir,
        global_gemini=True,
        global_claude=True,
        registered_repos=True,
        set_compact_text=True,
        install_antigravity_mcp=True,
    )
    assert res1["output_mode"] == "compact_text"
    assert load_config(cfg_path).server.output_mode == "compact_text"

    gemini_text = gemini_rule.read_text(encoding="utf-8")
    assert "- Keep responses concise." in gemini_text
    assert gemini_text.count(RULE_BEGIN_MARKER) == 1
    assert gemini_text.count(RULE_END_MARKER) == 1

    claude_rule = home_dir / ".claude" / "CLAUDE.md"
    assert claude_rule.is_file()
    assert "# Token-Context MCP: Lean Selective" in claude_rule.read_text(encoding="utf-8")

    ws_rule = repo_dir / ".agents" / "rules" / "token-context-lean.md"
    assert ws_rule.is_file()
    assert "# Token-Context MCP: Lean Selective" in ws_rule.read_text(encoding="utf-8")

    parsed_mcp = json.loads(mcp_cfg.read_text(encoding="utf-8"))
    assert "other-server" in parsed_mcp["mcpServers"]
    tc_args = parsed_mcp["mcpServers"]["token-context"]["args"]
    assert "--output-mode" in tc_args and "compact_text" in tc_args

    # Calling a second time must remain idempotent without duplicating the block.
    install_lean_rules(
        config_path=cfg_path,
        home_dir=home_dir,
        global_gemini=True,
        global_claude=True,
        registered_repos=True,
        set_compact_text=True,
        install_antigravity_mcp=True,
    )
    gemini_text_2 = gemini_rule.read_text(encoding="utf-8")
    assert gemini_text_2.count(RULE_BEGIN_MARKER) == 1
    assert gemini_text_2.count(RULE_END_MARKER) == 1
    assert "- Keep responses concise." in gemini_text_2


def test_cli_install_rules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo_dir = tmp_path / "cli_repo"
    repo_dir.mkdir(parents=True)
    cfg_path = tmp_path / "repos.toml"
    save_config(
        cfg_path,
        AppConfig(
            repositories={"cli_repo": RepositoryConfig(repo_id="cli_repo", root=repo_dir.resolve())},
            server=ServerConfig(output_mode="text"),
        ),
    )
    fake_home = tmp_path / "fake_home"
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    rc = cli_main(["install-rules", "--config", str(cfg_path), "--antigravity-mcp"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["output_mode"] == "compact_text"
    assert (fake_home / ".gemini" / "GEMINI.md").is_file()
    assert (repo_dir / ".agents" / "rules" / "token-context-lean.md").is_file()
    assert (fake_home / ".gemini" / "config" / "mcp_config.json").is_file()

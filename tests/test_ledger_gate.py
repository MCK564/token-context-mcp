from __future__ import annotations

from pathlib import Path

from token_context_mcp.config import AppConfig, RepositoryConfig
from token_context_mcp.index.runner import build_index, database_path
from token_context_mcp.index.sqlite_store import SQLiteStore
from token_context_mcp.ledger.service import LedgerService


def _setup_repo(tmp_path: Path) -> tuple[Path, AppConfig, LedgerService, SQLiteStore]:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "mod.py").write_text(
        "def helper(x):\n"
        "    return x + 1\n\n"
        "def caller(y):\n"
        "    return helper(y)\n",
        encoding="utf-8",
    )
    cfg_path = tmp_path / "repos.toml"
    cfg_path.write_text("", encoding="utf-8")
    repo_cfg = RepositoryConfig(repo_id="demo", root=repo)
    cfg = AppConfig(repositories={"demo": repo_cfg})
    build_index(repo_cfg, tmp_path / "indexes", network_policy=cfg.server.network_policy)
    svc = LedgerService(cfg, cfg_path)
    idx = SQLiteStore(database_path(tmp_path / "indexes", "demo"), read_only=True)
    return repo, cfg, svc, idx


def test_gate_verifies_valid_answer_step_and_decoy(tmp_path: Path) -> None:
    _, _, svc, idx = _setup_repo(tmp_path)
    syms = {s.qualified_name: s for s in idx.symbols()}
    helper_id = syms["helper"].symbol_id
    caller_id = syms["caller"].symbol_id

    res = svc.trajectory_record(
        repo_id="demo",
        query="how does caller invoke helper",
        answers=[f"{helper_id}@2"],
        steps=[f"{caller_id}>{helper_id}@5"],
        decoys=[f"{caller_id}!wrapper_only"],
        agent_id="agent-1",
        run_id="run-1",
    )
    data = res["data"]
    assert data["status"] == "asserted"
    assert data["verified_count"] == 3
    assert data["answers"][0]["status"] == "verified"
    assert data["steps"][0]["status"] == "verified"
    assert data["decoys"][0]["status"] == "verified"
    assert "does" not in str(svc.show_card(data["card_id"])["sig_tokens"])


def test_gate_rejects_stale_file(tmp_path: Path) -> None:
    repo, _, svc, idx = _setup_repo(tmp_path)
    syms = {s.qualified_name: s for s in idx.symbols()}
    helper_id = syms["helper"].symbol_id

    # Modify file without re-indexing
    (repo / "mod.py").write_text(
        "def helper(x):\n"
        "    return x + 2\n\n"
        "def caller(y):\n"
        "    return helper(y)\n",
        encoding="utf-8",
    )
    res = svc.trajectory_record(
        repo_id="demo",
        query="helper value",
        answers=[f"{helper_id}@2"],
    )
    assert res["data"]["verified_count"] == 0
    assert res["data"]["answers"][0]["reason"] == "stale_file"

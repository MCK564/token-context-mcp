from __future__ import annotations

import json
from pathlib import Path

from token_context_mcp.cli import main
from token_context_mcp.config import AppConfig, RepositoryConfig
from token_context_mcp.index.runner import build_index, database_path
from token_context_mcp.index.sqlite_store import SQLiteStore
from token_context_mcp.ledger.service import LedgerService


def test_ledger_cli_lifecycle(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "mod.py").write_text("def hello():\n    return 42\n", encoding="utf-8")
    cfg_path = tmp_path / "repos.toml"
    cfg_path.write_text("", encoding="utf-8")
    repo_cfg = RepositoryConfig(repo_id="demo", root=repo)
    cfg = AppConfig(repositories={"demo": repo_cfg})
    build_index(repo_cfg, tmp_path / "indexes", network_policy=cfg.server.network_policy)
    idx = SQLiteStore(database_path(tmp_path / "indexes", "demo"), read_only=True)
    sid = idx.symbols()[0].symbol_id

    svc = LedgerService(cfg, cfg_path)
    rec = svc.trajectory_record("demo", "hello value", [f"{sid}@2"])
    cid = rec["data"]["card_id"]

    assert main(["ledger", "list", "--config", str(cfg_path)]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert len(listed["cards"]) == 1

    assert main(["ledger", "show", str(cid), "--config", str(cfg_path)]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["card_id"] == cid

    assert main(["ledger", "confirm", str(cid), "--config", str(cfg_path)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "confirmed"

    out_md = tmp_path / "export.md"
    assert main(["ledger", "export", "--format", "md", "--output", str(out_md), "--config", str(cfg_path)]) == 0
    assert out_md.exists()
    assert "Verified Evidence Ledger Export" in out_md.read_text(encoding="utf-8")
    capsys.readouterr()

    assert main(["ledger", "prune", "--config", str(cfg_path)]) == 0
    capsys.readouterr()

    assert main(["ledger", "forget", str(cid), "--config", str(cfg_path)]) == 0
    assert json.loads(capsys.readouterr().out)["deleted"] is True

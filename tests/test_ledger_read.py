from __future__ import annotations

import json
from pathlib import Path

from token_context_mcp.config import AppConfig, LedgerConfig, RepositoryConfig
from token_context_mcp.index.runner import build_index, database_path
from token_context_mcp.index.sqlite_store import SQLiteStore
from token_context_mcp.ledger.service import LedgerService
from token_context_mcp.retrieve.service import RetrievalService
from token_context_mcp.retrieve.token_budget import count_tokens_o200k


def _setup(tmp_path: Path, *, enabled: bool) -> tuple[Path, AppConfig, LedgerService, RetrievalService, dict[str, str]]:
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    src = repo / "mod.py"
    if not src.exists():
        src.write_text(
            "def alpha(x):\n"
            "    return x + 1\n\n"
            "def beta(y):\n"
            "    return alpha(y)\n\n"
            "def gamma(z):\n"
            "    return beta(z)\n",
            encoding="utf-8",
        )
    cfg_path = tmp_path / "repos.toml"
    cfg_path.write_text("", encoding="utf-8")
    repo_cfg = RepositoryConfig(repo_id="demo", root=repo)
    cfg = AppConfig(
        repositories={"demo": repo_cfg},
        ledger=LedgerConfig(enabled=enabled),
    )
    build_index(repo_cfg, tmp_path / "indexes", network_policy=cfg.server.network_policy)
    lsvc = LedgerService(cfg, cfg_path)
    rsvc = RetrievalService(cfg, cfg_path)
    idx = SQLiteStore(database_path(tmp_path / "indexes", "demo"), read_only=True)
    return repo, cfg, lsvc, rsvc, {s.qualified_name: s.symbol_id for s in idx.symbols()}


def test_disabled_ledger_is_byte_identical(tmp_path: Path) -> None:
    _, _, lsvc, rsvc_off, syms = _setup(tmp_path, enabled=False)
    res_before = rsvc_off.search_source("demo", query="alpha beta gamma", profile="locate")

    # Record a card into ledger.sqlite while ledger.enabled is False
    lsvc.trajectory_record(
        repo_id="demo",
        query="alpha beta gamma",
        answers=[f"{syms['alpha']}@2"],
        run_id="r1",
    )
    res_after = rsvc_off.search_source("demo", query="alpha beta gamma", profile="locate")
    assert json.dumps(res_before, sort_keys=True) == json.dumps(res_after, sort_keys=True)
    assert "prior_evidence" not in res_after["data"]
    assert "ledger_rev" not in res_after


def test_read_verification_prefix_and_mutations(tmp_path: Path) -> None:
    repo, _, lsvc, rsvc, syms = _setup(tmp_path, enabled=True)
    a_id, b_id, g_id = syms["alpha"], syms["beta"], syms["gamma"]

    lsvc.trajectory_record(
        repo_id="demo",
        query="gamma calls beta calls alpha",
        answers=[f"{a_id}@2"],
        steps=[f"{g_id}>{b_id}@8", f"{b_id}>{a_id}@5"],
        decoys=[f"{g_id}!wrapper_only"],
        run_id="run_1",
    )

    # Asserted card -> served with prior_evidence_unconfirmed, no decoys yet
    s1 = rsvc.search_source("demo", query="gamma calls beta calls alpha", profile="locate")
    pe1 = s1["data"]["prior_evidence"]
    assert pe1["status"] == "asserted"
    assert "prior_evidence_unconfirmed" in s1["warnings"]
    assert pe1["decoys"] == []
    assert count_tokens_o200k(json.dumps(pe1, separators=(",", ":")))[0] <= 150

    # Second run_id confirms -> decoys served, warning gone
    lsvc.trajectory_record(
        repo_id="demo",
        query="gamma calls beta calls alpha",
        answers=[f"{a_id}@2"],
        steps=[f"{g_id}>{b_id}@8", f"{b_id}>{a_id}@5"],
        decoys=[f"{g_id}!wrapper_only"],
        run_id="run_2",
    )
    m1 = rsvc.repo_map("demo", query="gamma calls beta calls alpha", format="compact")
    pe2 = m1["data"]["prior_evidence"]
    assert pe2["status"] == "confirmed"
    assert "prior_evidence_unconfirmed" not in m1["warnings"]
    assert len(pe2["decoys"]) == 1

    # Mutation 0 (un-reindexed shift): insert lines above alpha on disk WITHOUT re-indexing ->
    # shifted byte slice still verifies alpha body SHA-256!
    (repo / "mod.py").write_text(
        "# unindexed shift 1\n"
        "# unindexed shift 2\n"
        "def alpha(x):\n"
        "    return x + 1\n\n"
        "def beta(y):\n"
        "    return alpha(y)\n\n"
        "def gamma(z):\n"
        "    return beta(z)\n",
        encoding="utf-8",
    )
    rsvc_unindexed = RetrievalService(rsvc._cached_config, rsvc.config_path)
    s_unindexed = rsvc_unindexed.search_source("demo", query="gamma calls beta calls alpha", profile="locate")
    assert s_unindexed["data"]["prior_evidence"]["answers"][0][3] == "valid"

    # Contrastive Identifier Guard: sibling query substituting 'alpha' with 'delta' must NOT match card!
    s_collision = rsvc_unindexed.search_source("demo", query="gamma calls beta calls delta", profile="locate")
    assert "prior_evidence" not in s_collision["data"]

    # Mutation 1: insert lines above alpha + edit beta body (step 2) -> alpha still valid, recheck_from == 2!
    (repo / "mod.py").write_text(
        "# header comment 1\n"
        "# header comment 2\n"
        "def alpha(x):\n"
        "    return x + 1\n\n"
        "def beta(y):\n"
        "    return alpha(y + 10)\n\n"
        "def gamma(z):\n"
        "    return beta(z)\n",
        encoding="utf-8",
    )
    build_index(RepositoryConfig(repo_id="demo", root=repo), tmp_path / "indexes", network_policy="declared-deny-not-enforced")
    rsvc2 = RetrievalService(rsvc._cached_config, rsvc.config_path)
    s2 = rsvc2.search_source("demo", query="gamma calls beta calls alpha", profile="locate")
    pe3 = s2["data"]["prior_evidence"]
    assert pe3["answers"][0][3] == "valid"
    assert pe3["recheck_from"] == 2
    assert len(pe3["steps"]) == 1

    # Mutation 2: edit alpha body -> no valid answers -> retired and not served!
    (repo / "mod.py").write_text(
        "def alpha(x):\n"
        "    return x + 999\n\n"
        "def beta(y):\n"
        "    return alpha(y + 10)\n\n"
        "def gamma(z):\n"
        "    return beta(z)\n",
        encoding="utf-8",
    )
    build_index(RepositoryConfig(repo_id="demo", root=repo), tmp_path / "indexes", network_policy="declared-deny-not-enforced")
    rsvc3 = RetrievalService(rsvc._cached_config, rsvc.config_path)
    s3 = rsvc3.search_source("demo", query="gamma calls beta calls alpha", profile="locate")
    assert "prior_evidence" not in s3["data"]

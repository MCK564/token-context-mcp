"""End-to-End Governance Tests: Desktop GUI Controller controlling Live Server (G2)."""
from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("psutil")

from token_context_mcp.gui.bridge import AgentSecurityController
from token_context_mcp.server import build_server
from token_context_mcp.security.governance_store import GovernanceStore, merge_seen_agents


def test_gui_controls_server_e2e(indexed_config: Path) -> None:
    # 1. Build server and GUI controller sharing the same config/governance store
    server = build_server(indexed_config, enable_extensions=True, enable_admin_tools=True)
    ctrl = AgentSecurityController(indexed_config)

    try:
        # Initial call succeeds
        res0 = asyncio.run(server.call_tool("list_repositories", {}))
        assert "error" not in res0.structured_content

        # 2. GUI triggers emergency halt -> Server rejects tool calls within <= 1.1s
        t0 = time.perf_counter()
        ctrl.emergency_halt("E2E GUI Emergency Halt")

        halt_recognized = False
        while time.perf_counter() - t0 <= 1.2:
            res = asyncio.run(server.call_tool("list_repositories", {}))
            err = res.structured_content.get("error")
            if err and err.get("code") == "permission_revoked":
                halt_recognized = True
                break
            time.sleep(0.02)

        elapsed_halt = time.perf_counter() - t0
        print(f"\n[MEASUREMENT] E2E halt latency: {elapsed_halt:.4f}s")
        assert halt_recognized is True, f"Server failed to recognize GUI halt within 1.1s (took {elapsed_halt:.3f}s)"
        assert elapsed_halt <= 1.1, f"Halt propagation exceeded 1.1s SLA: {elapsed_halt:.3f}s"

        # 3. GUI triggers emergency resume -> Server accepts calls again within <= 1.1s
        t1 = time.perf_counter()
        ctrl.emergency_resume()

        resume_recognized = False
        while time.perf_counter() - t1 <= 1.2:
            res = asyncio.run(server.call_tool("list_repositories", {}))
            if "error" not in res.structured_content:
                resume_recognized = True
                break
            time.sleep(0.02)

        elapsed_resume = time.perf_counter() - t1
        print(f"\n[MEASUREMENT] E2E resume latency: {elapsed_resume:.4f}s")
        assert resume_recognized is True, f"Server failed to recognize GUI resume within 1.1s (took {elapsed_resume:.3f}s)"
        assert elapsed_resume <= 1.1, f"Resume propagation exceeded 1.1s SLA: {elapsed_resume:.3f}s"

        # 4. GUI pauses anonymous agent -> Server rejects anonymous call
        ctrl.pause_agent("anonymous", "Paused from GUI")
        # Give cache a short moment to refresh on server
        time.sleep(1.05)
        res_paused = asyncio.run(server.call_tool("list_repositories", {}))
        assert res_paused.structured_content["error"]["code"] == "permission_revoked"

        # Resume anonymous
        ctrl.resume_agent("anonymous")
        time.sleep(1.05)
        res_resumed = asyncio.run(server.call_tool("list_repositories", {}))
        assert "error" not in res_resumed.structured_content

    finally:
        ctrl.close()


def test_refresh_data_is_pure_query_no_mutation(indexed_config: Path) -> None:
    ctrl = AgentSecurityController(indexed_config)
    gov_db = indexed_config.parent / "governance.sqlite"

    try:
        # Pre-seed one agent in DB
        store = GovernanceStore(gov_db)
        store.upsert_agent("agent-test-1", "ACTIVE")

        with sqlite3.connect(str(gov_db)) as conn:
            count_before = conn.execute("SELECT COUNT(*) FROM agents;").fetchone()[0]

        # Call refresh_data multiple times
        ctrl.refresh_data()
        ctrl.refresh_data()

        with sqlite3.connect(str(gov_db)) as conn:
            count_after = conn.execute("SELECT COUNT(*) FROM agents;").fetchone()[0]

        assert count_after == count_before, "refresh_data must not insert or register agents in the DB"

    finally:
        ctrl.close()

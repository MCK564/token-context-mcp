"""Comprehensive regression tests for all bug fixes in v0.3.12."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
import time
import tomllib
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from token_context_mcp.config import (
    ConfigError,
    load_config,
    register_repository,
    save_config,
    unregister_repository,
)
from token_context_mcp.index.runner import (
    build_index,
    current_pointer_path,
    database_path,
    manifest_path,
)
from token_context_mcp.index.sqlite_store import ReadConnectionPool, SQLiteStore, StoreError
from token_context_mcp.ledger.service import LedgerService
from token_context_mcp.ledger.store import CardItemRecord, LedgerStore
from token_context_mcp.ledger.verify import LedgerVerifier
from token_context_mcp.memory.store import MemoryStore
from token_context_mcp.models import AppConfig, LedgerConfig, RepositoryConfig, ServerConfig
from token_context_mcp.retrieve.service import RetrievalError, RetrievalService
from token_context_mcp.security.access_control import PolicyProfile
from token_context_mcp.security.audit import AuditLogger
from token_context_mcp.security.governance_store import GovernanceStore
from token_context_mcp.security.path_policy import PathPolicyError
from token_context_mcp.server import build_server


def _make_repo(path: Path, code: str = "def alpha():\n    return 1\n") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "mod.py").write_text(code, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 1. Config, missing roots, and index runner validation
# ---------------------------------------------------------------------------


def test_missing_root_does_not_brick_config_or_unregister(tmp_path: Path) -> None:
    cfg_path = tmp_path / "repos.toml"
    good_root = _make_repo(tmp_path / "good")
    gone_root = _make_repo(tmp_path / "gone")

    register_repository(cfg_path, "good", good_root)
    register_repository(cfg_path, "gone", gone_root)
    idx_dir = cfg_path.parent / "indexes"
    build_index(load_config(cfg_path).repositories["good"], idx_dir, network_policy="declared-deny-not-enforced")
    build_index(load_config(cfg_path).repositories["gone"], idx_dir, network_policy="declared-deny-not-enforced")

    # Delete one repo directory from disk
    for p in gone_root.rglob("*"):
        if p.is_file():
            p.unlink()
    gone_root.rmdir()

    # load_config still succeeds so remaining repos & unregister keep working
    cfg = load_config(cfg_path)
    assert set(cfg.repositories) == {"good", "gone"}

    # Retrieval still works for 'good', but rejects 'gone' cleanly
    svc = RetrievalService(cfg, cfg_path)
    try:
        assert svc.status("good")["freshness"] == "fresh"
        with pytest.raises(PathPolicyError):
            svc.status("gone")
        with pytest.raises(PathPolicyError):
            build_index(cfg.repositories["gone"], cfg_path.parent / "indexes", network_policy="declared-deny-not-enforced")
    finally:
        svc.close()

    # Unregistering the missing repo succeeds
    unregister_repository(cfg_path, "gone")
    assert set(load_config(cfg_path).repositories) == {"good"}


def test_save_config_validates_server_limits(tmp_path: Path) -> None:
    cfg_path = tmp_path / "repos.toml"
    bad_cfg = AppConfig(repositories={}, server=ServerConfig(max_result_tokens=99999))
    with pytest.raises(ConfigError, match="max_result_tokens"):
        save_config(cfg_path, bad_cfg)
    assert not cfg_path.exists()


# ---------------------------------------------------------------------------
# 2. RetrievalService status, pointer cache invalidation, and Windows lock release
# ---------------------------------------------------------------------------


def test_status_on_unindexed_repo_returns_clean_error_not_internal_error(tmp_path: Path) -> None:
    cfg_path = tmp_path / "repos.toml"
    repo_root = _make_repo(tmp_path / "demo")
    register_repository(cfg_path, "demo", repo_root)

    svc = RetrievalService(load_config(cfg_path), cfg_path)
    try:
        with pytest.raises(RetrievalError, match="active index missing"):
            svc.status("demo")
    finally:
        svc.close()

    srv = build_server(cfg_path)
    try:
        res = asyncio.run(srv.call_tool("get_index_status", {"repo_id": "demo"}))
        err = res.structured_content["error"]
        assert err["code"] == "invalid_request"
    finally:
        srv.governance_store.close()
        srv.audit_logger.close()


def test_read_pool_missing_db_raises_store_error(tmp_path: Path) -> None:
    pool = ReadConnectionPool()
    with pytest.raises(StoreError, match="does not exist"):
        pool.get_connection(tmp_path / "missing.sqlite")


def test_pointer_cache_picks_up_immediate_reindex_with_zero_delay(tmp_path: Path) -> None:
    cfg_path = tmp_path / "repos.toml"
    repo_root = _make_repo(tmp_path / "demo", "def first_fn():\n    return 1\n")
    register_repository(cfg_path, "demo", repo_root)
    idx_dir = cfg_path.parent / "indexes"
    repo_cfg = load_config(cfg_path).repositories["demo"]
    build_index(repo_cfg, idx_dir, network_policy="declared-deny-not-enforced")

    svc = RetrievalService(load_config(cfg_path), cfg_path)
    try:
        r1 = svc.find_symbols("demo", pattern="first_fn")
        assert len(r1["data"]["symbols"]) == 1

        # Immediately re-index within < 50ms (far below old 1.0s TTL)
        (repo_root / "mod.py").write_text("def second_fn():\n    return 2\n", encoding="utf-8")
        build_index(repo_cfg, idx_dir, network_policy="declared-deny-not-enforced", full_rebuild=True)

        r2 = svc.find_symbols("demo", pattern="second_fn")
        assert len(r2["data"]["symbols"]) == 1
        assert svc.find_symbols("demo", pattern="first_fn")["data"]["symbols"] == []
    finally:
        svc.close()


# ---------------------------------------------------------------------------
# 3. LedgerStore.close, LedgerVerifier cache isolation, LedgerService hot-reload
# ---------------------------------------------------------------------------


def test_ledger_store_close_and_verifier_cache_isolation(tmp_path: Path) -> None:
    cfg_path = tmp_path / "repos.toml"
    repo_a = _make_repo(tmp_path / "repo_a", "def shared_name():\n    return 'a'\n")
    repo_b = _make_repo(tmp_path / "repo_b", "def shared_name():\n    return 'b'\n")
    register_repository(cfg_path, "repo-a", repo_a)

    idx_dir = cfg_path.parent / "indexes"
    cfg = load_config(cfg_path)
    build_index(cfg.repositories["repo-a"], idx_dir, network_policy="declared-deny-not-enforced")

    # LedgerService hot-reloads repo-b registered after LedgerService creation
    lsvc = LedgerService(cfg, cfg_path)
    try:
        register_repository(cfg_path, "repo-b", repo_b)
        cfg2 = load_config(cfg_path)
        build_index(cfg2.repositories["repo-b"], idx_dir, network_policy="declared-deny-not-enforced")

        store_a = SQLiteStore(database_path(idx_dir, "repo-a"), read_only=True)
        store_b = SQLiteStore(database_path(idx_dir, "repo-b"), read_only=True)
        sym_a = store_a.find_symbols("shared_name")[0]
        sym_b = store_b.find_symbols("shared_name")[0]

        res_a = lsvc.trajectory_record("repo-a", "find shared name a", [f"{sym_a.symbol_id}@{sym_a.start_line}"])
        res_b = lsvc.trajectory_record("repo-b", "find shared name b", [f"{sym_b.symbol_id}@{sym_b.start_line}"])
        assert res_a["data"]["status"] == "asserted"
        assert res_b["data"]["status"] == "asserted"

        verifier = LedgerVerifier()
        pe_a, _, _ = verifier.lookup_prior_evidence(
            repo_id="repo-a",
            query="find shared name a",
            ledger_store=lsvc.store,
            idx_store=store_a,
            root=repo_a.resolve(),
            allow_symlinks=False,
            cfg=LedgerConfig(),
        )
        pe_b, _, _ = verifier.lookup_prior_evidence(
            repo_id="repo-b",
            query="find shared name b",
            ledger_store=lsvc.store,
            idx_store=store_b,
            root=repo_b.resolve(),
            allow_symlinks=False,
            cfg=LedgerConfig(),
        )
        assert pe_a is not None and pe_b is not None
        assert pe_a["answers"][0][0] == sym_a.symbol_id
        assert pe_b["answers"][0][0] == sym_b.symbol_id
        # Verify cache keys use actual DB paths (not empty string)
        assert all(k[0] != "" for k in verifier._idx_path_cache)
    finally:
        lsvc.close()


# ---------------------------------------------------------------------------
# 4. AuditLogger concurrency & MemoryStore.force_release_lock
# ---------------------------------------------------------------------------


def test_audit_logger_concurrent_writes_and_queries(tmp_path: Path) -> None:
    logger = AuditLogger(tmp_path / "audit.sqlite")
    errors: list[BaseException] = []

    def writer() -> None:
        try:
            for i in range(40):
                logger.log("search_source", f"agent-{i % 3}", "SUCCESS", 1.5, {"i": i})
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    def reader() -> None:
        try:
            for _ in range(15):
                logger.query_logs(limit=10)
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    logger.close()
    assert errors == []


def test_memory_force_release_lock(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite")
    acq = store.lock("res-1", "agent-a", timeout_sec=60)
    assert acq["acquired"] is True
    assert store.force_release_lock("res-1") is True
    assert store.force_release_lock("res-1") is False
    assert store.list_active_locks() == []


# ---------------------------------------------------------------------------
# 5. GUI / Qt tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def _qt_reset():
    pyside6 = pytest.importorskip("PySide6")
    pytest.importorskip("psutil")
    del pyside6
    from token_context_mcp.gui.workers import reset_workers_for_tests

    reset_workers_for_tests()
    yield


@pytest.fixture()
def qapp(_qt_reset):
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


def _pump_until(predicate, timeout: float = 30.0) -> bool:
    from PySide6.QtWidgets import QApplication

    deadline = time.monotonic() + timeout
    app = QApplication.instance()
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_index_process_full_flag_and_failed_to_start(qapp, tmp_path: Path) -> None:
    from token_context_mcp.gui.bridge import IndexProcess

    cfg_path = tmp_path / "repos.toml"
    proc_full = IndexProcess("demo", cfg_path, full=True)
    _, args = proc_full.build_command()
    assert "--full" in args

    bad_proc = IndexProcess("demo", cfg_path, command=("Z:/nonexistent_binary_12345.exe", []))
    failed: list[tuple[str, str]] = []
    bad_proc.index_failed.connect(lambda r, e: failed.append((r, e)))
    bad_proc.start()
    assert _pump_until(lambda: bool(failed), 10)
    assert failed[0][0] == "demo"
    assert not bad_proc._timer.isActive()


def test_repositories_tab_reindex_full_rebuild_all_cancel_and_failure_unlock(qapp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtWidgets import QMessageBox
    from token_context_mcp.gui.bridge import IndexProcess, RepoManager
    from token_context_mcp.gui.widgets.repositories_tab import RepositoriesTab
    from token_context_mcp.gui.workers import wait_idle

    cfg_path = tmp_path / "repos.toml"
    repo_a = _make_repo(tmp_path / "repo_a", "def fn_a():\n    return 1\n")
    repo_b = _make_repo(tmp_path / "repo_b", "def fn_b():\n    return 2\n")

    mgr = RepoManager(cfg_path)
    mgr.add_repository("repo-a", repo_a)
    mgr.add_repository("repo-b", repo_b)

    tab = RepositoriesTab(mgr)
    tab.show()
    tab.refresh()
    assert wait_idle()
    assert len(tab.model.rows()) == 2

    # 1. Click Re-index on selected row (incremental)
    tab.table.selectRow(0)
    finished: list[tuple[str, bool, str]] = []
    tab.indexing_finished.connect(lambda r, ok, msg: finished.append((r, ok, msg)))
    tab.reindex_sel_btn.click()
    assert _pump_until(lambda: len(finished) == 1 and not tab.isIndexing(), 60)
    assert finished[-1][0] == "repo-a" and finished[-1][1] is True
    assert tab.reindex_sel_btn.isEnabled() is True
    assert tab.cancel_btn.isEnabled() is False

    # 2. Click Full Rebuild on selected row
    tab.table.selectRow(0)
    tab.full_rebuild_btn.click()
    assert _pump_until(lambda: len(finished) == 2 and not tab.isIndexing(), 60)
    assert finished[-1][1] is True

    # 3. Click Re-index All (uses model.rows())
    tab.reindex_all_btn.click()
    assert _pump_until(lambda: len(finished) == 4 and not tab.isIndexing(), 90)
    assert all(ok for _, ok, _ in finished[-2:])
    assert wait_idle()
    assert {r["status"] for r in tab.model.rows()} == {"FRESH"}

    # 4. Failure recovery: broken command must unlock UI and show Failed status
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Ok)
    orig_init = IndexProcess.__init__

    def failing_init(self, repo_id, config_path=None, parent=None, *, all_repos=False, full=False, command=None):
        orig_init(self, repo_id, config_path, parent=parent, all_repos=all_repos, full=full, command=("Z:/missing_indexer_exe.exe", []))

    monkeypatch.setattr(IndexProcess, "__init__", failing_init)
    tab.table.selectRow(0)
    tab.reindex_sel_btn.click()
    assert _pump_until(lambda: len(finished) == 5 and not tab.isIndexing(), 15)
    assert finished[-1][1] is False
    assert tab.reindex_sel_btn.isEnabled() is True
    assert tab.progress_card.isVisible() is True
    assert "Failed" in tab.progress_status.text()

    # 5. Cancel button stops a running job and unlocks UI
    def sleeping_init(self, repo_id, config_path=None, parent=None, *, all_repos=False, full=False, command=None):
        orig_init(
            self,
            repo_id,
            config_path,
            parent=parent,
            all_repos=all_repos,
            full=full,
            command=(sys.executable, ["-c", "import time; time.sleep(30)"]),
        )

    monkeypatch.setattr(IndexProcess, "__init__", sleeping_init)
    tab.table.selectRow(0)
    tab.reindex_sel_btn.click()
    assert _pump_until(lambda: tab.isIndexing() and tab._proc is not None and tab._proc.isRunning(), 10)
    tab.cancel_btn.click()
    assert _pump_until(lambda: len(finished) == 6 and not tab.isIndexing(), 15)
    assert finished[-1][1] is False
    assert finished[-1][2] == "Cancelled"
    assert tab.reindex_sel_btn.isEnabled() is True


def test_add_repo_dialog_validates_id_and_suggests_valid_id(qapp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from token_context_mcp.gui.widgets.repositories_tab import AddRepoDialog

    weird_dir = tmp_path / "123_My.App!"
    weird_dir.mkdir()

    dlg = AddRepoDialog()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(weird_dir))
    dlg._browse()
    suggested = dlg.repo_id_input.text()
    assert suggested.startswith("repo-")
    assert dlg.values()[0] == suggested

    warnings: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, title, msg: warnings.append(msg))
    dlg.repo_id_input.setText("Invalid_Upper")
    dlg._accept_validated()
    assert len(warnings) == 1
    assert dlg.result() == 0

    dlg.repo_id_input.setText("valid_repo-1")
    dlg._accept_validated()
    assert dlg.result() == AddRepoDialog.DialogCode.Accepted


def test_repo_manager_releases_locks_and_purges_all_snapshot_artifacts(tmp_path: Path) -> None:
    from token_context_mcp.gui.bridge import RepoManager

    cfg_path = tmp_path / "repos.toml"
    repo_dir = _make_repo(tmp_path / "demo")
    mgr = RepoManager(cfg_path)
    mgr.add_repository("demo", repo_dir)
    build_index(load_config(cfg_path).repositories["demo"], mgr.get_index_dir(), network_policy="declared-deny-not-enforced")

    # list_repositories must close its RetrievalService pool so files can be deleted immediately on Windows
    rows = mgr.list_repositories(force_refresh=True)
    assert len(rows) == 1
    assert rows[0]["status"] == "FRESH"
    assert rows[0]["edges_count"] >= 0

    idx_dir = mgr.get_index_dir()
    assert list(idx_dir.glob("demo*.sqlite"))
    assert current_pointer_path(idx_dir, "demo").is_file()
    assert manifest_path(idx_dir, "demo").is_file()

    mgr.delete_repository("demo", purge_db=True)
    assert list(idx_dir.glob("demo*")) == []


def test_cache_manager_legacy_classification_and_immediate_clean(qapp, tmp_path: Path) -> None:
    from token_context_mcp.gui.bridge import CacheManager, RepoManager
    from token_context_mcp.gui.widgets.cache_tab import CacheTab
    from token_context_mcp.gui.workers import wait_idle

    cfg_path = tmp_path / "repos.toml"
    repo_dir = _make_repo(tmp_path / "demo", "def a():\n    return 1\n")
    mgr = RepoManager(cfg_path)
    mgr.add_repository("demo", repo_dir)
    idx_dir = mgr.get_index_dir()
    repo_cfg = load_config(cfg_path).repositories["demo"]

    build_index(repo_cfg, idx_dir, network_policy="declared-deny-not-enforced")
    (repo_dir / "mod.py").write_text("def b():\n    return 2\n", encoding="utf-8")
    build_index(repo_cfg, idx_dir, network_policy="declared-deny-not-enforced")

    cache = CacheManager(cfg_path)
    stats = cache.get_storage_stats()
    statuses = {d["file_name"]: d["status"] for d in stats["databases"]}
    assert "ACTIVE" in statuses.values()
    assert "SUPERSEDED" in statuses.values()
    assert statuses.get("demo.sqlite") == "LEGACY"

    # clean_stale_snapshots removes SUPERSEDED snapshots immediately (max_age=0)
    removed = cache.clean_stale_snapshots()
    assert any(name.startswith("demo.run_") and name.endswith(".sqlite") for name in removed)

    tab = CacheTab(mgr)
    tab.refresh()
    assert wait_idle()
    tab.stale_only_chk.setChecked(True)
    # LEGACY & ACTIVE are excluded when showing stale/orphan only
    assert tab.table.rowCount() == 0


def test_ledger_controller_memory_entries_and_ledger_tab_filter(qapp, tmp_path: Path) -> None:
    from token_context_mcp.gui.bridge import LedgerController, RepoManager
    from token_context_mcp.gui.widgets.ledger_tab import LedgerTab
    from token_context_mcp.gui.workers import wait_idle

    cfg_path = tmp_path / "repos.toml"
    _make_repo(tmp_path / "demo")
    mgr = RepoManager(cfg_path)
    mgr.add_repository("demo", tmp_path / "demo")

    mem = MemoryStore(cfg_path.parent / "memory.sqlite")
    mem.put("arch-note", {"summary": "hello"}, scope="project", namespace="ns1", ttl=3600)
    mem.put("expired-note", "old", scope="session", namespace="ns2", ttl=1)
    with mem._connection() as conn:
        conn.execute("UPDATE key_values SET expires_at = ? WHERE key = 'expired-note'", (time.time() - 60.0,))

    ctrl = LedgerController(cfg_path)
    entries = ctrl.list_memory_entries()
    assert len(entries) == 1
    assert entries[0]["key"] == "arch-note"
    assert "project/ns1" == entries[0]["namespace"]

    tab = LedgerTab(mgr)
    tab.refresh()
    assert wait_idle()
    assert tab.memory_table.rowCount() == 1

    # Changing filter updates _selected_repo_filter for subsequent fetch()
    tab.repo_filter.setCurrentText("demo")
    assert wait_idle()
    assert tab._selected_repo_filter == "demo"


def test_agents_tab_actions_and_governance_merge(qapp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtWidgets import QMessageBox
    from token_context_mcp.gui.bridge import AgentSecurityController, RepoManager
    from token_context_mcp.gui.widgets.agents_tab import AgentsTab
    from token_context_mcp.gui.workers import wait_idle

    cfg_path = tmp_path / "repos.toml"
    mgr = RepoManager(cfg_path)
    ctrl = AgentSecurityController(cfg_path)
    try:
        ctrl._memory_store.lock("file://a.py", "worker-1", timeout_sec=60)
        ctrl.access_control.register_agent("worker-1", role="coder")
        gov = GovernanceStore(cfg_path.parent / "governance.sqlite")
        gov.upsert_agent("worker-2", status="ACTIVE", policy="")

        tab = AgentsTab(ctrl, mgr)
        tab.refresh()
        assert wait_idle()

        # Live worker signal merge should not raise KeyError even when DB policy is ""
        ctrl._on_governance_agents(gov.list_agents())
        assert tab.agents_table.rowCount() >= 2

        # Select worker-1 and test Pause -> Resume
        for row in range(tab.agents_table.rowCount()):
            if tab.agents_table.item(row, 0).text() == "worker-1":
                tab.agents_table.selectRow(row)
                break
        tab._on_toggle_pause_selected()
        assert wait_idle()
        assert ctrl.access_control.get_agent_state("worker-1").value == "PAUSED"
        tab._on_toggle_pause_selected()
        assert wait_idle()
        assert ctrl.access_control.get_agent_state("worker-1").value == "ACTIVE"

        # Test Block -> Unblock
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Yes)
        tab._on_toggle_block_selected()
        assert wait_idle()
        assert ctrl.access_control.get_agent_state("worker-1").value == "BLOCKED"
        tab._on_toggle_block_selected()
        assert wait_idle()
        assert ctrl.access_control.get_agent_state("worker-1").value == "ACTIVE"

        # Test Apply Policy
        tab.policy_combo.setCurrentText("READ_ONLY")
        tab._on_apply_policy_selected()
        assert wait_idle()
        assert ctrl.access_control.get_agent_policy("worker-1") == PolicyProfile.READ_ONLY

        # Test Force Release Selected Lock
        assert tab.locks_table.rowCount() == 1
        tab.locks_table.selectRow(0)
        tab._on_release_selected_lock()
        assert wait_idle()
        assert tab.locks_table.rowCount() == 0
    finally:
        ctrl.close()


def test_dashboard_tasks_settings_and_overlay_fixes(qapp, tmp_path: Path) -> None:
    from token_context_mcp.gui.bridge import RepoManager, ServerController
    from token_context_mcp.gui.main_window import MainWindow
    from token_context_mcp.gui.widgets.dashboard_tab import CopyConfigDialog, DashboardTab
    from token_context_mcp.gui.widgets.loading_overlay import LoadingOverlay
    from token_context_mcp.gui.widgets.settings_tab import SettingsTab
    from token_context_mcp.gui.widgets.tasks_tab import TasksTab
    from token_context_mcp.gui.workers import wait_idle

    cfg_path = tmp_path / "repos.toml"
    mgr = RepoManager(cfg_path)
    ctrl = ServerController(cfg_path)

    # Dashboard ambiguity ratio scaling & last_seen formatting
    dash = DashboardTab(mgr, ctrl)
    dash.render({
        "hw": "CPU Only",
        "servers": [{
            "server_id": "srv-1",
            "pid": 1234,
            "client_name": "antigravity",
            "output_mode": "compact_text",
            "schema_profile": "gemini_safe",
            "last_seen": "2026-11-25T10:00:00+00:00",
        }],
        "repos": [{
            "repo_id": "demo",
            "files_count": 10,
            "db_size_mb": 1.2,
            "edges_count": 100,
            "ambiguous_rate": 0.159,
        }],
        "ledger_cards": 2,
    })
    assert dash.stat_ambig.text() == "15.9%"
    assert dash.srv_table.item(0, 5).text() != "-"

    # CopyConfigDialog codex TOML + compact_text + admin + agent_id
    copy_dlg = CopyConfigDialog(ctrl)
    copy_dlg.client_combo.setCurrentText("codex")
    copy_dlg.chk_compact.setChecked(True)
    copy_dlg.chk_admin.setChecked(True)
    copy_dlg.agent_id_input.setText("codex-worker")
    parsed = tomllib.loads(copy_dlg.preview.toPlainText())
    args = parsed["mcp_servers"]["token-context"]["args"]
    assert "--output-mode" in args and "compact_text" in args
    assert "--enable-admin-tools" in args
    assert parsed["mcp_servers"]["token-context"]["env"]["TOKEN_CONTEXT_AGENT_ID"] == "codex-worker"

    # TasksTab resolved percentage scaling (0.159 -> 84%)
    tasks = TasksTab(mgr)
    tasks._cached_repos = [{"repo_id": "demo", "languages": ["python"], "ambiguous_rate": 0.159}]
    tasks._apply_repo_meta("demo")
    assert tasks.precision_bar.value() == 84

    # SettingsTab spinbox caps match config._validate_server
    settings = SettingsTab(mgr)
    assert settings.spin_tokens.maximum() == 8192
    assert settings.spin_req_bytes.maximum() == 1_048_576
    assert settings.spin_nodes.maximum() == 500
    assert settings.spin_symbols.maximum() == 100

    # LoadingOverlay timer only runs when visible
    overlay = LoadingOverlay()
    assert not overlay.spinner._timer.isActive()
    overlay.show_loading("Working...")
    assert overlay.spinner._timer.isActive()
    overlay.hide_loading()
    assert not overlay.spinner._timer.isActive()

    # MainWindow active_servers_updated signal updates Dashboard table live
    win = MainWindow(config_path=cfg_path)
    try:
        wait_idle()
        win.security_ctrl.active_servers_updated.emit([
            {"server_id": "live-srv", "pid": 555, "client_name": "antigravity", "output_mode": "compact_text", "schema_profile": "gemini_safe", "last_seen": "2026-11-25T10:05:00+00:00"}
        ])
        assert win.tab_dashboard.srv_table.rowCount() == 1
        assert win.tab_dashboard.srv_table.item(0, 0).text() == "live-srv"
    finally:
        win.close()

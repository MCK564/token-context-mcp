"""M8: the GUI never blocks its event loop.

Hard checks: refresh does no SQLite / manifest / hardware I/O on the UI thread; indexing runs in a child process and
Cancel kills the whole tree; VACUUM never touches index snapshots; the repo badges are honest.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("psutil")
pytest.importorskip("PySide6")

import psutil  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from token_context_mcp.gui import bridge  # noqa: E402
from token_context_mcp.gui.bridge import (  # noqa: E402
    CacheManager,
    IndexProcess,
    RepoManager,
    ServerController,
    SystemMonitor,
    classify_repo,
    kill_process_tree,
)
from token_context_mcp.gui.models import RepoTableModel  # noqa: E402
from token_context_mcp.gui.perf import EventLoopWatchdog  # noqa: E402
from token_context_mcp.gui.workers import is_ui_thread, pending_count, run_async, wait_idle  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    return app


@pytest.fixture
def env(qapp):
    with tempfile.TemporaryDirectory(prefix="tcmcp_m8_", ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        config_path = root / "repos.toml"
        repo_dir = root / "repo-a"
        (repo_dir / "pkg").mkdir(parents=True)
        (repo_dir / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (repo_dir / "pkg" / "mod.py").write_text("def alpha():\n    return beta()\n\n\ndef beta():\n    return 1\n", encoding="utf-8")
        (repo_dir / "README.md").write_text("# a\n", encoding="utf-8")
        yield config_path, repo_dir


def cli_index(config_path: Path, repo_id: str | None = None, *extra: str) -> subprocess.CompletedProcess:
    args = [sys.executable, "-m", "token_context_mcp", "index", "--config", str(config_path)]
    args += ["--repo-id", repo_id] if repo_id else []
    args += list(extra)
    return subprocess.run(args, capture_output=True, text=True, timeout=150)


def pump_until(predicate, timeout=30.0):
    deadline = time.monotonic() + timeout
    app = QApplication.instance()
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


# ---- M8.1 run_async -----------------------------------------------------------------------------------------------
def test_run_async_runs_off_ui_thread_and_delivers_on_it(qapp):
    seen = {}

    def work(x):
        seen["worker_is_ui"] = is_ui_thread()
        return x * 2

    def ok(v):
        seen["ok_is_ui"] = is_ui_thread()
        seen["value"] = v

    run_async(work, 21, on_ok=ok)
    assert wait_idle()
    assert seen == {"worker_is_ui": False, "ok_is_ui": True, "value": 42}


def test_run_async_error_path(qapp):
    seen = {}

    def boom():
        raise RuntimeError("nope")

    run_async(boom, on_ok=lambda v: seen.setdefault("ok", v), on_err=lambda e: seen.update(err=str(e), ui=is_ui_thread()))
    assert wait_idle()
    assert seen == {"err": "nope", "ui": True}
    assert pending_count() == 0


def test_pool_is_capped_at_four(qapp):
    from PySide6.QtCore import QThreadPool

    run_async(lambda: None)
    wait_idle()
    assert QThreadPool.globalInstance().maxThreadCount() == 4


# ---- M8.2 refresh does no I/O on the UI thread ----------------------------------------------------------------------
def test_tab_refresh_does_no_io_on_ui_thread(qapp, env, monkeypatch):
    from token_context_mcp.gui.main_window import MainWindow

    config_path, repo_dir = env
    RepoManager(config_path).add_repository("repo-a", repo_dir)
    assert cli_index(config_path, "repo-a").returncode == 0

    window = MainWindow(config_path=config_path)
    wait_idle()
    ui_calls: list[str] = []
    worker_calls: list[str] = []

    def guard(label, fn):
        def wrapper(*a, **k):
            (ui_calls if is_ui_thread() else worker_calls).append(label)
            return fn(*a, **k)

        return wrapper

    monkeypatch.setattr(RepoManager, "list_repositories", guard("list_repositories", RepoManager.list_repositories))
    monkeypatch.setattr(RepoManager, "repo_detail", guard("repo_detail", RepoManager.repo_detail))
    monkeypatch.setattr(RepoManager, "get_server_config", guard("get_server_config", RepoManager.get_server_config))
    monkeypatch.setattr(RepoManager, "fetch_active_servers", guard("fetch_active_servers", RepoManager.fetch_active_servers))
    monkeypatch.setattr(CacheManager, "get_storage_stats", guard("get_storage_stats", CacheManager.get_storage_stats))
    monkeypatch.setattr(bridge.AgentSecurityController, "collect_snapshot", guard("collect_snapshot", bridge.AgentSecurityController.collect_snapshot))
    monkeypatch.setattr(bridge, "detect_ai_hardware", guard("detect_ai_hardware", bridge.detect_ai_hardware))
    real_connect = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", guard("sqlite3.connect", real_connect))
    real_read_text = Path.read_text
    monkeypatch.setattr(Path, "read_text", guard("Path.read_text", real_read_text))

    for idx in (0, 1, 2, 3, 4, 5, 0):
        window._on_nav_clicked(idx)
        assert wait_idle()
        pump_until(lambda: pending_count() == 0, 5)
    window._manual_refresh_current_tab()
    assert wait_idle()

    assert ui_calls == [], f"I/O on the UI thread: {sorted(set(ui_calls))}"
    assert {"list_repositories", "get_storage_stats", "collect_snapshot", "get_server_config"} <= set(worker_calls)
    window.close()


def test_repositories_tab_renders_indexed_repo(qapp, env):
    from token_context_mcp.gui.widgets.repositories_tab import RepositoriesTab

    config_path, repo_dir = env
    mgr = RepoManager(config_path)
    mgr.add_repository("repo-a", repo_dir)
    assert cli_index(config_path, "repo-a").returncode == 0
    tab = RepositoriesTab(mgr)
    tab.refresh()
    assert wait_idle()
    row = tab.model.row_at(0)
    assert row["status"] == "FRESH"
    assert row["symbols_count"] >= 2
    assert not hasattr(tab, "setCellWidget")
    # no widgets embedded in cells (M8.6)
    assert tab.table.indexWidget(tab.model.index(0, 2)) is None


# ---- M8.5 honest status ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "status,expected",
    [
        (None, "NOT_INDEXED"),
        ({"index_schema_version": "1.0", "freshness": "fresh"}, "SCHEMA_OUTDATED"),
        ({"index_schema_version": "2.4", "freshness": "fresh", "pending_path_count": 3}, "STALE"),
        ({"index_schema_version": "2.4", "freshness": "stale", "pending_path_count": 0}, "STALE"),
        ({"index_schema_version": "2.4", "freshness": "fresh", "pending_path_count": 0, "changed_non_indexed": ["README.md"]}, "DOCS_CHANGED"),
        ({"index_schema_version": "2.4", "freshness": "fresh", "pending_path_count": 0, "changed_non_indexed": []}, "FRESH"),
    ],
)
def test_classify_repo(status, expected):
    assert classify_repo(status) == expected


def test_badges_end_to_end(qapp, env):
    config_path, repo_dir = env
    mgr = RepoManager(config_path)
    mgr.add_repository("repo-a", repo_dir)
    assert mgr.list_repositories(force_refresh=True)[0]["status"] == "NOT_INDEXED"
    assert cli_index(config_path, "repo-a").returncode == 0
    assert mgr.list_repositories(force_refresh=True)[0]["status"] == "FRESH"

    (repo_dir / "README.md").write_text("# a changed\n", encoding="utf-8")
    assert mgr.list_repositories(force_refresh=True)[0]["status"] == "DOCS_CHANGED"

    (repo_dir / "pkg" / "mod.py").write_text("def alpha():\n    return 2\n", encoding="utf-8")
    assert mgr.list_repositories(force_refresh=True)[0]["status"] == "STALE"

    assert cli_index(config_path, "repo-a").returncode == 0
    (repo_dir / "pkg" / "new.py").write_text("def gamma():\n    return 3\n", encoding="utf-8")
    assert mgr.list_repositories(force_refresh=True)[0]["status"] == "STALE"  # an added indexable file


def test_ambiguous_rate_is_a_ratio_shown_as_percent(qapp):
    model = RepoTableModel()
    model.set_rows(
        [{"repo_id": "r", "root": "/r", "status": "FRESH", "symbols_count": 1200, "ambiguous_rate": 0.125, "db_size_mb": 1.5}]
    )
    assert model.rowCount() == 1 and model.columnCount() == 6
    assert model.index(0, 4).data() == "12.5%"
    assert model.index(0, 3).data() == "1,200"
    assert model.row_at(0)["ambiguous_rate"] == 0.125  # stored value untouched
    assert model.repo_id_at(0) == "r" and model.repo_id_at(5) is None


# ---- M8.3 index in a child process ----------------------------------------------------------------------------------
def test_index_process_single_repo(qapp, env):
    config_path, repo_dir = env
    RepoManager(config_path).add_repository("repo-a", repo_dir)
    job = IndexProcess("repo-a", config_path)
    done: list = []
    failed: list = []
    progress: list[float] = []
    job.index_finished.connect(lambda r, m: done.append((r, m)))
    job.index_failed.connect(lambda r, e: failed.append((r, e)))
    job.progress_changed.connect(lambda *_: progress.append(time.monotonic()))
    t0 = time.monotonic()
    job.start()
    assert pump_until(lambda: bool(done or failed), 120)
    elapsed = time.monotonic() - t0
    assert failed == [] and done and done[0][0] == "repo-a"
    assert done[0][1].get("symbols_indexed", 0) >= 2
    assert len(progress) <= elapsed * 10 + 3  # at most ten updates per second
    assert RepoManager(config_path).list_repositories(force_refresh=True)[0]["status"] == "FRESH"


def test_index_process_all(qapp, env):
    config_path, repo_dir = env
    mgr = RepoManager(config_path)
    mgr.add_repository("repo-a", repo_dir)
    other = repo_dir.parent / "repo-b"
    other.mkdir()
    (other / "x.py").write_text("def x():\n    return 1\n", encoding="utf-8")
    mgr.add_repository("repo-b", other)
    job = IndexProcess(None, config_path, all_repos=True)
    done: list = []
    failed: list = []
    job.index_finished.connect(lambda r, m: done.append((r, m)))
    job.index_failed.connect(lambda r, e: failed.append((r, e)))
    job.start()
    assert pump_until(lambda: bool(done or failed), 150)
    assert failed == [] and done[0][0] == "*"
    assert {r["status"] for r in mgr.list_repositories(force_refresh=True)} == {"FRESH"}


GRANDCHILD_SCRIPT = """
import subprocess, sys, time, pathlib
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
pathlib.Path(sys.argv[1]).write_text(str(child.pid))
print('{"stage": "scan", "current": 1, "total": 10}', flush=True)
time.sleep(120)
"""


def test_cancel_kills_the_whole_process_tree(qapp, tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    job = IndexProcess("x", tmp_path / "repos.toml", command=(sys.executable, ["-c", GRANDCHILD_SCRIPT, str(pidfile)]))
    failed: list = []
    job.index_failed.connect(lambda r, e: failed.append((r, e)))
    job.start()
    assert pump_until(lambda: pidfile.exists() and pidfile.read_text().strip() != "", 30)
    grandchild = int(pidfile.read_text())
    child = job.pid()
    assert psutil.pid_exists(grandchild) and psutil.pid_exists(child)

    job.cancel()
    assert pump_until(lambda: bool(failed), 30)
    assert failed[0] == ("x", "Cancelled") and job.cancelled
    assert grandchild in job.killed_pids and child in job.killed_pids
    assert pump_until(lambda: not psutil.pid_exists(grandchild) or psutil.Process(grandchild).status() == psutil.STATUS_ZOMBIE, 10)
    assert pump_until(lambda: not psutil.pid_exists(child) or psutil.Process(child).status() == psutil.STATUS_ZOMBIE, 10)


def test_kill_process_tree_of_missing_pid():
    assert kill_process_tree(2**22 + 12345) == []


# ---- M8.4 log --------------------------------------------------------------------------------------------------------
def test_log_is_batched_and_capped(qapp, env):
    from token_context_mcp.gui.widgets.tasks_tab import TasksTab

    config_path, _ = env
    tab = TasksTab(RepoManager(config_path))
    assert tab.console.maximumBlockCount() == 5000
    assert tab._log_timer.interval() == 100
    before = tab.console.blockCount()
    for i in range(300):
        tab.append_log(f"line {i}")
    assert tab.console.blockCount() == before  # nothing appended per message
    tab.flush_logs()
    assert tab.console.blockCount() == before + 300 - 1 or tab.console.blockCount() >= 300
    for i in range(6000):
        tab.append_log(f"more {i}")
    tab.flush_logs()
    assert tab.console.blockCount() <= 5000


# ---- M8.7 server panel (D2) --------------------------------------------------------------------------------------------
def test_no_server_start_stop_api():
    for name in ("start_server", "stop_server", "restart_server", "log_received", "status_changed"):
        assert not hasattr(ServerController, name)


def test_client_configs_carry_the_matrix_flags(tmp_path):
    ctrl = ServerController(tmp_path / "repos.toml")
    assert "--output-mode" in ctrl.get_client_config("claude-code") and "structured" in ctrl.get_client_config("claude-code")
    anti = ctrl.get_client_config("antigravity")
    assert "gemini_safe" in anti and "text" in anti
    codex = ctrl.get_client_config("codex")
    assert codex.startswith("[mcp_servers.token-context]") and "command =" in codex
    assert '"servers"' in ctrl.get_client_config("vscode")
    assert '"mcpServers"' in ctrl.get_client_config("claude")
    assert "--output-mode" not in ctrl.get_client_config("claude")  # D11: server default stays structured


def test_dashboard_lists_running_servers(qapp, env):
    from token_context_mcp.gui.widgets.dashboard_tab import DashboardTab
    from token_context_mcp.security.governance_store import GovernanceStore

    config_path, _ = env
    store = GovernanceStore(config_path.parent / "governance.sqlite")
    store.record_heartbeat("srv-1", pid=4242)
    store.close()
    mgr = RepoManager(config_path)
    tab = DashboardTab(mgr, ServerController(config_path))
    tab.refresh()
    assert wait_idle()
    assert tab.servers_table.rowCount() == 1
    assert tab.servers_table.item(0, 0).text() == "srv-1"
    assert not hasattr(tab, "start_btn") and not hasattr(tab, "stop_btn")


# ---- M8.8 hardware probe --------------------------------------------------------------------------------------------
def test_system_monitor_probes_hardware_on_its_own_thread(qapp, monkeypatch):
    calls: list[bool] = []
    monkeypatch.setattr(bridge, "detect_ai_hardware", lambda: calls.append(is_ui_thread()) or "TestGPU")
    monitor = SystemMonitor(None, interval=0.1)
    assert calls == []  # the constructor does not probe
    got: list = []
    monitor.telemetry_updated.connect(got.append)
    monitor.start()
    assert pump_until(lambda: bool(got), 15)
    monitor.stop()
    monitor.wait(5000)
    assert calls == [False] and got[0].ai_hardware == "TestGPU"


# ---- M8.9 VACUUM ----------------------------------------------------------------------------------------------------
def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_vacuum_never_touches_snapshots(qapp, env):
    config_path, repo_dir = env
    mgr = RepoManager(config_path)
    mgr.add_repository("repo-a", repo_dir)
    assert cli_index(config_path, "repo-a").returncode == 0
    idx_dir = mgr.get_index_dir()
    before = {p: _sha(p) for p in idx_dir.rglob("*") if p.is_file()}
    assert before

    for name in CacheManager.VACUUMABLE_DBS:
        con = sqlite3.connect(config_path.parent / name)
        con.execute("CREATE TABLE t(x)")
        con.executemany("INSERT INTO t VALUES (?)", [("x" * 100,)] * 200)
        con.execute("DELETE FROM t")
        con.commit()
        con.close()

    cache = CacheManager(config_path)
    assert {t["name"] for t in cache.vacuum_targets()} == set(CacheManager.VACUUMABLE_DBS)
    results = cache.vacuum_databases([t["name"] for t in cache.vacuum_targets()])
    assert [r["status"] for r in results] == ["ok"] * 3
    assert all(r["reclaimed_bytes"] >= 0 for r in results)
    assert {p: _sha(p) for p in idx_dir.rglob("*") if p.is_file()} == before

    snapshot_name = next(p.name for p in idx_dir.iterdir() if p.suffix == ".sqlite")
    for bad in (snapshot_name, "repo-a.sqlite", "../repos.toml", "index"):
        with pytest.raises(ValueError):
            cache.vacuum_one(bad)
    assert {p: _sha(p) for p in idx_dir.rglob("*") if p.is_file()} == before


def test_vacuum_retries_locked_database_three_times(qapp, env, monkeypatch):
    config_path, _ = env
    db = config_path.parent / "memory.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t(x)")
    con.commit()
    con.close()
    holder = sqlite3.connect(db, isolation_level=None)
    holder.execute("BEGIN EXCLUSIVE")

    sleeps: list[float] = []
    monkeypatch.setattr(bridge.time, "sleep", lambda s: sleeps.append(s))
    cache = CacheManager(config_path)
    result = cache.vacuum_one("memory.sqlite")
    assert result["status"] == "error" and "locked" in result["error"].lower()
    assert len(sleeps) == 3 == CacheManager.VACUUM_RETRIES
    assert sleeps == [0.5, 1.0, 1.5]

    holder.execute("ROLLBACK")
    holder.close()
    assert cache.vacuum_one("memory.sqlite")["status"] == "ok"


def test_vacuum_missing_database_reports_error(qapp, env):
    result = CacheManager(env[0]).vacuum_one("audit.sqlite")
    assert result["status"] == "error"


# ---- M8.10 watchdog -------------------------------------------------------------------------------------------------
def test_watchdog_records_a_stall(qapp):
    dog = EventLoopWatchdog(None, debug=False)
    dog.start()
    pump_until(lambda: False, 0.2)  # a few healthy ticks
    healthy = dog.stall_count
    time.sleep(0.4)  # block the UI thread
    pump_until(lambda: dog.stall_count > healthy, 3)
    dog.stop()
    assert dog.stall_count > healthy
    assert max(dog.stalls_ms) >= 250


def test_watchdog_debug_dumps_stack(qapp, tmp_path):
    dump = tmp_path / "stalls.log"
    dog = EventLoopWatchdog(None, debug=True, dump_path=dump)
    dog.start()
    pump_until(lambda: False, 0.2)
    time.sleep(0.5)
    pump_until(lambda: dog.stall_count > 0, 3)
    dog.stop()
    assert dog.stall_count > 0
    assert "Thread" in dump.read_text(encoding="utf-8")

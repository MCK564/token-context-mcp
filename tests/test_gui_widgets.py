from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Use offscreen platform for headless test execution
os.environ["QT_QPA_PLATFORM"] = "offscreen"

pyside6 = pytest.importorskip("PySide6", reason="PySide6 is not installed")
from PySide6.QtWidgets import QApplication, QWidget

from token_context_mcp.gui.bridge import AgentSecurityController, RepoManager, ServerController
from token_context_mcp.gui.main_window import MainWindow
from token_context_mcp.gui.widgets.agents_tab import AgentsTab
from token_context_mcp.gui.widgets.cache_tab import CacheTab
from token_context_mcp.gui.widgets.dashboard_tab import DashboardTab
from token_context_mcp.gui.widgets.repositories_tab import RepositoriesTab
from token_context_mcp.gui.widgets.settings_tab import SettingsTab
from token_context_mcp.gui.widgets.tasks_tab import TasksTab


@pytest.fixture(scope="session")
def qapp():
    try:
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        return app
    except Exception as exc:
        pytest.skip(f"QApplication failed to initialize: {exc}")


@pytest.fixture
def temp_gui_env():
    with tempfile.TemporaryDirectory(prefix="tcmcp_gui_widget_test_", ignore_cleanup_errors=True) as tmpdir:
        config_path = Path(tmpdir) / "repos.toml"
        repo_dir = Path(tmpdir) / "test-repo"
        repo_dir.mkdir()
        (repo_dir / "index.js").write_text("function test() {}", encoding="utf-8")
        yield config_path, repo_dir


def test_main_window_instantiation(qapp, temp_gui_env):
    config_path, _ = temp_gui_env
    window = MainWindow(config_path=config_path)
    assert window is not None
    assert window.stack.count() == 6

    # Switch tabs
    for idx in range(6):
        window._on_nav_clicked(idx)
        assert window.stack.currentIndex() == idx

    window.close()


def test_individual_widgets(qapp, temp_gui_env):
    config_path, repo_dir = temp_gui_env
    repo_mgr = RepoManager(config_path)
    repo_mgr.add_repository("testrepo", repo_dir)
    server_ctrl = ServerController(config_path)
    security_ctrl = AgentSecurityController(config_path)

    # Dashboard tab
    dashboard = DashboardTab(repo_mgr, server_ctrl)
    dashboard.refresh_stats()
    assert dashboard.stat_repos.text() == "1"

    # Repositories tab
    repos_tab = RepositoriesTab(repo_mgr)
    assert repos_tab.table.rowCount() == 1

    # Tasks tab
    tasks_tab = TasksTab(repo_mgr)
    tasks_tab.append_log("Test log entry")
    assert "Test log entry" in tasks_tab.console.toPlainText()

    # Cache tab
    cache_tab = CacheTab(repo_mgr)
    assert cache_tab.table is not None

    # Agents tab
    agents_tab = AgentsTab(security_ctrl, repo_mgr)
    security_ctrl.access_control.register_agent("test-agent-1", role="unit-tester")
    security_ctrl.refresh_data()
    assert agents_tab.agents_table.rowCount() >= 1

    # Pause agent via controller and verify UI reflection
    security_ctrl.pause_agent("test-agent-1", reason="Testing pause")
    assert security_ctrl.access_control.get_agent_state("test-agent-1").value == "PAUSED"

    # Emergency halt
    security_ctrl.emergency_halt("Testing emergency stop")
    assert security_ctrl.is_emergency_halted is True
    assert "EMERGENCY STOP ACTIVE" in agents_tab.status_indicator.text()
    security_ctrl.emergency_resume()
    assert security_ctrl.is_emergency_halted is False

    # Settings tab
    settings_tab = SettingsTab(repo_mgr)
    assert settings_tab.spin_tokens.value() > 0

    security_ctrl.close()


def test_loading_overlay(qapp):
    from token_context_mcp.gui.widgets.loading_overlay import LoadingOverlay
    parent = QWidget()
    parent.show()
    overlay = LoadingOverlay(parent)
    assert not overlay.isVisible()
    overlay.show_loading("Processing task...")
    assert overlay.isVisible()
    assert overlay.text_label.text() == "Processing task..."
    overlay.hide_loading()
    assert not overlay.isVisible()
    parent.close()

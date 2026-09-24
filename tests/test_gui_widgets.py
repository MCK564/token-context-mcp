from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Use offscreen platform for headless test execution
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from token_context_mcp.gui.bridge import RepoManager, ServerController
from token_context_mcp.gui.main_window import MainWindow
from token_context_mcp.gui.widgets.cache_tab import CacheTab
from token_context_mcp.gui.widgets.dashboard_tab import DashboardTab
from token_context_mcp.gui.widgets.repositories_tab import RepositoriesTab
from token_context_mcp.gui.widgets.settings_tab import SettingsTab
from token_context_mcp.gui.widgets.tasks_tab import TasksTab


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def temp_gui_env():
    with tempfile.TemporaryDirectory(prefix="tcmcp_gui_widget_test_") as tmpdir:
        config_path = Path(tmpdir) / "repos.toml"
        repo_dir = Path(tmpdir) / "test-repo"
        repo_dir.mkdir()
        (repo_dir / "index.js").write_text("function test() {}", encoding="utf-8")
        yield config_path, repo_dir


def test_main_window_instantiation(qapp, temp_gui_env):
    config_path, _ = temp_gui_env
    window = MainWindow(config_path=config_path)
    assert window is not None
    assert window.stack.count() == 5

    # Switch tabs
    for idx in range(5):
        window._on_nav_clicked(idx)
        assert window.stack.currentIndex() == idx

    window.close()


def test_individual_widgets(qapp, temp_gui_env):
    config_path, repo_dir = temp_gui_env
    repo_mgr = RepoManager(config_path)
    repo_mgr.add_repository("testrepo", repo_dir)
    server_ctrl = ServerController(config_path)

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

    # Settings tab
    settings_tab = SettingsTab(repo_mgr)
    assert settings_tab.spin_tokens.value() > 0

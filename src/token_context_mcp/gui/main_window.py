from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from token_context_mcp.gui.bridge import (
    RepoManager,
    ServerController,
    SystemMonitor,
)
from token_context_mcp.gui.widgets.cache_tab import CacheTab
from token_context_mcp.gui.widgets.dashboard_tab import DashboardTab
from token_context_mcp.gui.widgets.repositories_tab import RepositoriesTab
from token_context_mcp.gui.widgets.settings_tab import SettingsTab
from token_context_mcp.gui.widgets.tasks_tab import TasksTab


class MainWindow(QMainWindow):
    def __init__(self, config_path: Path | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Token Context MCP - Desktop Controller")
        self.resize(1080, 720)
        self.setMinimumSize(920, 600)

        # Core Bridges
        self.repo_mgr = RepoManager(config_path)
        self.server_ctrl = ServerController(config_path, self)
        self.sys_monitor = SystemMonitor(self)

        # Central Layout
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Sidebar Navigation
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        s_layout = QVBoxLayout(sidebar)
        s_layout.setContentsMargins(0, 0, 0, 16)
        s_layout.setSpacing(4)

        # Sidebar Header
        header = QWidget()
        header.setObjectName("SidebarHeader")
        h_layout = QVBoxLayout(header)
        h_layout.setContentsMargins(14, 14, 14, 14)
        h_layout.setSpacing(2)

        title = QLabel("TOKEN-CONTEXT")
        title.setObjectName("AppTitle")
        subtitle = QLabel("Desktop Controller v0.1.0")
        subtitle.setObjectName("AppSubtitle")
        h_layout.addWidget(title)
        h_layout.addWidget(subtitle)
        s_layout.addWidget(header)

        # Nav Buttons
        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)

        nav_items = [
            ("📊 Dashboard", 0),
            ("📁 Repositories", 1),
            ("⚡ Tasks & Graph", 2),
            ("💾 Cache & DB", 3),
            ("⚙️ Settings", 4),
        ]

        self.nav_buttons: list[QPushButton] = []
        for label, idx in nav_items:
            btn = QPushButton(label)
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            self.btn_group.addButton(btn, idx)
            s_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        self.nav_buttons[0].setChecked(True)
        s_layout.addStretch()

        # Version footer
        footer = QLabel("SQLite Snapshot • 19 Tools Ready")
        footer.setStyleSheet("color: #6e738d; font-size: 10px; padding: 0 16px;")
        s_layout.addWidget(footer)

        root_layout.addWidget(sidebar)

        # 2. Main Content Stack
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background-color: #1e1e2e;")

        self.tab_dashboard = DashboardTab(self.repo_mgr, self.server_ctrl)
        self.tab_repos = RepositoriesTab(self.repo_mgr)
        self.tab_tasks = TasksTab(self.repo_mgr)
        self.tab_cache = CacheTab(self.repo_mgr)
        self.tab_settings = SettingsTab(self.repo_mgr)

        self.stack.addWidget(self.tab_dashboard)
        self.stack.addWidget(self.tab_repos)
        self.stack.addWidget(self.tab_tasks)
        self.stack.addWidget(self.tab_cache)
        self.stack.addWidget(self.tab_settings)

        root_layout.addWidget(self.stack, 1)

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready. Token-context-mcp controller initialized.")

        # Connect Signals
        self.btn_group.idClicked.connect(self._on_nav_clicked)
        self.sys_monitor.telemetry_updated.connect(self.tab_dashboard.update_telemetry)
        self.server_ctrl.log_received.connect(self.tab_tasks.append_log)
        self.server_ctrl.status_changed.connect(self._on_server_status)

        self.tab_repos.indexing_started.connect(lambda rid: self.tab_tasks.append_log(f"⚡ Indexing started for: {rid}"))
        self.tab_repos.indexing_finished.connect(self._on_index_done)

        # Start background monitor
        self.sys_monitor.start()
        self.tab_dashboard.refresh_stats()

    def _on_nav_clicked(self, idx: int) -> None:
        self.stack.setCurrentIndex(idx)
        if idx == 0:
            self.tab_dashboard.refresh_stats()
        elif idx == 1:
            self.tab_repos.load_repositories()
        elif idx == 2:
            self.tab_tasks.refresh_repositories()
        elif idx == 3:
            self.tab_cache.refresh_stats()
        elif idx == 4:
            self.tab_settings.load_settings()

    def _on_server_status(self, status: str, pid: int) -> None:
        if status == "RUNNING":
            self.status_bar.showMessage(f"MCP Server Active (PID: {pid}) - Stdio ready.")
        elif status == "STOPPED":
            self.status_bar.showMessage("MCP Server Stopped.")
        else:
            self.status_bar.showMessage(f"MCP Server: {status}...")

    def _on_index_done(self, repo_id: str) -> None:
        self.status_bar.showMessage(f"Repository '{repo_id}' indexed successfully.")
        self.tab_dashboard.refresh_stats()
        self.tab_tasks.refresh_repositories()
        self.tab_cache.refresh_stats()

    def closeEvent(self, event) -> None:
        # Gracefully stop monitor and server
        if self.sys_monitor.isRunning():
            self.sys_monitor.stop()
        if self.server_ctrl.status == "RUNNING":
            self.server_ctrl.stop_server()
        event.accept()

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
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
    SystemTelemetry,
)
from token_context_mcp.gui.widgets.cache_tab import CacheTab
from token_context_mcp.gui.widgets.dashboard_tab import DashboardTab
from token_context_mcp.gui.widgets.loading_overlay import LoadingOverlay
from token_context_mcp.gui.widgets.repositories_tab import RepositoriesTab
from token_context_mcp.gui.widgets.settings_tab import SettingsTab
from token_context_mcp.gui.widgets.tasks_tab import TasksTab


class MainWindow(QMainWindow):
    def __init__(self, config_path: Path | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Token Context MCP - Desktop Controller")
        self.resize(1120, 740)
        self.setMinimumSize(960, 620)

        # Core Bridges
        self.repo_mgr = RepoManager(config_path)
        self.server_ctrl = ServerController(config_path, self)
        self.sys_monitor = SystemMonitor(self, interval=2.5)

        self._active_task_desc = "All tasks idle"
        self._is_task_running = False

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

        self.tab_titles = [
            ("Dashboard", "System Telemetry & Server Controls"),
            ("Repositories", "Allowlist & Snapshot Inventory"),
            ("Tasks & Graph", "Live Log Stream & Graph Precision"),
            ("Cache & Storage", "SQLite DB Breakdown & Defragmentation"),
            ("Settings", "Resource Caps & Extension Configuration"),
        ]

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

        # 2. Main Content Area (Header + Stack + Overlay)
        content_panel = QWidget()
        content_layout = QVBoxLayout(content_panel)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Top Task & Status Banner Header
        self.top_header = QFrame()
        self.top_header.setStyleSheet("background-color: #181825; border-bottom: 1px solid #363a4f; padding: 8px 16px;")
        top_header_layout = QHBoxLayout(self.top_header)
        top_header_layout.setContentsMargins(12, 6, 12, 6)
        top_header_layout.setSpacing(12)

        # View Title
        self.view_title_label = QLabel("Dashboard")
        self.view_title_label.setStyleSheet("font-size: 15px; font-weight: 700; color: #cad3f5;")
        self.view_subtitle_label = QLabel("System Telemetry & Server Controls")
        self.view_subtitle_label.setStyleSheet("font-size: 11px; color: #a5adcb; margin-left: 6px;")

        top_header_layout.addWidget(self.view_title_label)
        top_header_layout.addWidget(self.view_subtitle_label)
        top_header_layout.addStretch()

        # Active Task Status Pill
        self.task_badge = QLabel("● All tasks idle")
        self.task_badge.setProperty("class", "BadgeFresh")
        self.task_badge.setStyleSheet("padding: 4px 10px; font-size: 12px; font-weight: 600;")
        top_header_layout.addWidget(self.task_badge)

        # Quick Telemetry Pill
        self.quick_telemetry_label = QLabel("CPU: --% | RAM: -- GB")
        self.quick_telemetry_label.setStyleSheet("color: #a5adcb; font-size: 11px; font-weight: 500; background-color: #24273a; border-radius: 6px; padding: 4px 8px;")
        top_header_layout.addWidget(self.quick_telemetry_label)

        # Refresh Button
        self.header_refresh_btn = QPushButton("🔄 Refresh")
        self.header_refresh_btn.setStyleSheet("padding: 4px 10px; font-size: 11px;")
        self.header_refresh_btn.clicked.connect(self._manual_refresh_current_tab)
        top_header_layout.addWidget(self.header_refresh_btn)

        content_layout.addWidget(self.top_header)

        # Stack Container with Loading Overlay
        self.stack_container = QWidget()
        stack_box = QVBoxLayout(self.stack_container)
        stack_box.setContentsMargins(0, 0, 0, 0)
        stack_box.setSpacing(0)

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

        stack_box.addWidget(self.stack)

        # Floating Loading Overlay
        self.overlay = LoadingOverlay(self.stack_container)
        content_layout.addWidget(self.stack_container, 1)

        root_layout.addWidget(content_panel, 1)

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready. Token-context-mcp controller initialized.")

        # Connect Signals
        self.btn_group.idClicked.connect(self._on_nav_clicked)
        self.sys_monitor.telemetry_updated.connect(self._on_telemetry_update)
        self.server_ctrl.log_received.connect(self.tab_tasks.append_log)
        self.server_ctrl.status_changed.connect(self._on_server_status)

        # Connect Task & Indexing Tracking
        self.tab_repos.indexing_started.connect(self._on_indexing_started)
        self.tab_repos.indexing_progress.connect(self._on_indexing_progress)
        self.tab_repos.indexing_finished.connect(self._on_indexing_finished)

        # Start background monitor
        self.sys_monitor.start()
        self.tab_dashboard.refresh_stats()

    def _on_nav_clicked(self, idx: int) -> None:
        # 1. Switch tab immediately (0ms UI lag)
        self.stack.setCurrentIndex(idx)

        # 2. Update view title
        if 0 <= idx < len(self.tab_titles):
            title, subtitle = self.tab_titles[idx]
            self.view_title_label.setText(title)
            self.view_subtitle_label.setText(subtitle)

        # 3. Non-blocking asynchronous refresh using cached data
        QTimer.singleShot(0, lambda: self._refresh_tab_async(idx))

    def _refresh_tab_async(self, idx: int) -> None:
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

    def _manual_refresh_current_tab(self) -> None:
        self.repo_mgr.invalidate_cache()
        idx = self.stack.currentIndex()
        self.overlay.show_loading("Refreshing data...")
        QTimer.singleShot(150, lambda: self._do_refresh_and_hide(idx))

    def _do_refresh_and_hide(self, idx: int) -> None:
        self._refresh_tab_async(idx)
        self.overlay.hide_loading()
        self.status_bar.showMessage("Refreshed data successfully.", 3000)

    def _on_telemetry_update(self, t: SystemTelemetry) -> None:
        self.tab_dashboard.update_telemetry(t)
        self.quick_telemetry_label.setText(f"CPU: {t.cpu_percent:.0f}% | RAM: {t.ram_used_gb:.1f}/{t.ram_total_gb:.0f} GB")

    def _on_indexing_started(self, repo_id: str) -> None:
        self._is_task_running = True
        self.task_badge.setText(f"⚡ Indexing '{repo_id}'...")
        self.task_badge.setProperty("class", "BadgeStale")
        self.task_badge.style().unpolish(self.task_badge)
        self.task_badge.style().polish(self.task_badge)
        self.tab_tasks.append_log(f"⚡ Indexing started for: {repo_id}")

    def _on_indexing_progress(self, msg: str, current: int, total: int) -> None:
        pct = min(100, int((current / max(1, total)) * 100)) if total > 0 else 0
        self.task_badge.setText(f"⚡ Indexing [{pct}%] - {msg}")

    def _on_indexing_finished(self, repo_id: str) -> None:
        self._is_task_running = False
        self.task_badge.setText("● All tasks idle")
        self.task_badge.setProperty("class", "BadgeFresh")
        self.task_badge.style().unpolish(self.task_badge)
        self.task_badge.style().polish(self.task_badge)

        self.status_bar.showMessage(f"Repository '{repo_id}' indexed successfully.", 5000)
        self.repo_mgr.invalidate_cache()
        self.tab_dashboard.refresh_stats()
        self.tab_tasks.refresh_repositories()
        self.tab_cache.refresh_stats()

    def _on_server_status(self, status: str, pid: int) -> None:
        if status == "RUNNING":
            self.status_bar.showMessage(f"MCP Server Active (PID: {pid}) - Stdio ready.")
        elif status == "STOPPED":
            self.status_bar.showMessage("MCP Server Stopped.")
        else:
            self.status_bar.showMessage(f"MCP Server: {status}...")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "overlay") and self.overlay.isVisible():
            self.overlay.resize(self.stack_container.size())

    def closeEvent(self, event) -> None:
        if self.sys_monitor.isRunning():
            self.sys_monitor.stop()
        if self.server_ctrl.status == "RUNNING":
            self.server_ctrl.stop_server()
        event.accept()

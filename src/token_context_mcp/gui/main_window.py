from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
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

from token_context_mcp.gui.bridge import AgentSecurityController, RepoManager, ServerController, SystemMonitor
from token_context_mcp.gui.icons import make_icon
from token_context_mcp.gui.perf import EventLoopWatchdog
from token_context_mcp.gui.theme import COLOR_ACCENT, COLOR_TEXT_MUTED, COLOR_TEXT_PRIMARY
from token_context_mcp.gui.widgets.agents_tab import AgentsTab
from token_context_mcp.gui.widgets.cache_tab import CacheTab
from token_context_mcp.gui.widgets.dashboard_tab import DashboardTab
from token_context_mcp.gui.widgets.ledger_tab import LedgerTab
from token_context_mcp.gui.widgets.loading_overlay import LoadingOverlay
from token_context_mcp.gui.widgets.repositories_tab import RepositoriesTab
from token_context_mcp.gui.widgets.settings_tab import SettingsTab
from token_context_mcp.gui.widgets.tasks_tab import TasksTab
from token_context_mcp.gui.workers import reset_workers_for_tests, run_async, shutdown_workers


class MainWindow(QMainWindow):
    def __init__(self, config_path: Path | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        reset_workers_for_tests()
        self.setWindowTitle("Token Context MCP — Desktop Controller")
        self.resize(1120, 740)
        self.setMinimumSize(960, 620)

        # Core Bridges
        self.repo_mgr = RepoManager(config_path)
        self.server_ctrl = ServerController(config_path, self)
        self.security_ctrl = AgentSecurityController(config_path, self)
        self.sys_monitor = SystemMonitor(self, interval=2.5)
        self.watchdog = EventLoopWatchdog(self)
        self._refresh_seq = 0
        self._refresh_pending: dict[int, int] = {}

        self._active_task_desc = "All tasks idle"
        self._is_task_running = False

        # Central Layout
        central = QWidget()
        central.setObjectName("MainContent")
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Sidebar Navigation
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        s_layout = QVBoxLayout(sidebar)
        s_layout.setContentsMargins(0, 0, 0, 14)
        s_layout.setSpacing(4)

        header = QWidget()
        header.setObjectName("SidebarHeader")
        h_layout = QVBoxLayout(header)
        h_layout.setContentsMargins(14, 14, 14, 14)
        h_layout.setSpacing(2)

        title = QLabel("TOKEN-CONTEXT")
        title.setObjectName("AppTitle")
        subtitle = QLabel("Desktop Controller")
        subtitle.setObjectName("AppSubtitle")
        h_layout.addWidget(title)
        h_layout.addWidget(subtitle)
        s_layout.addWidget(header)

        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)

        self.tab_titles = [
            ("Dashboard", "System Telemetry & Running Servers"),
            ("Repositories", "Allowlist & Snapshot Inventory"),
            ("Tasks & Graph", "Symbol Explorer & Indexing Stream"),
            ("Cache & Storage", "SQLite Breakdown & Vacuum"),
            ("Ledger & Memory", "Evidence Ledger ('Lá Phổi') & Memory"),
            ("Agents & Security", "Policies, Locks & Audit Trail"),
            ("Settings", "Server Limits & Ledger Config"),
        ]

        nav_items = [
            ("Dashboard", "dashboard", 0),
            ("Repositories", "repos", 1),
            ("Tasks && Graph", "tasks", 2),
            ("Cache && DB", "cache", 3),
            ("Ledger && Memory", "ledger", 4),
            ("Agents", "agents", 5),
            ("Settings", "settings", 6),
        ]

        self.nav_buttons: list[QPushButton] = []
        for label, icon_name, idx in nav_items:
            btn = QPushButton(label)
            btn.setObjectName("NavButton")
            btn.setIcon(make_icon(icon_name, COLOR_TEXT_PRIMARY if idx == 0 else COLOR_TEXT_MUTED))
            btn.setCheckable(True)
            self.btn_group.addButton(btn, idx)
            s_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        self.nav_buttons[0].setChecked(True)
        s_layout.addStretch()

        footer = QLabel("SQLite Snapshot • MCP Controller")
        footer.setStyleSheet("color: #6e738d; font-size: 10px; padding: 0 14px; background: transparent;")
        s_layout.addWidget(footer)

        root_layout.addWidget(sidebar)

        # 2. Main Content Area (Header + Stack)
        content_panel = QWidget()
        content_layout = QVBoxLayout(content_panel)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.top_header = QFrame()
        self.top_header.setObjectName("TopHeader")
        top_header_layout = QHBoxLayout(self.top_header)
        top_header_layout.setContentsMargins(16, 10, 16, 10)
        top_header_layout.setSpacing(10)

        self.view_title_label = QLabel("Dashboard")
        self.view_title_label.setObjectName("HeaderTitle")
        self.view_subtitle_label = QLabel("System Telemetry & Running Servers")
        self.view_subtitle_label.setObjectName("HeaderSubtitle")

        top_header_layout.addWidget(self.view_title_label)
        top_header_layout.addWidget(self.view_subtitle_label, 1)

        self.task_badge = QLabel("All tasks idle")
        self.task_badge.setProperty("class", "BadgeFresh")
        top_header_layout.addWidget(self.task_badge)

        self.quick_telemetry_label = QLabel("CPU: --% | RAM: -- GB")
        self.quick_telemetry_label.setObjectName("TelemetryPill")
        top_header_layout.addWidget(self.quick_telemetry_label)

        self.header_refresh_btn = QPushButton("Refresh")
        self.header_refresh_btn.setIcon(make_icon("refresh", COLOR_TEXT_PRIMARY))
        self.header_refresh_btn.clicked.connect(self._manual_refresh_current_tab)
        top_header_layout.addWidget(self.header_refresh_btn)

        content_layout.addWidget(self.top_header)

        self.stack_container = QWidget()
        stack_box = QVBoxLayout(self.stack_container)
        stack_box.setContentsMargins(0, 0, 0, 0)
        stack_box.setSpacing(0)

        self.stack = QStackedWidget()
        self.stack.setObjectName("MainStack")

        self.tab_dashboard = DashboardTab(self.repo_mgr, self.server_ctrl)
        self.tab_repos = RepositoriesTab(self.repo_mgr)
        self.tab_tasks = TasksTab(self.repo_mgr)
        self.tab_cache = CacheTab(self.repo_mgr)
        self.tab_ledger = LedgerTab(self.repo_mgr)
        self.tab_agents = AgentsTab(self.security_ctrl, self.repo_mgr)
        self.tab_settings = SettingsTab(self.repo_mgr)

        self.stack.addWidget(self.tab_dashboard)
        self.stack.addWidget(self.tab_repos)
        self.stack.addWidget(self.tab_tasks)
        self.stack.addWidget(self.tab_cache)
        self.stack.addWidget(self.tab_ledger)
        self.stack.addWidget(self.tab_agents)
        self.stack.addWidget(self.tab_settings)

        stack_box.addWidget(self.stack)

        self.overlay = LoadingOverlay(self.stack_container)
        content_layout.addWidget(self.stack_container, 1)

        root_layout.addWidget(content_panel, 1)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready. Token-context-mcp controller initialized.")

        # Connect Signals
        self.btn_group.idClicked.connect(self._on_nav_clicked)
        self.sys_monitor.telemetry_updated.connect(self._on_telemetry_update)
        self.tab_repos.indexing_log.connect(self.tab_tasks.append_log)
        self.tab_repos.indexing_started.connect(self._on_indexing_started)
        self.tab_repos.indexing_progress.connect(self._on_indexing_progress)
        self.tab_repos.indexing_finished.connect(self._on_indexing_finished)

        # Keyboard shortcuts
        QShortcut(QKeySequence("F5"), self, activated=self._manual_refresh_current_tab)
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self._manual_refresh_current_tab)

        self.sys_monitor.start()
        self.watchdog.start()
        QTimer.singleShot(0, lambda: self._refresh_tab(0))

    def _on_nav_clicked(self, idx: int) -> None:
        self.stack.setCurrentIndex(idx)
        icon_names = ["dashboard", "repos", "tasks", "cache", "ledger", "agents", "settings"]
        for i, btn in enumerate(self.nav_buttons):
            btn.setIcon(make_icon(icon_names[i], COLOR_ACCENT if i == idx else COLOR_TEXT_MUTED))

        if 0 <= idx < len(self.tab_titles):
            title, subtitle = self.tab_titles[idx]
            self.view_title_label.setText(title)
            self.view_subtitle_label.setText(subtitle)

        QTimer.singleShot(0, lambda: self._refresh_tab(idx))

    def _tab_at(self, idx: int) -> QWidget | None:
        tabs = [
            self.tab_dashboard,
            self.tab_repos,
            self.tab_tasks,
            self.tab_cache,
            self.tab_ledger,
            self.tab_agents,
            self.tab_settings,
        ]
        return tabs[idx] if 0 <= idx < len(tabs) else None

    def _refresh_tab(self, idx: int, show_status: bool = False) -> None:
        tab = self._tab_at(idx)
        if tab is None or not hasattr(tab, "fetch") or not hasattr(tab, "render"):
            return
        self._refresh_seq += 1
        seq = self._refresh_seq
        self._refresh_pending[idx] = seq
        if show_status:
            self.status_bar.showMessage("Refreshing...")

        def _done(snap: Any) -> None:
            if self._refresh_pending.get(idx) == seq:
                tab.render(snap)
            if show_status:
                self.status_bar.showMessage("Ready.", 2500)

        def _err(exc: BaseException) -> None:
            self.status_bar.showMessage(f"Refresh failed: {exc}", 5000)

        run_async(tab.fetch, on_ok=_done, on_err=_err)

    def _manual_refresh_current_tab(self) -> None:
        self._refresh_tab(self.stack.currentIndex(), show_status=True)

    def _on_telemetry_update(self, data: Any) -> None:
        self.tab_dashboard.update_telemetry(data)
        g = (lambda k, d=0.0: data.get(k, d)) if isinstance(data, dict) else (lambda k, d=0.0: getattr(data, k, d))
        cpu = float(g("cpu_percent", 0.0) or 0.0)
        ram_used = float(g("ram_used_gb", 0.0) or 0.0)
        ram_tot = float(g("ram_total_gb", 0.0) or 0.0)
        self.quick_telemetry_label.setText(f"CPU: {cpu:.0f}% | RAM: {ram_used:.1f}/{ram_tot:.0f} GB")

    def _on_indexing_started(self, repo_id: str) -> None:
        self._is_task_running = True
        self._active_task_desc = f"Indexing {repo_id}..."
        self.task_badge.setText(self._active_task_desc)
        self.task_badge.setProperty("class", "BadgeWarning")
        self.task_badge.style().unpolish(self.task_badge)
        self.task_badge.style().polish(self.task_badge)
        self.status_bar.showMessage(f"Background indexing started for '{repo_id}'...")

    def _on_indexing_progress(self, repo_id: str, current: int, total: int, msg: str) -> None:
        if total > 0:
            pct = int(current * 100 / total)
            self.task_badge.setText(f"Indexing {repo_id} ({pct}%)")
        else:
            self.task_badge.setText(f"Indexing {repo_id}...")
        self.status_bar.showMessage(f"Indexing '{repo_id}': {msg}")

    def _on_indexing_finished(self, repo_id: str, ok: bool, msg: str) -> None:
        self._is_task_running = False
        self._active_task_desc = "All tasks idle"
        self.task_badge.setText("All tasks idle")
        self.task_badge.setProperty("class", "BadgeFresh")
        self.task_badge.style().unpolish(self.task_badge)
        self.task_badge.style().polish(self.task_badge)
        if ok:
            self.status_bar.showMessage(f"Finished indexing '{repo_id}': {msg}", 5000)
        else:
            self.status_bar.showMessage(f"Indexing failed for '{repo_id}': {msg}", 8000)

    def closeEvent(self, event) -> None:
        shutdown_workers()
        if self.sys_monitor.isRunning():
            self.sys_monitor.stop()
        self.watchdog.stop()
        if self.tab_repos.isIndexing():
            self.tab_repos.cancel_indexing()
        if hasattr(self, "security_ctrl"):
            self.security_ctrl.close()
        event.accept()

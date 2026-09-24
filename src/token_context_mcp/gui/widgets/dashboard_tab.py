from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from token_context_mcp.gui.bridge import SystemTelemetry

if TYPE_CHECKING:
    from token_context_mcp.gui.bridge import RepoManager, ServerController


class CopyConfigDialog(QDialog):
    def __init__(self, server_ctrl: ServerController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.server_ctrl = server_ctrl
        self.setWindowTitle("Copy MCP Server Configuration")
        self.resize(560, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        header = QLabel("Ready-to-Paste Client Configuration JSON")
        header.setStyleSheet("font-size: 15px; font-weight: 700; color: #89b4fa;")
        layout.addWidget(header)

        client_row = QHBoxLayout()
        client_row.addWidget(QLabel("Target Client:"))
        self.client_combo = QComboBox()
        self.client_combo.addItems(["Claude Desktop / Code", "VS Code (Copilot)", "Cursor", "Antigravity"])
        self.client_combo.currentTextChanged.connect(self._update_json)
        client_row.addWidget(self.client_combo, 1)
        layout.addLayout(client_row)

        self.json_edit = QPlainTextEdit()
        self.json_edit.setReadOnly(True)
        self.json_edit.setProperty("class", "LogConsole")
        self.json_edit.setStyleSheet("background-color: #11111b; font-family: monospace; font-size: 12px; color: #a6da95;")
        layout.addWidget(self.json_edit, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.copy_btn = QPushButton("Copy to Clipboard")
        self.copy_btn.setProperty("class", "PrimaryButton")
        self.copy_btn.clicked.connect(self._copy_clipboard)
        btn_row.addWidget(self.copy_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)
        self._update_json()

    def _update_json(self) -> None:
        client_text = self.client_combo.currentText().lower()
        if "vs code" in client_text:
            key = "vscode"
        elif "antigravity" in client_text:
            key = "antigravity"
        elif "cursor" in client_text:
            key = "cursor"
        else:
            key = "claude"
        self.json_edit.setPlainText(self.server_ctrl.get_client_config(key))

    def _copy_clipboard(self) -> None:
        clipboard = QApplication.clipboard()
        clipboard.setText(self.json_edit.toPlainText())
        self.copy_btn.setText("Copied!")
        self.copy_btn.setEnabled(False)


class DashboardTab(QWidget):
    def __init__(self, repo_mgr: RepoManager, server_ctrl: ServerController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repo_mgr = repo_mgr
        self.server_ctrl = server_ctrl

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # 1. System Telemetry Card
        telemetry_card = QFrame()
        telemetry_card.setProperty("class", "Card")
        t_layout = QVBoxLayout(telemetry_card)
        t_layout.setSpacing(12)

        t_title = QLabel("System Telemetry & Hardware Status")
        t_title.setProperty("class", "CardHeader")
        t_layout.addWidget(t_title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)

        # CPU
        self.cpu_label = QLabel("CPU: --%")
        self.cpu_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        self.cpu_bar = QProgressBar()
        self.cpu_bar.setRange(0, 100)
        self.cpu_bar.setValue(0)
        grid.addWidget(self.cpu_label, 0, 0)
        grid.addWidget(self.cpu_bar, 0, 1)

        # RAM
        self.ram_label = QLabel("RAM: --/-- GB (--%)")
        self.ram_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        self.ram_bar = QProgressBar()
        self.ram_bar.setRange(0, 100)
        self.ram_bar.setValue(0)
        grid.addWidget(self.ram_label, 1, 0)
        grid.addWidget(self.ram_bar, 1, 1)

        # AI Hardware & Disk
        self.hw_label = QLabel("AI Engine: Detecting hardware...")
        self.hw_label.setStyleSheet("color: #89b4fa; font-weight: 600;")
        grid.addWidget(self.hw_label, 2, 0)

        self.disk_label = QLabel("Disk Free: --/-- GB")
        self.disk_label.setStyleSheet("color: #a5adcb;")
        grid.addWidget(self.disk_label, 2, 1)

        t_layout.addLayout(grid)
        layout.addWidget(telemetry_card)

        # 2. MCP Server Status & Controls Card
        server_card = QFrame()
        server_card.setProperty("class", "Card")
        s_layout = QVBoxLayout(server_card)
        s_layout.setSpacing(12)

        s_header_row = QHBoxLayout()
        s_title = QLabel("MCP Server Controller")
        s_title.setProperty("class", "CardHeader")
        s_header_row.addWidget(s_title)
        s_header_row.addStretch()

        self.status_badge = QLabel("STOPPED")
        self.status_badge.setProperty("class", "BadgeStopped")
        s_header_row.addWidget(self.status_badge)
        s_layout.addLayout(s_header_row)

        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(10)

        self.start_btn = QPushButton("Start Server")
        self.start_btn.setProperty("class", "SuccessButton")
        self.start_btn.clicked.connect(self.server_ctrl.start_server)
        ctrl_row.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop Server")
        self.stop_btn.setProperty("class", "DangerButton")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.server_ctrl.stop_server)
        ctrl_row.addWidget(self.stop_btn)

        self.restart_btn = QPushButton("Restart")
        self.restart_btn.clicked.connect(self.server_ctrl.restart_server)
        ctrl_row.addWidget(self.restart_btn)

        ctrl_row.addStretch()

        self.copy_config_btn = QPushButton("📋 Copy MCP Config JSON")
        self.copy_config_btn.clicked.connect(self._open_copy_dialog)
        ctrl_row.addWidget(self.copy_config_btn)

        s_layout.addLayout(ctrl_row)
        layout.addWidget(server_card)

        # 3. Quick Stats Card
        stats_card = QFrame()
        stats_card.setProperty("class", "Card")
        st_layout = QVBoxLayout(stats_card)

        st_title = QLabel("Quick Repository Statistics")
        st_title.setProperty("class", "CardHeader")
        st_layout.addWidget(st_title)

        stats_grid = QGridLayout()
        stats_grid.setHorizontalSpacing(24)
        stats_grid.setVerticalSpacing(8)

        self.stat_repos = QLabel("0")
        self.stat_repos.setProperty("class", "MetricValue")
        lbl_repos = QLabel("Registered Repos")
        lbl_repos.setProperty("class", "MetricLabel")
        stats_grid.addWidget(self.stat_repos, 0, 0)
        stats_grid.addWidget(lbl_repos, 1, 0)

        self.stat_files = QLabel("0")
        self.stat_files.setProperty("class", "MetricValue")
        lbl_files = QLabel("Total Indexed Files")
        lbl_files.setProperty("class", "MetricLabel")
        stats_grid.addWidget(self.stat_files, 0, 1)
        stats_grid.addWidget(lbl_files, 1, 1)

        self.stat_db_size = QLabel("0 MB")
        self.stat_db_size.setProperty("class", "MetricValue")
        lbl_db = QLabel("Total SQLite Cache")
        lbl_db.setProperty("class", "MetricLabel")
        stats_grid.addWidget(self.stat_db_size, 0, 2)
        stats_grid.addWidget(lbl_db, 1, 2)

        self.stat_ambig = QLabel("0.0%")
        self.stat_ambig.setProperty("class", "MetricValue")
        lbl_ambig = QLabel("Ambiguous Edge Rate")
        lbl_ambig.setProperty("class", "MetricLabel")
        stats_grid.addWidget(self.stat_ambig, 0, 3)
        stats_grid.addWidget(lbl_ambig, 1, 3)

        st_layout.addLayout(stats_grid)
        layout.addWidget(stats_card)

        layout.addStretch()

        # Connect signals
        self.server_ctrl.status_changed.connect(self._on_server_status_changed)

    def update_telemetry(self, t: SystemTelemetry) -> None:
        self.cpu_label.setText(f"CPU Usage: {t.cpu_percent:.1f}% ({t.cpu_count_logical} threads)")
        self.cpu_bar.setValue(int(t.cpu_percent))

        self.ram_label.setText(f"RAM Usage: {t.ram_used_gb:.1f} / {t.ram_total_gb:.1f} GB ({t.ram_percent:.1f}%)")
        self.ram_bar.setValue(int(t.ram_percent))

        self.hw_label.setText(f"AI Hardware: {t.ai_hardware}")
        self.disk_label.setText(f"Disk Free: {t.disk_free_gb:.1f} GB / {t.disk_total_gb:.1f} GB")

    def refresh_stats(self) -> None:
        repos = self.repo_mgr.list_repositories()
        total_files = sum(r["files_count"] for r in repos)
        total_size = sum(r["db_size_mb"] for r in repos)

        rates = [r["ambiguous_rate"] for r in repos if r["ambiguous_rate"] > 0]
        avg_rate = (sum(rates) / len(rates)) if rates else 0.0

        self.stat_repos.setText(str(len(repos)))
        self.stat_files.setText(f"{total_files:,}")
        self.stat_db_size.setText(f"{total_size:.1f} MB")
        self.stat_ambig.setText(f"{avg_rate:.1f}%")

    def _on_server_status_changed(self, status: str, pid: int) -> None:
        if status == "RUNNING":
            self.status_badge.setText(f"RUNNING (PID: {pid})")
            self.status_badge.setProperty("class", "BadgeRunning")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
        elif status == "STARTING":
            self.status_badge.setText("STARTING...")
            self.status_badge.setProperty("class", "BadgeStale")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
        else:
            self.status_badge.setText("STOPPED")
            self.status_badge.setProperty("class", "BadgeStopped")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)

        # Force style reload
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)

    def _open_copy_dialog(self) -> None:
        dlg = CopyConfigDialog(self.server_ctrl, self)
        dlg.exec()

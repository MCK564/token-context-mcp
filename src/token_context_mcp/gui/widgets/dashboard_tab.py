from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from token_context_mcp.gui.bridge import SystemTelemetry
from token_context_mcp.gui.workers import run_async

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
        # keys of ServerController.CLIENTS; the flags come from docs/CLIENT_MATRIX.md
        self.client_combo.addItems(["claude", "claude-code", "vscode", "antigravity", "codex"])
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
        self.json_edit.setPlainText(self.server_ctrl.get_client_config(self.client_combo.currentText()))

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

        # 2. Running MCP servers (M8.7): read from the heartbeats servers write themselves. The GUI does not
        # start or stop servers: a stdio server belongs to the client that spawns it.
        server_card = QFrame()
        server_card.setProperty("class", "Card")
        s_layout = QVBoxLayout(server_card)
        s_layout.setSpacing(12)

        s_header_row = QHBoxLayout()
        s_title = QLabel("Running MCP Servers")
        s_title.setProperty("class", "CardHeader")
        s_header_row.addWidget(s_title)
        s_header_row.addStretch()

        self.copy_config_btn = QPushButton("📋 Copy client config")
        self.copy_config_btn.clicked.connect(self._open_copy_dialog)
        s_header_row.addWidget(self.copy_config_btn)
        s_layout.addLayout(s_header_row)

        self.servers_table = QTableWidget()
        self.servers_table.setColumnCount(6)
        self.servers_table.setHorizontalHeaderLabels(["Server", "PID", "Client", "Output mode", "Schema profile", "Last seen"])
        self.servers_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.servers_table.verticalHeader().setVisible(False)
        self.servers_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.servers_table.setMaximumHeight(150)
        s_layout.addWidget(self.servers_table)
        self.servers_hint = QLabel("No MCP server is running. Clients start their own server from their configuration.")
        self.servers_hint.setStyleSheet("color: #6e738d; font-size: 11px;")
        s_layout.addWidget(self.servers_hint)
        layout.addWidget(server_card)

        self._servers_timer = QTimer(self)
        self._servers_timer.setInterval(5000)
        self._servers_timer.timeout.connect(self.refresh_servers)

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

    def update_telemetry(self, t: SystemTelemetry) -> None:
        self.cpu_label.setText(f"CPU Usage: {t.cpu_percent:.1f}% ({t.cpu_count_logical} threads)")
        self.cpu_bar.setValue(int(t.cpu_percent))

        self.ram_label.setText(f"RAM Usage: {t.ram_used_gb:.1f} / {t.ram_total_gb:.1f} GB ({t.ram_percent:.1f}%)")
        self.ram_bar.setValue(int(t.ram_percent))

        self.hw_label.setText(f"AI Hardware: {t.ai_hardware}")
        self.disk_label.setText(f"Disk Free: {t.disk_free_gb:.1f} GB / {t.disk_total_gb:.1f} GB")

    # -- fetch / render (M8.2) -----------------------------------------------------------------------------------
    def fetch(self) -> dict:
        """Worker-side: repository rows and server heartbeats. Touches no widget."""
        return {"repos": self.repo_mgr.list_repositories(force_refresh=True), "servers": self.repo_mgr.fetch_active_servers()}

    def render(self, data: dict) -> None:
        repos = data["repos"]
        total_files = sum(r["files_count"] for r in repos)
        total_size = sum(r["db_size_mb"] for r in repos)
        rates = [r["ambiguous_rate"] for r in repos if r["ambiguous_rate"] > 0]  # ratios 0-1
        avg_rate = (sum(rates) / len(rates)) if rates else 0.0

        self.stat_repos.setText(str(len(repos)))
        self.stat_files.setText(f"{total_files:,}")
        self.stat_db_size.setText(f"{total_size:.1f} MB")
        self.stat_ambig.setText(f"{avg_rate * 100:.1f}%")
        self.render_servers(data["servers"])

    def refresh(self) -> None:
        run_async(self.fetch, on_ok=self.render)

    refresh_stats = refresh  # name used by older callers

    def refresh_servers(self) -> None:
        run_async(self.repo_mgr.fetch_active_servers, on_ok=self.render_servers)

    def render_servers(self, servers: list) -> None:
        self.servers_table.setRowCount(len(servers))
        for row, srv in enumerate(servers):
            values = [
                srv.get("server_id", ""),
                str(srv.get("pid", "")),
                " ".join(x for x in (srv.get("client_name"), srv.get("client_version")) if x) or "unknown",
                srv.get("output_mode") or "-",
                srv.get("schema_profile") or "-",
                str(srv.get("last_seen", ""))[:19].replace("T", " "),
            ]
            for col, value in enumerate(values):
                self.servers_table.setItem(row, col, QTableWidgetItem(value))
        self.servers_hint.setVisible(not servers)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self._servers_timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().hideEvent(event)
        self._servers_timer.stop()

    def _open_copy_dialog(self) -> None:
        dlg = CopyConfigDialog(self.server_ctrl, self)
        dlg.exec()

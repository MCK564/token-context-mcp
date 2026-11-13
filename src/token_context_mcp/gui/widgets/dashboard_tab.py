from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from token_context_mcp.gui.bridge import RepoManager, ServerController, detect_ai_hardware
from token_context_mcp.gui.icons import make_icon
from token_context_mcp.gui.theme import (
    COLOR_ACCENT,
    COLOR_CRUST,
    COLOR_DANGER,
    COLOR_SUCCESS,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_WARNING,
)
from token_context_mcp.gui.workers import is_ui_thread


class CopyConfigDialog(QDialog):
    def __init__(self, server_ctrl: ServerController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.server_ctrl = server_ctrl
        self.setWindowTitle("Copy MCP Client Configuration")
        self.resize(640, 480)
        self.setMinimumSize(520, 400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("Ready-to-Paste Client Configuration JSON")
        title.setProperty("class", "SectionTitle")
        layout.addWidget(title)

        # Client selector
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(QLabel("Target Client:"))
        self.client_combo = QComboBox()
        self.client_combo.addItems(["claude", "claude-code", "cursor", "vscode", "antigravity", "codex"])
        self.client_combo.currentTextChanged.connect(self._update_preview)
        row.addWidget(self.client_combo, 1)
        layout.addLayout(row)

        # Options row
        opts = QHBoxLayout()
        opts.setSpacing(14)
        self.chk_admin = QCheckBox("Enable Admin Tools")
        self.chk_admin.toggled.connect(self._update_preview)
        self.chk_text = QCheckBox("Force --output-mode text")
        self.chk_text.toggled.connect(self._update_preview)
        opts.addWidget(self.chk_admin)
        opts.addWidget(self.chk_text)
        opts.addStretch()
        layout.addLayout(opts)

        env_row = QHBoxLayout()
        env_row.setSpacing(10)
        env_row.addWidget(QLabel("TOKEN_CONTEXT_AGENT_ID (optional):"))
        self.agent_id_input = QLineEdit()
        self.agent_id_input.setPlaceholderText("e.g. antigravity-dev (leave empty to omit)")
        self.agent_id_input.textChanged.connect(self._update_preview)
        env_row.addWidget(self.agent_id_input, 1)
        layout.addLayout(env_row)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setStyleSheet("font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 12px;")
        layout.addWidget(self.preview, 1)

        btns = QHBoxLayout()
        btns.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        self.copy_btn = QPushButton("Copy to Clipboard")
        self.copy_btn.setIcon(make_icon("copy", COLOR_CRUST))
        self.copy_btn.setProperty("class", "PrimaryButton")
        self.copy_btn.clicked.connect(self._copy)
        btns.addWidget(close_btn)
        btns.addWidget(self.copy_btn)
        layout.addLayout(btns)

        self._update_preview()

    def _update_preview(self) -> None:
        client = self.client_combo.currentText()
        raw = self.server_ctrl.get_client_config(client)
        try:
            data = json.loads(raw)
        except Exception:
            self.preview.setPlainText(raw)
            return

        # Inject optional flags into args & env cleanly
        root_key = "servers" if client == "vscode" else "mcpServers"
        srv_obj = (data.get(root_key) or {}).get("token-context")
        if isinstance(srv_obj, dict):
            args = list(srv_obj.get("args") or [])
            if self.chk_admin.isChecked() and "--enable-admin-tools" not in args:
                args.append("--enable-admin-tools")
            if self.chk_text.isChecked() and "--output-mode" not in args:
                args.extend(["--output-mode", "text"])
            srv_obj["args"] = args
            agent_id = self.agent_id_input.text().strip()
            if agent_id:
                env = dict(srv_obj.get("env") or {})
                env["TOKEN_CONTEXT_AGENT_ID"] = agent_id
                srv_obj["env"] = env
        self.preview.setPlainText(json.dumps(data, indent=2))
        self.copy_btn.setText("Copy to Clipboard")
        self.copy_btn.setEnabled(True)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.preview.toPlainText())
        self.copy_btn.setText("Copied!")
        self.copy_btn.setEnabled(False)
        QTimer.singleShot(1500, self._reset_copy_btn)

    def _reset_copy_btn(self) -> None:
        self.copy_btn.setText("Copy to Clipboard")
        self.copy_btn.setEnabled(True)


class DashboardTab(QWidget):
    def __init__(
        self,
        repo_mgr: RepoManager,
        server_ctrl: ServerController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.repo_mgr = repo_mgr
        self.server_ctrl = server_ctrl

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # 1. System Telemetry & Compute Card
        tel_card = QFrame()
        tel_card.setProperty("class", "Card")
        t_layout = QVBoxLayout(tel_card)
        t_layout.setContentsMargins(16, 14, 16, 14)
        t_layout.setSpacing(10)

        t_title = QLabel("System Telemetry & Host Runtime")
        t_title.setProperty("class", "SectionTitle")
        t_layout.addWidget(t_title)

        cpu_row = QHBoxLayout()
        cpu_row.setSpacing(12)
        self.cpu_label = QLabel("CPU Usage: --% (-- threads)")
        self.cpu_label.setMinimumWidth(220)
        self.cpu_bar = QProgressBar()
        self.cpu_bar.setRange(0, 100)
        self.cpu_bar.setValue(0)
        cpu_row.addWidget(self.cpu_label)
        cpu_row.addWidget(self.cpu_bar, 1)
        t_layout.addLayout(cpu_row)

        ram_row = QHBoxLayout()
        ram_row.setSpacing(12)
        self.ram_label = QLabel("RAM Usage: -- / -- GB (--%)")
        self.ram_label.setMinimumWidth(220)
        self.ram_bar = QProgressBar()
        self.ram_bar.setRange(0, 100)
        self.ram_bar.setValue(0)
        ram_row.addWidget(self.ram_label)
        ram_row.addWidget(self.ram_bar, 1)
        t_layout.addLayout(ram_row)

        hw_row = QHBoxLayout()
        hw_row.setSpacing(14)
        self.hw_label = QLabel("Host Compute: Detecting...")
        self.hw_label.setStyleSheet(f"color: {COLOR_ACCENT}; font-weight: 500;")
        self.disk_label = QLabel("Disk Free: -- GB")
        self.disk_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        hw_row.addWidget(self.hw_label, 1)
        hw_row.addWidget(self.disk_label)
        t_layout.addLayout(hw_row)

        layout.addWidget(tel_card)

        # 2. Running MCP Servers Card
        srv_card = QFrame()
        srv_card.setProperty("class", "Card")
        s_layout = QVBoxLayout(srv_card)
        s_layout.setContentsMargins(16, 14, 16, 14)
        s_layout.setSpacing(10)

        s_header = QHBoxLayout()
        s_title = QLabel("Running MCP Servers")
        s_title.setProperty("class", "SectionTitle")
        s_header.addWidget(s_title)
        s_header.addStretch()

        self.copy_cfg_btn = QPushButton("Copy Client Config")
        self.copy_cfg_btn.setIcon(make_icon("copy", COLOR_TEXT_PRIMARY))
        self.copy_cfg_btn.clicked.connect(self._open_copy_dialog)
        s_header.addWidget(self.copy_cfg_btn)
        s_layout.addLayout(s_header)

        self.srv_table = QTableWidget(0, 6)
        self.srv_table.setHorizontalHeaderLabels(["Server", "PID", "Client", "Output Mode", "Schema Profile", "Last Seen"])
        self.srv_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.srv_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.srv_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.srv_table.verticalHeader().setVisible(False)
        self.srv_table.setAlternatingRowColors(True)
        self.srv_table.setMaximumHeight(165)
        s_layout.addWidget(self.srv_table)

        self.srv_empty_label = QLabel(
            "No active MCP server processes detected. AI clients launch stdio servers automatically from their MCP configuration."
        )
        self.srv_empty_label.setWordWrap(True)
        self.srv_empty_label.setProperty("class", "MutedHint")
        s_layout.addWidget(self.srv_empty_label)
        layout.addWidget(srv_card)

        # 3. Quick Repository & Ledger Statistics Cards
        stat_card = QFrame()
        stat_card.setProperty("class", "Card")
        st_layout = QVBoxLayout(stat_card)
        st_layout.setContentsMargins(16, 14, 16, 14)
        st_layout.setSpacing(10)

        st_title = QLabel("Workspace Overview")
        st_title.setProperty("class", "SectionTitle")
        st_layout.addWidget(st_title)

        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(10)
        self.stat_repos = self._make_metric_box(metrics_row, "Registered Repos", "0")
        self.stat_files = self._make_metric_box(metrics_row, "Indexed Files", "0")
        self.stat_size = self._make_metric_box(metrics_row, "Active Snapshot DB", "0.0 MB")
        self.stat_ledger = self._make_metric_box(metrics_row, "Ledger Cards", "0")
        self.stat_ambig = self._make_metric_box(metrics_row, "Weighted Ambiguous", "0.0%")
        st_layout.addLayout(metrics_row)
        layout.addWidget(stat_card)

        layout.addStretch(1)
        self.servers_table = self.srv_table
        self._apply_running_servers([])

    def _make_metric_box(self, parent_layout: QHBoxLayout, label_text: str, init_val: str) -> QLabel:
        box = QFrame()
        box.setProperty("class", "SubCard")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(12, 10, 12, 10)
        bl.setSpacing(4)
        val_lbl = QLabel(init_val)
        val_lbl.setProperty("class", "MetricValue")
        cap_lbl = QLabel(label_text)
        cap_lbl.setProperty("class", "MetricLabel")
        cap_lbl.setWordWrap(True)
        bl.addWidget(val_lbl)
        bl.addWidget(cap_lbl)
        parent_layout.addWidget(box, 1)
        return val_lbl

    def _open_copy_dialog(self) -> None:
        CopyConfigDialog(self.server_ctrl, self).exec()

    def update_telemetry(self, data: Any) -> None:
        g = (lambda k, d=0.0: data.get(k, d)) if isinstance(data, dict) else (lambda k, d=0.0: getattr(data, k, d))
        cpu = float(g("cpu_percent", 0.0) or 0.0)
        cores = int(g("cpu_count_logical", g("cpu_count", 0)) or 0)
        ram_pct = float(g("ram_percent", 0.0) or 0.0)
        ram_used = float(g("ram_used_gb", 0.0) or 0.0)
        ram_tot = float(g("ram_total_gb", 0.0) or 0.0)
        disk_free = float(g("disk_free_gb", 0.0) or 0.0)
        disk_tot = float(g("disk_total_gb", 0.0) or 0.0)

        self.cpu_label.setText(f"CPU Usage: {cpu:.1f}% ({cores} threads)")
        self.cpu_bar.setValue(int(cpu))
        self.ram_label.setText(f"RAM Usage: {ram_used:.1f} / {ram_tot:.1f} GB ({ram_pct:.1f}%)")
        self.ram_bar.setValue(int(ram_pct))
        self.disk_label.setText(f"Disk Free: {disk_free:.1f} / {disk_tot:.1f} GB")

    def refresh(self) -> None:
        from token_context_mcp.gui.workers import run_async

        run_async(self.fetch, on_ok=self.render)

    def fetch(self) -> dict[str, Any]:
        """Worker-thread half: read hardware, running servers, repos, and ledger count."""
        assert not is_ui_thread(), "DashboardTab.fetch must run off the UI thread"
        ledger_cards = 0
        try:
            from token_context_mcp.ledger.service import LedgerService
            from token_context_mcp.config import load_config

            cfg = load_config(self.repo_mgr.config_path)
            lsvc = LedgerService(cfg, self.repo_mgr.config_path)
            try:
                ledger_cards = len(lsvc.list_cards())
            finally:
                lsvc.store.close()
        except Exception:
            pass

        return {
            "hw": detect_ai_hardware(),
            "servers": self.repo_mgr.fetch_active_servers(),
            "repos": self.repo_mgr.list_repositories(),
            "ledger_cards": ledger_cards,
        }

    def render(self, snap: dict[str, Any]) -> None:
        assert is_ui_thread(), "DashboardTab.render must run on the UI thread"
        self.hw_label.setText(f"Host Compute: {snap['hw']}")
        self._apply_running_servers(snap["servers"])

        repos = snap["repos"]
        total_files = sum(r["files_count"] for r in repos)
        total_mb = sum(r["db_size_mb"] for r in repos)
        total_edges = sum(int(r.get("edges_count", 0) or 0) for r in repos)
        if total_edges > 0:
            weighted_ambig = sum(
                float(r.get("ambiguous_rate", 0.0) or 0.0) * int(r.get("edges_count", 0) or 0)
                for r in repos
            ) / total_edges
        else:
            rates = [float(r.get("ambiguous_rate", 0.0) or 0.0) for r in repos]
            weighted_ambig = (sum(rates) / len(rates)) if rates else 0.0

        self.stat_repos.setText(str(len(repos)))
        self.stat_files.setText(f"{total_files:,}")
        self.stat_size.setText(f"{total_mb:.1f} MB")
        self.stat_ledger.setText(str(snap.get("ledger_cards", 0)))
        self.stat_ambig.setText(f"{weighted_ambig:.1f}%")

        if weighted_ambig > 30:
            self.stat_ambig.setStyleSheet(f"color: {COLOR_WARNING};")
        else:
            self.stat_ambig.setStyleSheet(f"color: {COLOR_SUCCESS};")

    def _apply_running_servers(self, servers: list[dict[str, Any]]) -> None:
        self.srv_table.setRowCount(len(servers))
        has_rows = len(servers) > 0
        self.srv_table.setVisible(has_rows)
        self.srv_empty_label.setVisible(not has_rows)
        for row, srv in enumerate(servers):
            vals = [
                srv.get("server_id", "-"),
                str(srv.get("pid", "-")),
                srv.get("client_name") or "unknown",
                srv.get("output_mode") or "-",
                srv.get("schema_profile") or "-",
                srv.get("last_seen_str", "-"),
            ]
            for col, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if col == 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.srv_table.setItem(row, col, item)

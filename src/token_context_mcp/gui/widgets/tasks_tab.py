from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
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

from token_context_mcp.gui.workers import run_async

if TYPE_CHECKING:
    from token_context_mcp.gui.bridge import RepoManager

MAX_LOG_BLOCKS = 5000
LOG_FLUSH_MS = 100


class TasksTab(QWidget):
    def __init__(self, repo_mgr: RepoManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repo_mgr = repo_mgr
        self._selected_repo = ""      # plain copy of the combo text, readable from workers
        self._log_buffer: list[str] = []
        self._log_timer = QTimer(self)
        self._log_timer.setInterval(LOG_FLUSH_MS)
        self._log_timer.timeout.connect(self.flush_logs)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Upper row: Visualizer Card (Language breakdown + Graph Precision)
        viz_card = QFrame()
        viz_card.setProperty("class", "Card")
        v_layout = QVBoxLayout(viz_card)
        v_layout.setSpacing(10)

        v_top = QHBoxLayout()
        v_title = QLabel("Codebase & Graph Visualizer")
        v_title.setProperty("class", "CardHeader")
        v_top.addWidget(v_title)
        v_top.addStretch()

        v_top.addWidget(QLabel("Select Repository:"))
        self.repo_selector = QComboBox()
        self.repo_selector.currentTextChanged.connect(self._on_repo_selected)
        v_top.addWidget(self.repo_selector)
        v_layout.addLayout(v_top)

        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)

        # Languages
        grid.addWidget(QLabel("Language Distribution:"), 0, 0)
        self.lang_label = QLabel("No data")
        self.lang_label.setStyleSheet("color: #89b4fa; font-weight: 600;")
        grid.addWidget(self.lang_label, 0, 1)

        # Edge Precision
        grid.addWidget(QLabel("Edge Precision (Lexical Graph):"), 1, 0)
        self.edge_bar = QProgressBar()
        self.edge_bar.setRange(0, 100)
        self.edge_bar.setValue(0)
        self.edge_bar.setFormat("%v% Resolved")
        grid.addWidget(self.edge_bar, 1, 1)

        v_layout.addLayout(grid)

        # Top Entry Points / Symbols Table
        ep_label = QLabel("Top Entry Points & Architectural Roles:")
        ep_label.setStyleSheet("font-size: 12px; font-weight: 600; color: #a5adcb; margin-top: 4px;")
        v_layout.addWidget(ep_label)

        self.ep_table = QTableWidget()
        self.ep_table.setColumnCount(3)
        self.ep_table.setHorizontalHeaderLabels(["Role", "Target / Symbol", "Status / Evidence"])
        self.ep_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.ep_table.verticalHeader().setVisible(False)
        self.ep_table.setMaximumHeight(130)
        v_layout.addWidget(self.ep_table)

        layout.addWidget(viz_card)

        # Lower row: Real-time Console Log Viewer
        log_card = QFrame()
        log_card.setProperty("class", "Card")
        l_layout = QVBoxLayout(log_card)
        l_layout.setSpacing(8)

        l_top = QHBoxLayout()
        l_title = QLabel("Real-Time Task Stream & Console Logs")
        l_title.setProperty("class", "CardHeader")
        l_top.addWidget(l_title)
        l_top.addStretch()

        clear_btn = QPushButton("Clear Console")
        clear_btn.clicked.connect(self.clear_logs)
        l_top.addWidget(clear_btn)
        l_layout.addLayout(l_top)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(MAX_LOG_BLOCKS)  # M8.4: the log can no longer grow without bound
        self.console.setProperty("class", "LogConsole")
        self.console.setStyleSheet("background-color: #11111b; font-family: monospace; font-size: 12px; color: #a6da95;")
        l_layout.addWidget(self.console, 1)

        layout.addWidget(log_card, 1)

    # -- log: collected and appended once per 100 ms (M8.4) ---------------------------------------------------------
    def append_log(self, text: str) -> None:
        self._log_buffer.append(text)
        if not self._log_timer.isActive():
            self._log_timer.start()

    def flush_logs(self) -> None:
        if not self._log_buffer:
            self._log_timer.stop()
            return
        chunk, self._log_buffer = "\n".join(self._log_buffer), []
        self.console.appendPlainText(chunk)
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

    def clear_logs(self) -> None:
        self._log_buffer.clear()
        self.console.clear()

    # -- fetch / render (M8.2) ---------------------------------------------------------------------------------------
    def fetch(self) -> dict:
        """Worker-side: repository ids and the detail of the selected one."""
        repos = self.repo_mgr.list_repositories()
        ids = [r["repo_id"] for r in repos]
        current = self._selected_repo if self._selected_repo in ids else (ids[0] if ids else "")
        return {"ids": ids, "current": current, "detail": self.repo_mgr.repo_detail(current) if current else None}

    def render(self, data: dict) -> None:
        self.repo_selector.blockSignals(True)
        self.repo_selector.clear()
        for repo_id in data["ids"]:
            self.repo_selector.addItem(repo_id)
        if data["current"]:
            self.repo_selector.setCurrentText(data["current"])
        self.repo_selector.blockSignals(False)
        self._selected_repo = data["current"]
        self.render_detail(data["detail"])

    def refresh_repositories(self) -> None:
        run_async(self.fetch, on_ok=self.render)

    def _on_repo_selected(self, repo_id: str) -> None:
        self._selected_repo = repo_id
        if not repo_id:
            self.render_detail(None)
            return
        run_async(self.repo_mgr.repo_detail, repo_id, on_ok=self.render_detail)

    def render_detail(self, detail: dict | None) -> None:
        if not detail:
            self.lang_label.setText("No repository selected")
            self.edge_bar.setValue(0)
            self.ep_table.setRowCount(0)
            return
        if not detail.get("indexed"):
            self.lang_label.setText("Not indexed yet")
            self.edge_bar.setValue(0)
            self.ep_table.setRowCount(0)
            return
        langs = detail.get("languages") or []
        self.lang_label.setText(", ".join(langs).title() if langs else "None detected")
        rate = detail.get("resolved_rate")
        self.edge_bar.setValue(100 if rate is None else max(0, min(100, int(rate * 100))))
        entry_points = detail.get("entry_points") or []
        self.ep_table.setRowCount(len(entry_points))
        for i, ep in enumerate(entry_points):
            self.ep_table.setItem(i, 0, QTableWidgetItem("Declared Script"))
            self.ep_table.setItem(i, 1, QTableWidgetItem(ep.get("declared", "entry_point")))
            self.ep_table.setItem(i, 2, QTableWidgetItem("Resolved" if ep.get("resolved") else "Unresolved"))

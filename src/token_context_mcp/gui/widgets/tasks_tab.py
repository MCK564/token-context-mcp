from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
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

if TYPE_CHECKING:
    from token_context_mcp.gui.bridge import RepoManager


class TasksTab(QWidget):
    def __init__(self, repo_mgr: RepoManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repo_mgr = repo_mgr

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
        self.console.setProperty("class", "LogConsole")
        self.console.setStyleSheet("background-color: #11111b; font-family: monospace; font-size: 12px; color: #a6da95;")
        l_layout.addWidget(self.console, 1)

        layout.addWidget(log_card, 1)

        self.refresh_repositories()

    def append_log(self, text: str) -> None:
        self.console.appendPlainText(text)
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

    def clear_logs(self) -> None:
        self.console.clear()

    def refresh_repositories(self) -> None:
        repos = self.repo_mgr.list_repositories()
        current = self.repo_selector.currentText()
        self.repo_selector.clear()
        for r in repos:
            self.repo_selector.addItem(r["repo_id"])
        if current and self.repo_selector.findText(current) >= 0:
            self.repo_selector.setCurrentText(current)
        elif self.repo_selector.count() > 0:
            self.repo_selector.setCurrentIndex(0)

    def _on_repo_selected(self, repo_id: str) -> None:
        if not repo_id:
            self.lang_label.setText("No repository selected")
            self.edge_bar.setValue(0)
            self.ep_table.setRowCount(0)
            return

        import json
        import sqlite3
        from token_context_mcp.index.runner import database_path, manifest_path

        idx_dir = self.repo_mgr.get_index_dir()
        db_path = database_path(idx_dir, repo_id)
        mf_path = manifest_path(idx_dir, repo_id)

        if not db_path.exists() or not mf_path.exists():
            self.lang_label.setText("Not indexed yet")
            self.edge_bar.setValue(0)
            self.ep_table.setRowCount(0)
            return

        try:
            mf_data = json.loads(mf_path.read_text(encoding="utf-8"))

            # Languages
            parsers = mf_data.get("parser_versions", {})
            langs = parsers.get("languages", [])
            self.lang_label.setText(", ".join(langs).title() if langs else "None detected")

            # Fast edge precision
            resolved_pct = 100
            try:
                con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
                cur = con.cursor()
                cur.execute("SELECT count(*), count(CASE WHEN status='ambiguous' THEN 1 END) FROM edges;")
                row = cur.fetchone()
                con.close()
                if row and row[0] > 0:
                    resolved_pct = max(0, min(100, int(((row[0] - row[1]) / row[0]) * 100)))
            except Exception:
                pass
            self.edge_bar.setValue(resolved_pct)

            # Entry points
            entry_points = mf_data.get("entry_points", [])
            self.ep_table.setRowCount(len(entry_points))
            for i, ep in enumerate(entry_points):
                decl = ep.get("declared", "entry_point")
                res = "Resolved" if ep.get("resolved") else "Unresolved"
                self.ep_table.setItem(i, 0, QTableWidgetItem("Declared Script"))
                self.ep_table.setItem(i, 1, QTableWidgetItem(decl))
                self.ep_table.setItem(i, 2, QTableWidgetItem(res))

        except Exception as e:
            self.lang_label.setText(f"Error reading metadata: {e}")
            self.edge_bar.setValue(0)
            self.ep_table.setRowCount(0)

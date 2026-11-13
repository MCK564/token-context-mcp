from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
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

from token_context_mcp.gui.bridge import RepoManager
from token_context_mcp.gui.icons import make_icon
from token_context_mcp.gui.theme import (
    COLOR_ACCENT,
    COLOR_DANGER,
    COLOR_SUCCESS,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_WARNING,
)
from token_context_mcp.gui.workers import is_ui_thread, run_async


class TasksTab(QWidget):
    """Codebase Insights / Symbol Explorer + Real-Time Indexing Log Stream."""

    def __init__(self, repo_mgr: RepoManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repo_mgr = repo_mgr
        self._pending_logs: list[str] = []
        self._log_timer = QTimer(self)
        self._log_timer.setInterval(100)
        self._log_timer.timeout.connect(self.flush_logs)
        self._cached_repos: list[dict[str, Any]] = []

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

        # 1. Codebase & Symbol Insights Card
        graph_card = QFrame()
        graph_card.setProperty("class", "Card")
        g_layout = QVBoxLayout(graph_card)
        g_layout.setContentsMargins(16, 14, 16, 14)
        g_layout.setSpacing(10)

        g_header = QHBoxLayout()
        g_header.setSpacing(10)
        g_title = QLabel("Codebase & Symbol Explorer")
        g_title.setProperty("class", "SectionTitle")
        g_header.addWidget(g_title)
        g_header.addStretch()

        g_header.addWidget(QLabel("Repository:"))
        self.repo_combo = QComboBox()
        self.repo_combo.setMinimumWidth(190)
        self.repo_combo.currentTextChanged.connect(self._on_repo_selected)
        g_header.addWidget(self.repo_combo)
        g_layout.addLayout(g_header)

        # Stats row
        lang_row = QHBoxLayout()
        lang_row.setSpacing(10)
        lbl_lang = QLabel("Languages:")
        lbl_lang.setMinimumWidth(140)
        self.lang_label = QLabel("-")
        self.lang_label.setStyleSheet(f"color: {COLOR_ACCENT}; font-weight: 500;")
        lang_row.addWidget(lbl_lang)
        lang_row.addWidget(self.lang_label, 1)
        g_layout.addLayout(lang_row)

        prec_row = QHBoxLayout()
        prec_row.setSpacing(10)
        lbl_prec = QLabel("Lexical Edge Precision:")
        lbl_prec.setMinimumWidth(140)
        self.precision_bar = QProgressBar()
        self.precision_bar.setRange(0, 100)
        self.precision_bar.setValue(0)
        self.precision_bar.setFormat("%p% Resolved")
        prec_row.addWidget(lbl_prec)
        prec_row.addWidget(self.precision_bar, 1)
        g_layout.addLayout(prec_row)

        self.roles_summary = QLabel("Architectural Roles: -")
        self.roles_summary.setProperty("class", "MutedHint")
        self.roles_summary.setWordWrap(True)
        g_layout.addWidget(self.roles_summary)

        # Symbol filter bar
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.sym_search = QLineEdit()
        self.sym_search.setPlaceholderText("Filter indexed symbols by qualified name or path (e.g. Service, route)...")
        self.sym_search.setClearButtonEnabled(True)
        self.sym_search.returnPressed.connect(self._run_symbol_search)
        self.search_btn = QPushButton("Search")
        self.search_btn.setIcon(make_icon("search", COLOR_TEXT_PRIMARY))
        self.search_btn.clicked.connect(self._run_symbol_search)
        search_row.addWidget(self.sym_search, 1)
        search_row.addWidget(self.search_btn)
        g_layout.addLayout(search_row)

        self.ep_table = QTableWidget(0, 4)
        self.ep_table.setHorizontalHeaderLabels(["Symbol", "Kind", "Location", "Roles"])
        ep_header = self.ep_table.horizontalHeader()
        ep_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        ep_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        ep_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        ep_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.ep_table.verticalHeader().setVisible(False)
        self.ep_table.setAlternatingRowColors(True)
        self.ep_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.ep_table.setMinimumHeight(180)
        g_layout.addWidget(self.ep_table)

        layout.addWidget(graph_card)

        # 2. Live Task Stream & Console Logs Card
        log_card = QFrame()
        log_card.setProperty("class", "Card")
        l_layout = QVBoxLayout(log_card)
        l_layout.setContentsMargins(16, 14, 16, 14)
        l_layout.setSpacing(10)

        l_header = QHBoxLayout()
        l_title = QLabel("Real-Time Task Stream & Console Logs")
        l_title.setProperty("class", "SectionTitle")
        l_header.addWidget(l_title)
        l_header.addStretch()

        clear_btn = QPushButton("Clear Console")
        clear_btn.setIcon(make_icon("trash", COLOR_TEXT_PRIMARY))
        clear_btn.clicked.connect(self._clear_console)
        l_header.addWidget(clear_btn)
        l_layout.addLayout(l_header)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(5000)
        self.console.setMinimumHeight(160)
        self.console.setPlaceholderText("Background indexing logs and GUI events will stream here...")
        self.console.setStyleSheet(
            "font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 12px;"
        )
        l_layout.addWidget(self.console, 1)

        layout.addWidget(log_card, 1)

    def _clear_console(self) -> None:
        self._pending_logs.clear()
        self.console.clear()

    def append_log(self, text: str) -> None:
        self._pending_logs.append(text)
        if not self._log_timer.isActive():
            self._log_timer.start()

    def flush_logs(self) -> None:
        if not self._pending_logs:
            self._log_timer.stop()
            return
        chunk = "\n".join(self._pending_logs)
        self._pending_logs.clear()
        self._log_timer.stop()
        self.console.appendPlainText(chunk)
        scrollbar = self.console.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def refresh(self) -> None:
        run_async(self.fetch, on_ok=self.render)

    def fetch(self) -> dict[str, Any]:
        assert not is_ui_thread(), "TasksTab.fetch must run off the UI thread"
        repos = self.repo_mgr.list_repositories()
        first_id = repos[0]["repo_id"] if repos else ""
        insights = self.repo_mgr.get_repo_insights(first_id, query="", limit=30) if first_id else {}
        return {"repos": repos, "insights": insights, "insights_repo": first_id}

    def render(self, payload: dict[str, Any] | list[dict[str, Any]]) -> None:
        assert is_ui_thread(), "TasksTab.render must run on the UI thread"
        if isinstance(payload, list):
            repos = payload
            insights = {}
            insights_repo = ""
        else:
            repos = payload.get("repos", [])
            insights = payload.get("insights", {})
            insights_repo = str(payload.get("insights_repo", ""))

        self._cached_repos = repos
        current = self.repo_combo.currentText()
        self.repo_combo.blockSignals(True)
        self.repo_combo.clear()
        for r in repos:
            self.repo_combo.addItem(r["repo_id"])
        if current and any(r["repo_id"] == current for r in repos):
            self.repo_combo.setCurrentText(current)
            target_id = current
        elif repos:
            target_id = repos[0]["repo_id"]
        else:
            target_id = ""
        self.repo_combo.blockSignals(False)

        if target_id:
            if target_id == insights_repo and insights:
                self._apply_repo_meta(target_id)
                self._render_insights(insights)
            else:
                self._on_repo_selected(target_id)
        else:
            self.lang_label.setText("-")
            self.precision_bar.setValue(0)
            self.roles_summary.setText("Architectural Roles: -")
            self.ep_table.setRowCount(0)

    def _apply_repo_meta(self, repo_id: str) -> None:
        target = next((r for r in self._cached_repos if r["repo_id"] == repo_id), None)
        if not target:
            return
        langs = target.get("languages")
        if isinstance(langs, dict) and langs:
            lang_str = ", ".join(f"{k.title()} ({v})" for k, v in sorted(langs.items(), key=lambda x: -x[1]))
        elif isinstance(langs, list) and langs:
            lang_str = ", ".join(str(x).title() for x in langs)
        else:
            lang_str = "None detected"
        self.lang_label.setText(lang_str)

        ambig = float(target.get("ambiguous_rate", 0.0) or 0.0)
        resolved_pct = max(0, min(100, int(100 - ambig)))
        self.precision_bar.setValue(resolved_pct)
        chunk_color = COLOR_SUCCESS if resolved_pct >= 75 else (COLOR_WARNING if resolved_pct >= 50 else COLOR_DANGER)
        self.precision_bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {chunk_color}; border-radius: 5px; }}")

    def _on_repo_selected(self, repo_id: str) -> None:
        if not repo_id:
            return
        self._apply_repo_meta(repo_id)
        q = self.sym_search.text().strip()
        run_async(
            lambda: self.repo_mgr.get_repo_insights(repo_id, query=q, limit=30),
            on_ok=self._render_insights,
        )

    def _run_symbol_search(self) -> None:
        rid = self.repo_combo.currentText()
        if rid:
            self._on_repo_selected(rid)

    def _render_insights(self, insights: dict[str, Any]) -> None:
        role_counts = insights.get("role_counts", {})
        if role_counts:
            roles_txt = ", ".join(f"{k}: {v}" for k, v in sorted(role_counts.items(), key=lambda x: -x[1])[:8])
            self.roles_summary.setText(f"Architectural Roles ({insights.get('total_symbols', 0)} symbols): {roles_txt}")
        else:
            self.roles_summary.setText(f"Total Symbols: {insights.get('total_symbols', 0)} (no role tags)")

        syms = insights.get("symbols", [])
        self.ep_table.setRowCount(len(syms))
        for row, s in enumerate(syms):
            self.ep_table.setItem(row, 0, QTableWidgetItem(str(s.get("qualified_name", ""))))
            self.ep_table.setItem(row, 1, QTableWidgetItem(str(s.get("kind", ""))))
            self.ep_table.setItem(row, 2, QTableWidgetItem(f"{s.get('path', '')}:{s.get('line', 1)}"))
            self.ep_table.setItem(row, 3, QTableWidgetItem(str(s.get("roles", "-"))))

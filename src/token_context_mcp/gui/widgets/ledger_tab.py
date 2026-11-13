from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from token_context_mcp.gui.bridge import LedgerController, RepoManager
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


class LedgerTab(QWidget):
    """Inspector & lifecycle manager for Verified Evidence Ledger ('Lá Phổi') and Episodic Memory."""

    def __init__(self, repo_mgr: RepoManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repo_mgr = repo_mgr
        self.ctrl = LedgerController(repo_mgr.config_path)
        self._cards: list[dict[str, Any]] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Summary header bar
        sum_card = QFrame()
        sum_card.setProperty("class", "Card")
        s_layout = QHBoxLayout(sum_card)
        s_layout.setContentsMargins(14, 10, 14, 10)
        s_layout.setSpacing(12)

        self.status_badge = QLabel("Ledger: Active")
        self.status_badge.setProperty("class", "BadgeFresh")
        s_layout.addWidget(self.status_badge)

        self.summary_label = QLabel("Cards: 0 | Confirmed: 0 | Active: 0")
        self.summary_label.setProperty("class", "MutedHint")
        s_layout.addWidget(self.summary_label, 1)

        s_layout.addWidget(QLabel("Repo Filter:"))
        self.repo_filter = QComboBox()
        self.repo_filter.setMinimumWidth(140)
        self.repo_filter.addItem("All Repositories")
        self.repo_filter.currentTextChanged.connect(lambda _: self.refresh())
        s_layout.addWidget(self.repo_filter)
        layout.addWidget(sum_card)

        # Sub-tabs: Evidence Ledger vs Episodic Memory
        self.sub_tabs = QTabWidget()
        layout.addWidget(self.sub_tabs, 1)

        # --- Sub-tab 1: Evidence Ledger ---
        ledger_page = QWidget()
        lp_layout = QVBoxLayout(ledger_page)
        lp_layout.setContentsMargins(12, 12, 12, 12)
        lp_layout.setSpacing(10)

        act_row = QHBoxLayout()
        act_row.setSpacing(8)
        self.btn_confirm = QPushButton("Confirm Card")
        self.btn_confirm.setIcon(make_icon("check", COLOR_SUCCESS))
        self.btn_confirm.clicked.connect(self._confirm_selected)

        self.btn_forget = QPushButton("Forget Card")
        self.btn_forget.setIcon(make_icon("trash", COLOR_DANGER))
        self.btn_forget.setProperty("class", "DangerButton")
        self.btn_forget.clicked.connect(self._forget_selected)

        self.btn_prune = QPushButton("Prune Expired")
        self.btn_prune.setIcon(make_icon("broom", COLOR_TEXT_PRIMARY))
        self.btn_prune.clicked.connect(self._prune_cards)

        self.btn_export_md = QPushButton("Export Markdown")
        self.btn_export_md.setIcon(make_icon("export", COLOR_TEXT_PRIMARY))
        self.btn_export_md.clicked.connect(lambda: self._export("md"))

        self.btn_export_json = QPushButton("Export JSON")
        self.btn_export_json.setIcon(make_icon("export", COLOR_TEXT_PRIMARY))
        self.btn_export_json.clicked.connect(lambda: self._export("json"))

        for b in (self.btn_confirm, self.btn_forget, self.btn_prune, self.btn_export_md, self.btn_export_json):
            act_row.addWidget(b)
        act_row.addStretch()
        lp_layout.addLayout(act_row)

        self.cards_table = QTableWidget(0, 7)
        self.cards_table.setHorizontalHeaderLabels(
            ["ID", "Repo", "Status", "Confirms", "Items", "Signature Tokens", "Agent"]
        )
        ch = self.cards_table.horizontalHeader()
        ch.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        ch.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.cards_table.verticalHeader().setVisible(False)
        self.cards_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.cards_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.cards_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.cards_table.setAlternatingRowColors(True)
        self.cards_table.setMinimumHeight(180)
        self.cards_table.itemSelectionChanged.connect(self._on_card_selected)
        lp_layout.addWidget(self.cards_table, 1)

        det_lbl = QLabel("Selected Card Citations (Verified Answers, Multi-Hop Steps, Decoys):")
        det_lbl.setProperty("class", "MutedHint")
        lp_layout.addWidget(det_lbl)

        self.detail_view = QPlainTextEdit()
        self.detail_view.setReadOnly(True)
        self.detail_view.setMinimumHeight(135)
        self.detail_view.setMaximumHeight(185)
        self.detail_view.setPlaceholderText("Select a card row to inspect stored path:line citations and SHA-256 digests...")
        self.detail_view.setStyleSheet("font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 12px;")
        lp_layout.addWidget(self.detail_view)

        self.sub_tabs.addTab(ledger_page, "Evidence Ledger")

        # --- Sub-tab 2: Episodic Memory ---
        mem_page = QWidget()
        mp_layout = QVBoxLayout(mem_page)
        mp_layout.setContentsMargins(12, 12, 12, 12)
        mp_layout.setSpacing(8)

        self.memory_table = QTableWidget(0, 4)
        self.memory_table.setHorizontalHeaderLabels(["Namespace", "Key", "Value Preview", "Updated"])
        mh = self.memory_table.horizontalHeader()
        mh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        mh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        mh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        mh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.memory_table.verticalHeader().setVisible(False)
        self.memory_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.memory_table.setAlternatingRowColors(True)
        mp_layout.addWidget(self.memory_table, 1)

        self.sub_tabs.addTab(mem_page, "Episodic Memory")

    def _current_repo_filter(self) -> str | None:
        txt = self.repo_filter.currentText()
        if not txt or txt == "All Repositories":
            return None
        return txt

    def refresh(self) -> None:
        rid = self._current_repo_filter()
        run_async(lambda: self.fetch(rid), on_ok=self.render)

    def fetch(self, repo_id: str | None = None) -> dict[str, Any]:
        assert not is_ui_thread(), "LedgerTab.fetch must run off the UI thread"
        return self.ctrl.fetch_snapshot(repo_id=repo_id)

    def render(self, snap: dict[str, Any]) -> None:
        assert is_ui_thread(), "LedgerTab.render must run on the UI thread"
        enabled = bool(snap.get("enabled", True))
        overlay = bool(snap.get("overlay_enabled", False))
        self.status_badge.setText(
            f"Ledger: {'ON' if enabled else 'OFF'} · Overlay: {'ON' if overlay else 'OFF'}"
        )
        self.status_badge.setProperty("class", "BadgeFresh" if enabled else "BadgeWarning")
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)

        s = snap.get("summary", {})
        self.summary_label.setText(
            f"Total: {s.get('total_cards', 0)} · Active: {s.get('active', 0)} · Confirmed: {s.get('confirmed', 0)} · Retired: {s.get('retired', 0)}"
        )

        # Update repo filter choices without recursive signal
        repos = snap.get("repos", [])
        cur = self.repo_filter.currentText()
        self.repo_filter.blockSignals(True)
        self.repo_filter.clear()
        self.repo_filter.addItem("All Repositories")
        for r in repos:
            self.repo_filter.addItem(r)
        if cur and (cur == "All Repositories" or cur in repos):
            self.repo_filter.setCurrentText(cur)
        self.repo_filter.blockSignals(False)

        cards = snap.get("cards", [])
        self._cards = cards
        self.cards_table.setRowCount(len(cards))
        for row, c in enumerate(cards):
            status = str(c.get("status", "asserted"))
            st_item = QTableWidgetItem(status)
            st_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if status == "confirmed":
                st_item.setForeground(QColor(COLOR_SUCCESS))
            elif status == "retired":
                st_item.setForeground(QColor(COLOR_DANGER))
            else:
                st_item.setForeground(QColor(COLOR_WARNING))

            self.cards_table.setItem(row, 0, QTableWidgetItem(str(c.get("card_id", ""))))
            self.cards_table.setItem(row, 1, QTableWidgetItem(str(c.get("repo_id", ""))))
            self.cards_table.setItem(row, 2, st_item)
            self.cards_table.setItem(row, 3, QTableWidgetItem(str(c.get("confirmations", 0))))
            self.cards_table.setItem(row, 4, QTableWidgetItem(str(c.get("items_count", 0))))
            self.cards_table.setItem(row, 5, QTableWidgetItem(", ".join(c.get("sig_tokens", []))))
            self.cards_table.setItem(row, 6, QTableWidgetItem(str(c.get("agent_id", ""))))

        if not cards:
            self.detail_view.setPlainText("No verified ledger cards recorded yet.")

        mem_rows = snap.get("memory_entries", [])
        self.memory_table.setRowCount(len(mem_rows))
        for row, m in enumerate(mem_rows):
            self.memory_table.setItem(row, 0, QTableWidgetItem(str(m.get("namespace", ""))))
            self.memory_table.setItem(row, 1, QTableWidgetItem(str(m.get("key", ""))))
            self.memory_table.setItem(row, 2, QTableWidgetItem(str(m.get("value", ""))))
            self.memory_table.setItem(row, 3, QTableWidgetItem(str(m.get("updated_at", ""))))

    def _selected_card_id(self) -> int | None:
        row = self.cards_table.currentRow()
        if row < 0:
            return None
        item = self.cards_table.item(row, 0)
        return int(item.text()) if item and item.text().isdigit() else None

    def _on_card_selected(self) -> None:
        cid = self._selected_card_id()
        if cid is None:
            return
        run_async(
            lambda: self.ctrl.show_card(cid),
            on_ok=lambda card: self.detail_view.setPlainText(
                json.dumps(card, indent=2, ensure_ascii=False) if card else "Card not found."
            ),
        )

    def _confirm_selected(self) -> None:
        cid = self._selected_card_id()
        if cid is None:
            return
        run_async(lambda: self.ctrl.confirm_card(cid), on_ok=lambda _: self.refresh())

    def _forget_selected(self) -> None:
        cid = self._selected_card_id()
        if cid is None:
            return
        reply = QMessageBox.question(
            self,
            "Forget Card",
            f"Delete ledger card #{cid}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            run_async(lambda: self.ctrl.forget_card(cid), on_ok=lambda _: self.refresh())

    def _prune_cards(self) -> None:
        rid = self._current_repo_filter()
        run_async(
            lambda: self.ctrl.prune_cards(repo_id=rid),
            on_ok=lambda n: (
                QMessageBox.information(self, "Prune Complete", f"Pruned {n} expired or retired card(s)."),
                self.refresh(),
            ),
        )

    def _export(self, fmt: str) -> None:
        rid = self._current_repo_filter()
        ext = "md" if fmt == "md" else "json"
        dest, _ = QFileDialog.getSaveFileName(self, f"Export Ledger ({ext.upper()})", f"ledger_export.{ext}")
        if not dest:
            return

        def _do() -> str:
            text = self.ctrl.export_cards(repo_id=rid, fmt=fmt)
            Path(dest).write_text(text + "\n", encoding="utf-8")
            return dest

        run_async(
            _do,
            on_ok=lambda path: QMessageBox.information(self, "Export Complete", f"Saved to {path}"),
            on_err=lambda e: QMessageBox.warning(self, "Export Failed", str(e)),
        )

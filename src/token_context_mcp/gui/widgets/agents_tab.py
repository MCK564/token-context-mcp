from __future__ import annotations

import json
import time
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from token_context_mcp.gui.bridge import AgentSecurityController, RepoManager
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
from token_context_mcp.gui.workers import is_ui_thread, run_async


class AgentsTab(QWidget):
    """Agent Access Governance, Mutex Lock Oversight, and WAL Audit Forensics."""

    def __init__(
        self,
        security_ctrl: AgentSecurityController,
        repo_mgr: RepoManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.security_ctrl = security_ctrl
        self.repo_mgr = repo_mgr
        self._last_snapshot: dict[str, Any] = {}

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

        # 1. Emergency Control Bar
        ctrl_bar = QFrame()
        ctrl_bar.setProperty("class", "Card")
        c_layout = QHBoxLayout(ctrl_bar)
        c_layout.setContentsMargins(14, 10, 14, 10)
        c_layout.setSpacing(10)

        self.status_indicator = QLabel("All Agents Authorized")
        self.status_indicator.setProperty("class", "BadgeFresh")
        c_layout.addWidget(self.status_indicator)
        c_layout.addStretch()

        self.revoke_all_btn = QPushButton("Revoke All Locks")
        self.revoke_all_btn.setIcon(make_icon("unlock", COLOR_TEXT_PRIMARY))
        self.revoke_all_btn.clicked.connect(self._on_revoke_all_locks)
        c_layout.addWidget(self.revoke_all_btn)

        self.resume_all_btn = QPushButton("Resume Normal")
        self.resume_all_btn.setIcon(make_icon("play", COLOR_TEXT_PRIMARY))
        self.resume_all_btn.setEnabled(False)
        self.resume_all_btn.clicked.connect(self._on_emergency_resume)
        c_layout.addWidget(self.resume_all_btn)

        self.kill_btn = QPushButton("EMERGENCY STOP")
        self.kill_btn.setIcon(make_icon("stop", COLOR_CRUST))
        self.kill_btn.setProperty("class", "DangerSolidButton")
        self.kill_btn.clicked.connect(self._on_emergency_halt)
        c_layout.addWidget(self.kill_btn)

        layout.addWidget(ctrl_bar)

        # 2. Active Agents Section + Selection Toolbar (no 5s widget churn!)
        ag_header = QHBoxLayout()
        ag_header.setSpacing(8)
        ag_title = QLabel("Active Agents & Access Policies")
        ag_title.setProperty("class", "SectionTitle")
        ag_header.addWidget(ag_title)
        ag_header.addStretch()

        self.btn_pause_sel = QPushButton("Pause / Resume")
        self.btn_pause_sel.setIcon(make_icon("pause", COLOR_TEXT_PRIMARY))
        self.btn_pause_sel.clicked.connect(self._on_toggle_pause_selected)

        self.btn_revoke_sel = QPushButton("Revoke Locks")
        self.btn_revoke_sel.setIcon(make_icon("unlock", COLOR_TEXT_PRIMARY))
        self.btn_revoke_sel.clicked.connect(self._on_revoke_selected)

        self.btn_block_sel = QPushButton("Block / Unblock")
        self.btn_block_sel.setIcon(make_icon("stop", COLOR_DANGER))
        self.btn_block_sel.setProperty("class", "DangerButton")
        self.btn_block_sel.clicked.connect(self._on_toggle_block_selected)

        self.policy_combo = QComboBox()
        self.policy_combo.addItems(["FULL_ACCESS", "READ_ONLY", "CUSTOM"])
        self.policy_apply_btn = QPushButton("Apply Policy")
        self.policy_apply_btn.clicked.connect(self._on_apply_policy_selected)

        ag_header.addWidget(self.btn_pause_sel)
        ag_header.addWidget(self.btn_revoke_sel)
        ag_header.addWidget(self.btn_block_sel)
        ag_header.addWidget(self.policy_combo)
        ag_header.addWidget(self.policy_apply_btn)
        layout.addLayout(ag_header)

        self.agents_table = QTableWidget(0, 5)
        self.agents_table.setHorizontalHeaderLabels(
            ["Agent ID", "Role / Client", "Status", "Policy Profile", "Tool Calls"]
        )
        h1 = self.agents_table.horizontalHeader()
        h1.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h1.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h1.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h1.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        h1.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.agents_table.verticalHeader().setVisible(False)
        self.agents_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.agents_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.agents_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.agents_table.setAlternatingRowColors(True)
        self.agents_table.setMinimumHeight(130)
        self.agents_table.setMaximumHeight(185)
        self.agents_table.itemSelectionChanged.connect(self._sync_selected_policy_combo)
        layout.addWidget(self.agents_table)

        # 3. Active Resource Locks Section
        lk_header = QHBoxLayout()
        lk_title = QLabel("Active Mutex Resource Locks")
        lk_title.setProperty("class", "SectionTitle")
        lk_header.addWidget(lk_title)
        lk_header.addStretch()
        self.btn_release_lock = QPushButton("Force Release Selected Lock")
        self.btn_release_lock.clicked.connect(self._on_release_selected_lock)
        lk_header.addWidget(self.btn_release_lock)
        layout.addLayout(lk_header)

        self.locks_table = QTableWidget(0, 4)
        self.locks_table.setHorizontalHeaderLabels(["Resource Key", "Held By Agent", "Acquired At", "Remaining"])
        h2 = self.locks_table.horizontalHeader()
        h2.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h2.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h2.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h2.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.locks_table.verticalHeader().setVisible(False)
        self.locks_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.locks_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.locks_table.setAlternatingRowColors(True)
        self.locks_table.setMinimumHeight(105)
        self.locks_table.setMaximumHeight(140)
        layout.addWidget(self.locks_table)

        # 4. Security Audit Log Stream
        aud_header = QHBoxLayout()
        aud_title = QLabel("Security Audit Log Stream (WAL Forensics)")
        aud_title.setProperty("class", "SectionTitle")
        aud_header.addWidget(aud_title)
        aud_header.addStretch()
        aud_header.addWidget(QLabel("Filter Status:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["ALL", "SUCCESS", "DENIED", "PAUSED", "BLOCKED", "ERROR"])
        self.filter_combo.currentTextChanged.connect(self._on_filter_changed)
        aud_header.addWidget(self.filter_combo)
        layout.addLayout(aud_header)

        self.audit_table = QTableWidget(0, 6)
        self.audit_table.setHorizontalHeaderLabels(
            ["Time", "Agent ID", "Tool Called", "Status", "Duration (ms)", "Details / Reason"]
        )
        h3 = self.audit_table.horizontalHeader()
        h3.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h3.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h3.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h3.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        h3.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        h3.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.audit_table.verticalHeader().setVisible(False)
        self.audit_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.audit_table.setAlternatingRowColors(True)
        self.audit_table.setMinimumHeight(180)
        layout.addWidget(self.audit_table, 1)

        # Connect signals from background GovernanceRefreshWorker
        self.security_ctrl.agents_updated.connect(self._render_agents)
        self.security_ctrl.locks_updated.connect(self._render_locks)
        self.security_ctrl.audit_logs_updated.connect(self._render_audit)
        self.security_ctrl.emergency_state_changed.connect(self._render_emergency)

    def refresh(self) -> None:
        run_async(self.fetch, on_ok=self.render)

    def fetch(self) -> dict[str, Any]:
        assert not is_ui_thread(), "AgentsTab.fetch must run off the UI thread"
        return self.security_ctrl.collect_snapshot()

    def render(self, snap: dict[str, Any]) -> None:
        assert is_ui_thread(), "AgentsTab.render must run on the UI thread"
        self._last_snapshot = snap
        self.security_ctrl.apply_snapshot(snap)

    def _selected_agent(self) -> tuple[str, str] | None:
        row = self.agents_table.currentRow()
        if row < 0:
            return None
        aid_item = self.agents_table.item(row, 0)
        st_item = self.agents_table.item(row, 2)
        if not aid_item or not st_item:
            return None
        return aid_item.text(), st_item.text()

    def _sync_selected_policy_combo(self) -> None:
        row = self.agents_table.currentRow()
        if row < 0:
            return
        p_item = self.agents_table.item(row, 3)
        if p_item:
            self.policy_combo.setCurrentText(p_item.text())

    def _render_emergency(self, is_halted: bool, reason: str) -> None:
        if is_halted:
            self.status_indicator.setText(f"EMERGENCY STOP ACTIVE: {reason}")
            self.status_indicator.setProperty("class", "BadgeStale")
            self.resume_all_btn.setEnabled(True)
            self.kill_btn.setEnabled(False)
        else:
            self.status_indicator.setText("All Agents Authorized")
            self.status_indicator.setProperty("class", "BadgeFresh")
            self.resume_all_btn.setEnabled(False)
            self.kill_btn.setEnabled(True)
        self.status_indicator.style().unpolish(self.status_indicator)
        self.status_indicator.style().polish(self.status_indicator)

    def _render_agents(self, agents: list[dict[str, Any]]) -> None:
        selected = self._selected_agent()
        selected_id = selected[0] if selected else None

        self.agents_table.setRowCount(len(agents))
        for row, ag in enumerate(agents):
            aid = str(ag["agent_id"])
            status = str(ag["status"])
            policy = str(ag.get("policy_profile", "FULL_ACCESS"))

            self.agents_table.setItem(row, 0, QTableWidgetItem(aid))
            self.agents_table.setItem(row, 1, QTableWidgetItem(str(ag.get("role", "agent"))))

            st_item = QTableWidgetItem(status)
            st_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if status == "ACTIVE":
                st_item.setForeground(QColor(COLOR_SUCCESS))
            elif status == "PAUSED":
                st_item.setForeground(QColor(COLOR_WARNING))
            else:
                st_item.setForeground(QColor(COLOR_DANGER))
            self.agents_table.setItem(row, 2, st_item)

            pol_item = QTableWidgetItem(policy)
            pol_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.agents_table.setItem(row, 3, pol_item)

            calls_item = QTableWidgetItem(str(ag.get("tool_calls_count", 0)))
            calls_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.agents_table.setItem(row, 4, calls_item)

            if selected_id and aid == selected_id:
                self.agents_table.selectRow(row)

        if selected_id is None and agents:
            self.agents_table.selectRow(0)

    def _render_locks(self, locks: list[dict[str, Any]]) -> None:
        self.locks_table.setRowCount(len(locks))
        now = time.time()
        for row, lk in enumerate(locks):
            rem = max(0, int(lk.get("expires_at", 0) - now))
            acq = time.strftime("%H:%M:%S", time.localtime(lk.get("acquired_at", now)))
            self.locks_table.setItem(row, 0, QTableWidgetItem(str(lk["resource_key"])))
            self.locks_table.setItem(row, 1, QTableWidgetItem(str(lk["agent_id"])))
            self.locks_table.setItem(row, 2, QTableWidgetItem(acq))
            self.locks_table.setItem(row, 3, QTableWidgetItem(f"{rem}s"))

    def _on_filter_changed(self, _text: str) -> None:
        self.refresh()

    def _render_audit(self, logs: list[dict[str, Any]]) -> None:
        filt = self.filter_combo.currentText()
        if filt != "ALL":
            logs = [lg for lg in logs if lg.get("status") == filt]
        self.audit_table.setRowCount(len(logs))
        for row, lg in enumerate(logs):
            ts_str = time.strftime("%H:%M:%S", time.localtime(lg.get("timestamp", time.time())))
            status = str(lg.get("status", ""))
            st_item = QTableWidgetItem(status)
            st_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if status == "SUCCESS":
                st_item.setForeground(QColor(COLOR_SUCCESS))
            elif status in ("DENIED", "BLOCKED", "ERROR"):
                st_item.setForeground(QColor(COLOR_DANGER))
            elif status == "PAUSED":
                st_item.setForeground(QColor(COLOR_WARNING))

            details = lg.get("details", "{}")
            if isinstance(details, dict):
                details = json.dumps(details)

            self.audit_table.setItem(row, 0, QTableWidgetItem(ts_str))
            self.audit_table.setItem(row, 1, QTableWidgetItem(str(lg.get("agent_id", ""))))
            self.audit_table.setItem(row, 2, QTableWidgetItem(str(lg.get("tool_name", ""))))
            self.audit_table.setItem(row, 3, st_item)
            self.audit_table.setItem(row, 4, QTableWidgetItem(f"{lg.get('duration_ms', 0.0):.2f}"))
            self.audit_table.setItem(row, 5, QTableWidgetItem(str(details)[:220]))

    def _run_security_op(self, fn) -> None:
        run_async(fn, on_ok=lambda _: self.refresh(), on_err=lambda e: QMessageBox.warning(self, "Security Error", str(e)))

    def _on_toggle_pause_selected(self) -> None:
        sel = self._selected_agent()
        if not sel:
            return
        aid, status = sel
        if status == "PAUSED":
            self._run_security_op(lambda: self.security_ctrl._access_control.resume_agent(aid, reason="Resumed by operator via GUI"))
        else:
            self._run_security_op(lambda: self.security_ctrl._access_control.pause_agent(aid, reason="Paused by operator via GUI"))

    def _on_toggle_block_selected(self) -> None:
        sel = self._selected_agent()
        if not sel:
            return
        aid, status = sel
        if status == "BLOCKED":
            self._run_security_op(lambda: self.security_ctrl._access_control.unblock_agent(aid, reason="Unblocked by operator via GUI"))
        else:
            reply = QMessageBox.warning(
                self,
                "Confirm Block Agent",
                f"Block '{aid}' permanently from executing all MCP tools?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._run_security_op(lambda: self.security_ctrl._access_control.block_agent(aid, reason="Blocked by operator via GUI"))

    def _on_revoke_selected(self) -> None:
        sel = self._selected_agent()
        if not sel:
            return
        aid, _ = sel
        self._run_security_op(lambda: self.security_ctrl._memory_store.revoke_agent_locks(aid))

    def _on_apply_policy_selected(self) -> None:
        sel = self._selected_agent()
        if not sel:
            return
        aid, _ = sel
        pol = self.policy_combo.currentText()
        self._run_security_op(lambda: self.security_ctrl._access_control.set_policy(aid, pol))

    def _on_release_selected_lock(self) -> None:
        row = self.locks_table.currentRow()
        if row < 0:
            return
        key_item = self.locks_table.item(row, 0)
        if not key_item:
            return
        rkey = key_item.text()
        self._run_security_op(lambda: self.security_ctrl._memory_store.force_release_lock(rkey))

    def _on_revoke_all_locks(self) -> None:
        reply = QMessageBox.question(
            self,
            "Revoke All Mutex Locks",
            "Force release all active memory mutex locks held by agents?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._run_security_op(self.security_ctrl._memory_store.revoke_all_locks)

    def _on_emergency_halt(self) -> None:
        reply = QMessageBox.critical(
            self,
            "EMERGENCY STOP",
            "HALT all AI Agent MCP execution immediately and pause all active operations?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._run_security_op(lambda: self.security_ctrl._access_control.emergency_halt("Emergency Stop triggered from Desktop GUI"))

    def _on_emergency_resume(self) -> None:
        self._run_security_op(self.security_ctrl._access_control.emergency_resume)

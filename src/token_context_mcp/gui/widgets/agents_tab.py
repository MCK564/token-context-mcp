"""Agents & Security Tab: multi-agent tracking, permission management, mutex revocation, and audit stream."""
from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from token_context_mcp.gui.widgets.loading_overlay import LoadingOverlay

if TYPE_CHECKING:
    from token_context_mcp.gui.bridge import AgentSecurityController, RepoManager


class AgentsTab(QWidget):
    def __init__(
        self,
        security_ctrl: AgentSecurityController,
        repo_mgr: RepoManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.security_ctrl = security_ctrl
        self.repo_mgr = repo_mgr

        self._agents_data: list[dict[str, Any]] = []
        self._locks_data: list[dict[str, Any]] = []
        self._logs_data: list[dict[str, Any]] = []

        self._init_ui()

        # Connect signals
        self.security_ctrl.agents_updated.connect(self._on_agents_updated)
        self.security_ctrl.locks_updated.connect(self._on_locks_updated)
        self.security_ctrl.audit_logs_updated.connect(self._on_audit_logs_updated)
        self.security_ctrl.emergency_state_changed.connect(self._on_emergency_state_changed)

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 16, 18, 16)
        main_layout.setSpacing(14)

        # 1. Emergency Security Control Bar
        emergency_frame = QFrame()
        emergency_frame.setStyleSheet(
            "background-color: #24273a; border: 1px solid #363a4f; border-radius: 8px; padding: 10px 14px;"
        )
        em_layout = QHBoxLayout(emergency_frame)
        em_layout.setContentsMargins(4, 4, 4, 4)
        em_layout.setSpacing(12)

        self.status_indicator = QLabel("● All Agents Authorized")
        self.status_indicator.setStyleSheet("color: #a6da95; font-size: 13px; font-weight: 700;")
        em_layout.addWidget(self.status_indicator)

        em_layout.addStretch()

        self.revoke_all_btn = QPushButton("🔓 Revoke All Locks")
        self.revoke_all_btn.setStyleSheet("padding: 5px 12px; font-size: 12px;")
        self.revoke_all_btn.clicked.connect(self._on_revoke_all_locks)
        em_layout.addWidget(self.revoke_all_btn)

        self.resume_sys_btn = QPushButton("▶️ Resume Normal")
        self.resume_sys_btn.setStyleSheet("padding: 5px 12px; font-size: 12px;")
        self.resume_sys_btn.clicked.connect(self._on_resume_system)
        em_layout.addWidget(self.resume_sys_btn)

        self.panic_btn = QPushButton("🚨 EMERGENCY STOP")
        self.panic_btn.setStyleSheet(
            "background-color: #ed8796; color: #181926; font-weight: 700; padding: 6px 14px; border-radius: 6px;"
        )
        self.panic_btn.clicked.connect(self._on_panic_emergency_stop)
        em_layout.addWidget(self.panic_btn)

        main_layout.addWidget(emergency_frame)

        # 2. Active Agents Section
        agents_header = QHBoxLayout()
        lbl_agents = QLabel("Active Agents & Access Policies")
        lbl_agents.setStyleSheet("font-size: 14px; font-weight: 700; color: #8bd5ca;")
        agents_header.addWidget(lbl_agents)
        agents_header.addStretch()
        main_layout.addLayout(agents_header)

        self.agents_table = QTableWidget(0, 6)
        self.agents_table.setHorizontalHeaderLabels([
            "Agent ID", "Role / Client", "Status", "Policy Profile", "Tool Calls", "Actions"
        ])
        self.agents_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.agents_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.agents_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.agents_table.verticalHeader().setVisible(False)
        self.agents_table.setStyleSheet("background-color: #181926; border: 1px solid #363a4f; border-radius: 6px;")
        self.agents_table.setMaximumHeight(180)
        main_layout.addWidget(self.agents_table)

        # 3. Active Mutex Locks Section
        locks_header = QHBoxLayout()
        lbl_locks = QLabel("Active Mutex Resource Locks")
        lbl_locks.setStyleSheet("font-size: 14px; font-weight: 700; color: #eed49f;")
        locks_header.addWidget(lbl_locks)
        locks_header.addStretch()
        main_layout.addLayout(locks_header)

        self.locks_table = QTableWidget(0, 5)
        self.locks_table.setHorizontalHeaderLabels([
            "Resource Key", "Held By Agent", "Acquired At", "Remaining", "Action"
        ])
        self.locks_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.locks_table.verticalHeader().setVisible(False)
        self.locks_table.setStyleSheet("background-color: #181926; border: 1px solid #363a4f; border-radius: 6px;")
        self.locks_table.setMaximumHeight(140)
        main_layout.addWidget(self.locks_table)

        # 4. Live Security Audit Stream
        audit_header = QHBoxLayout()
        lbl_audit = QLabel("Security Audit Log Stream (WAL Forensics)")
        lbl_audit.setStyleSheet("font-size: 14px; font-weight: 700; color: #c6a0f6;")
        audit_header.addWidget(lbl_audit)
        audit_header.addStretch()

        audit_header.addWidget(QLabel("Filter Status:"))
        self.status_filter_combo = QComboBox()
        self.status_filter_combo.addItems(["ALL", "SUCCESS", "DENIED", "ERROR"])
        self.status_filter_combo.currentTextChanged.connect(self._render_audit_logs)
        audit_header.addWidget(self.status_filter_combo)

        main_layout.addLayout(audit_header)

        self.audit_table = QTableWidget(0, 6)
        self.audit_table.setHorizontalHeaderLabels([
            "Time", "Agent ID", "Tool Called", "Status", "Duration (ms)", "Details / Reason"
        ])
        self.audit_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.audit_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.audit_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.audit_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.audit_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.audit_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.audit_table.verticalHeader().setVisible(False)
        self.audit_table.setStyleSheet("background-color: #181926; border: 1px solid #363a4f; border-radius: 6px;")
        main_layout.addWidget(self.audit_table, 1)

        # Loading overlay for smooth updates
        self.overlay = LoadingOverlay(self)

    def refresh(self, force: bool = False) -> None:
        self.overlay.show_loading("Updating Security & Agent Telemetry...")
        QTimer.singleShot(0, self._do_refresh)

    def _do_refresh(self) -> None:
        try:
            self.security_ctrl.refresh_data()
        finally:
            self.overlay.hide_loading()

    def _on_emergency_state_changed(self, is_halted: bool, reason: str) -> None:
        if is_halted:
            self.status_indicator.setText(f"🚨 EMERGENCY STOP ACTIVE: {reason}")
            self.status_indicator.setStyleSheet("color: #ed8796; font-size: 13px; font-weight: 700;")
            self.panic_btn.setEnabled(False)
            self.resume_sys_btn.setEnabled(True)
        else:
            self.status_indicator.setText("● All Agents Authorized")
            self.status_indicator.setStyleSheet("color: #a6da95; font-size: 13px; font-weight: 700;")
            self.panic_btn.setEnabled(True)
            self.resume_sys_btn.setEnabled(False)

    def _on_agents_updated(self, agents: list[dict[str, Any]]) -> None:
        self._agents_data = agents
        self._render_agents()

    def _on_locks_updated(self, locks: list[dict[str, Any]]) -> None:
        self._locks_data = locks
        self._render_locks()

    def _on_audit_logs_updated(self, logs: list[dict[str, Any]]) -> None:
        self._logs_data = logs
        self._render_audit_logs()

    def _render_agents(self) -> None:
        self.agents_table.setRowCount(0)
        for row_idx, agent in enumerate(self._agents_data):
            self.agents_table.insertRow(row_idx)
            agent_id = agent["agent_id"]
            role = agent.get("role", "agent")
            state = agent.get("state", "ACTIVE")
            policy = agent.get("policy", "FULL_ACCESS")
            call_count = str(agent.get("call_count", 0))

            item_id = QTableWidgetItem(agent_id)
            item_id.setForeground(Qt.GlobalColor.white)
            self.agents_table.setItem(row_idx, 0, item_id)

            item_role = QTableWidgetItem(role)
            self.agents_table.setItem(row_idx, 1, item_role)

            item_state = QTableWidgetItem(state)
            if state == "ACTIVE":
                item_state.setForeground(Qt.GlobalColor.green)
            elif state == "PAUSED":
                item_state.setForeground(Qt.GlobalColor.yellow)
            else:
                item_state.setForeground(Qt.GlobalColor.red)
            self.agents_table.setItem(row_idx, 2, item_state)

            # Policy combo
            policy_combo = QComboBox()
            policy_combo.addItems(["FULL_ACCESS", "READ_ONLY"])
            policy_combo.setCurrentText(policy)
            policy_combo.currentTextChanged.connect(
                lambda p, ag=agent_id: self.security_ctrl.set_agent_policy(ag, p)
            )
            self.agents_table.setCellWidget(row_idx, 3, policy_combo)

            item_calls = QTableWidgetItem(call_count)
            self.agents_table.setItem(row_idx, 4, item_calls)

            # Action buttons widget
            action_widget = QWidget()
            act_layout = QHBoxLayout(action_widget)
            act_layout.setContentsMargins(2, 2, 2, 2)
            act_layout.setSpacing(6)

            if state == "PAUSED":
                btn_pause = QPushButton("▶️ Resume")
                btn_pause.clicked.connect(lambda _, ag=agent_id: self.security_ctrl.resume_agent(ag))
            else:
                btn_pause = QPushButton("⏸️ Pause")
                btn_pause.clicked.connect(lambda _, ag=agent_id: self.security_ctrl.pause_agent(ag))
            act_layout.addWidget(btn_pause)

            btn_revoke = QPushButton("🔓 Revoke Locks")
            btn_revoke.clicked.connect(lambda _, ag=agent_id: self.security_ctrl.revoke_agent_locks(ag))
            act_layout.addWidget(btn_revoke)

            if state == "BLOCKED":
                btn_block = QPushButton("Unblock")
                btn_block.clicked.connect(lambda _, ag=agent_id: self.security_ctrl.unblock_agent(ag))
            else:
                btn_block = QPushButton("⛔ Block")
                btn_block.clicked.connect(lambda _, ag=agent_id: self.security_ctrl.block_agent(ag))
            act_layout.addWidget(btn_block)

            self.agents_table.setCellWidget(row_idx, 5, action_widget)

    def _render_locks(self) -> None:
        self.locks_table.setRowCount(0)
        for row_idx, lock in enumerate(self._locks_data):
            self.locks_table.insertRow(row_idx)
            res_key = lock["resource_key"]
            ag_id = lock["agent_id"]
            acq_time = datetime.datetime.fromtimestamp(lock["acquired_at"]).strftime("%H:%M:%S")
            remaining = f"{lock.get('remaining_sec', 0)}s"

            self.locks_table.setItem(row_idx, 0, QTableWidgetItem(res_key))
            self.locks_table.setItem(row_idx, 1, QTableWidgetItem(ag_id))
            self.locks_table.setItem(row_idx, 2, QTableWidgetItem(acq_time))
            self.locks_table.setItem(row_idx, 3, QTableWidgetItem(remaining))

            btn_unlock = QPushButton("Force Unlock")
            btn_unlock.setStyleSheet("padding: 2px 8px; font-size: 11px;")
            btn_unlock.clicked.connect(lambda _, ag=ag_id: self.security_ctrl.revoke_agent_locks(ag))
            self.locks_table.setCellWidget(row_idx, 4, btn_unlock)

    def _render_audit_logs(self) -> None:
        filt = self.status_filter_combo.currentText()
        filtered = self._logs_data
        if filt != "ALL":
            filtered = [l for l in filtered if l.get("status") == filt]

        self.audit_table.setRowCount(0)
        for row_idx, log in enumerate(filtered):
            self.audit_table.insertRow(row_idx)
            t_str = datetime.datetime.fromtimestamp(log["timestamp"]).strftime("%H:%M:%S")
            ag_id = log.get("agent_id", "anonymous")
            tool = log.get("tool_name", "")
            status = log.get("status", "")
            duration = f"{log.get('duration_ms', 0):.2f}"
            details = str(log.get("details", ""))

            self.audit_table.setItem(row_idx, 0, QTableWidgetItem(t_str))
            self.audit_table.setItem(row_idx, 1, QTableWidgetItem(ag_id))
            self.audit_table.setItem(row_idx, 2, QTableWidgetItem(tool))

            item_status = QTableWidgetItem(status)
            if status == "SUCCESS":
                item_status.setForeground(Qt.GlobalColor.green)
            elif status == "DENIED":
                item_status.setForeground(Qt.GlobalColor.red)
            else:
                item_status.setForeground(Qt.GlobalColor.yellow)
            self.audit_table.setItem(row_idx, 3, item_status)

            self.audit_table.setItem(row_idx, 4, QTableWidgetItem(duration))
            self.audit_table.setItem(row_idx, 5, QTableWidgetItem(details))

    def _on_panic_emergency_stop(self) -> None:
        reply = QMessageBox.warning(
            self,
            "Confirm Emergency Stop",
            "Are you sure you want to trigger EMERGENCY STOP?\nThis will immediately halt all tool calls across ALL agents!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.security_ctrl.emergency_halt("Triggered by user via GUI Panic Button")

    def _on_resume_system(self) -> None:
        self.security_ctrl.emergency_resume()

    def _on_revoke_all_locks(self) -> None:
        count = self.security_ctrl.revoke_all_locks()
        QMessageBox.information(self, "Locks Revoked", f"Successfully revoked {count} resource lock(s).")

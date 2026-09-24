from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from token_context_mcp.gui.bridge import RepoManager


class SettingsTab(QWidget):
    def __init__(self, repo_mgr: RepoManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repo_mgr = repo_mgr

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        card = QFrame()
        card.setProperty("class", "Card")
        c_layout = QVBoxLayout(card)
        c_layout.setSpacing(14)

        title = QLabel("Server Limits & Feature Flags (repos.toml)")
        title.setProperty("class", "CardHeader")
        c_layout.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(12)

        # 1. max_result_tokens
        grid.addWidget(QLabel("Max Result Tokens (Main Cost Knob):"), 0, 0)
        self.spin_tokens = QSpinBox()
        self.spin_tokens.setRange(32, 8192)
        self.spin_tokens.setSingleStep(256)
        grid.addWidget(self.spin_tokens, 0, 1)

        # 2. max_request_bytes
        grid.addWidget(QLabel("Max Request Bytes:"), 1, 0)
        self.spin_request_bytes = QSpinBox()
        self.spin_request_bytes.setRange(1024, 1048576)
        self.spin_request_bytes.setSingleStep(4096)
        grid.addWidget(self.spin_request_bytes, 1, 1)

        # 3. max_graph_nodes
        grid.addWidget(QLabel("Max Graph Nodes:"), 2, 0)
        self.spin_nodes = QSpinBox()
        self.spin_nodes.setRange(1, 500)
        grid.addWidget(self.spin_nodes, 2, 1)

        # 4. max_symbol_results
        grid.addWidget(QLabel("Max Symbol Results:"), 3, 0)
        self.spin_symbols = QSpinBox()
        self.spin_symbols.setRange(1, 100)
        grid.addWidget(self.spin_symbols, 3, 1)

        # 5. output_mode
        grid.addWidget(QLabel("Output Mode:"), 4, 0)
        self.combo_output = QComboBox()
        self.combo_output.addItems(["structured", "text", "legacy_dual"])
        grid.addWidget(self.combo_output, 4, 1)

        # 6. default_view
        grid.addWidget(QLabel("Default Projection View:"), 5, 0)
        self.combo_view = QComboBox()
        self.combo_view.addItems(["minimal", "normal", "full"])
        grid.addWidget(self.combo_view, 5, 1)

        # 7. enable_extensions
        grid.addWidget(QLabel("Extended 19 Tools Suite:"), 6, 0)
        self.cb_extensions = QCheckBox("Enable Discovery, Episodic Memory & Nested Sampling (Google GenAI)")
        self.cb_extensions.setToolTip("Enables all 19 tools across discovery, episodic memory, and local 7B sampling.")
        grid.addWidget(self.cb_extensions, 6, 1)

        c_layout.addLayout(grid)

        # Note
        note = QLabel("ℹ️ Notice: Settings are saved directly to repos.toml. Restart the MCP server process for limits to take effect.")
        note.setStyleSheet("color: #a5adcb; font-size: 12px; margin-top: 8px;")
        c_layout.addWidget(note)

        # Action button
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.save_btn = QPushButton("💾 Save Server Settings")
        self.save_btn.setProperty("class", "PrimaryButton")
        self.save_btn.clicked.connect(self._save_settings)
        btn_row.addWidget(self.save_btn)

        c_layout.addLayout(btn_row)
        layout.addWidget(card)

        layout.addStretch()
        self.load_settings()

    def load_settings(self) -> None:
        cfg = self.repo_mgr.get_server_config()
        self.spin_tokens.setValue(cfg.get("max_result_tokens", 4096))
        self.spin_request_bytes.setValue(cfg.get("max_request_bytes", 65536))
        self.spin_nodes.setValue(cfg.get("max_graph_nodes", 200))
        self.spin_symbols.setValue(cfg.get("max_symbol_results", 30))

        out_mode = cfg.get("output_mode", "structured")
        idx = self.combo_output.findText(out_mode)
        if idx >= 0:
            self.combo_output.setCurrentIndex(idx)

        view = cfg.get("default_view", "normal")
        v_idx = self.combo_view.findText(view)
        if v_idx >= 0:
            self.combo_view.setCurrentIndex(v_idx)

        self.cb_extensions.setChecked(bool(cfg.get("enable_extensions", False)))

    def _save_settings(self) -> None:
        new_settings = {
            "max_result_tokens": self.spin_tokens.value(),
            "max_request_bytes": self.spin_request_bytes.value(),
            "max_graph_nodes": self.spin_nodes.value(),
            "max_symbol_results": self.spin_symbols.value(),
            "output_mode": self.combo_output.currentText(),
            "default_view": self.combo_view.currentText(),
            "enable_extensions": self.cb_extensions.isChecked(),
        }
        try:
            self.repo_mgr.update_server_config(new_settings)
            QMessageBox.information(self, "Settings Saved", "Server configuration updated successfully in repos.toml!")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed saving configuration: {e}")

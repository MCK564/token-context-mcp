from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from token_context_mcp.gui.bridge import RepoManager
from token_context_mcp.gui.icons import make_icon
from token_context_mcp.gui.theme import COLOR_CRUST
from token_context_mcp.gui.workers import is_ui_thread, run_async
from token_context_mcp.models import LedgerConfig


class SettingsTab(QWidget):
    def __init__(self, repo_mgr: RepoManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repo_mgr = repo_mgr

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

        # --- Card 1: Server Limits & Tool Suites ---
        srv_card = QFrame()
        srv_card.setProperty("class", "Card")
        s_layout = QVBoxLayout(srv_card)
        s_layout.setContentsMargins(16, 14, 16, 14)
        s_layout.setSpacing(12)

        s_title = QLabel("Server Limits & Tool Suites (repos.toml)")
        s_title.setProperty("class", "SectionTitle")
        s_layout.addWidget(s_title)

        form = QFormLayout()
        form.setSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)

        self.spin_tokens = QSpinBox()
        self.spin_tokens.setRange(32, 65536)
        self.spin_tokens.setSingleStep(512)
        self.spin_tokens.setMinimumWidth(160)
        self.spin_tokens.setSuffix(" tokens")
        form.addRow("Max Result Tokens:", self.spin_tokens)

        self.spin_req_bytes = QSpinBox()
        self.spin_req_bytes.setRange(1024, 16_777_216)
        self.spin_req_bytes.setSingleStep(16384)
        self.spin_req_bytes.setMinimumWidth(160)
        self.spin_req_bytes.setSuffix(" bytes")
        form.addRow("Max Request Bytes:", self.spin_req_bytes)

        self.spin_nodes = QSpinBox()
        self.spin_nodes.setRange(10, 5000)
        self.spin_nodes.setMinimumWidth(160)
        form.addRow("Max Graph Nodes:", self.spin_nodes)

        self.spin_symbols = QSpinBox()
        self.spin_symbols.setRange(5, 500)
        self.spin_symbols.setMinimumWidth(160)
        form.addRow("Max Symbol Results:", self.spin_symbols)

        self.combo_output = QComboBox()
        self.combo_output.addItems(["auto", "structured", "text", "legacy_dual"])
        self.combo_output.setMinimumWidth(200)
        form.addRow("Output Mode:", self.combo_output)

        tip = QLabel("Tip: 'auto' detects client capability; 'text' avoids truncation in Gemini / Antigravity.")
        tip.setProperty("class", "MutedHint")
        tip.setWordWrap(True)
        form.addRow("", tip)

        self.combo_view = QComboBox()
        self.combo_view.addItems(["minimal", "normal", "full"])
        self.combo_view.setMinimumWidth(200)
        form.addRow("Default Projection View:", self.combo_view)

        self.chk_extensions = QCheckBox(
            "Enable Discovery, Episodic Memory, MCP Sampling && Trajectory Record (21 tools)"
        )
        form.addRow("Extended Tools Suite:", self.chk_extensions)

        self.chk_admin_tools = QCheckBox(
            "Enable Governance Admin Tools (agent_control, audit_logs -> 23 tools total)"
        )
        form.addRow("Admin Tools:", self.chk_admin_tools)

        s_layout.addLayout(form)
        layout.addWidget(srv_card)

        # --- Card 2: Verified Evidence Ledger ("Lá Phổi") ---
        led_card = QFrame()
        led_card.setProperty("class", "Card")
        l_layout = QVBoxLayout(led_card)
        l_layout.setContentsMargins(16, 14, 16, 14)
        l_layout.setSpacing(12)

        l_title = QLabel("Verified Evidence Ledger ('Lá Phổi' — [ledger])")
        l_title.setProperty("class", "SectionTitle")
        l_layout.addWidget(l_title)

        l_form = QFormLayout()
        l_form.setSpacing(10)
        l_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)

        self.chk_ledger_enabled = QCheckBox(
            "Serve disk-verified prior_evidence hints on read (default ON)"
        )
        l_form.addRow("Ledger Enabled:", self.chk_ledger_enabled)

        self.chk_ledger_overlay = QCheckBox(
            "Apply confirmed ledger hints as gentle ranking overlay in search_source"
        )
        l_form.addRow("Ranking Overlay:", self.chk_ledger_overlay)

        self.spin_ledger_max_cards = QSpinBox()
        self.spin_ledger_max_cards.setRange(10, 10000)
        self.spin_ledger_max_cards.setMinimumWidth(160)
        l_form.addRow("Max Cards Per Repo:", self.spin_ledger_max_cards)

        self.spin_ledger_ttl = QSpinBox()
        self.spin_ledger_ttl.setRange(1, 365)
        self.spin_ledger_ttl.setSuffix(" days")
        self.spin_ledger_ttl.setMinimumWidth(160)
        l_form.addRow("Card TTL:", self.spin_ledger_ttl)

        self.spin_ledger_hint_tokens = QSpinBox()
        self.spin_ledger_hint_tokens.setRange(32, 1024)
        self.spin_ledger_hint_tokens.setSuffix(" tokens")
        self.spin_ledger_hint_tokens.setMinimumWidth(160)
        l_form.addRow("Max Hint Tokens:", self.spin_ledger_hint_tokens)

        self.dspin_ans_jaccard = QDoubleSpinBox()
        self.dspin_ans_jaccard.setRange(0.1, 1.0)
        self.dspin_ans_jaccard.setSingleStep(0.05)
        self.dspin_ans_jaccard.setMinimumWidth(160)
        l_form.addRow("Answer Jaccard Min:", self.dspin_ans_jaccard)

        self.spin_ans_overlap = QSpinBox()
        self.spin_ans_overlap.setRange(1, 10)
        self.spin_ans_overlap.setMinimumWidth(160)
        l_form.addRow("Answer Min Overlap:", self.spin_ans_overlap)

        self.dspin_decoy_jaccard = QDoubleSpinBox()
        self.dspin_decoy_jaccard.setRange(0.1, 1.0)
        self.dspin_decoy_jaccard.setSingleStep(0.05)
        self.dspin_decoy_jaccard.setMinimumWidth(160)
        l_form.addRow("Decoy Jaccard Min:", self.dspin_decoy_jaccard)

        l_layout.addLayout(l_form)
        layout.addWidget(led_card)

        # Notice + Actions row
        notice = QLabel(
            "Settings write atomically to repos.toml. Restart active MCP server processes for changes to take effect."
        )
        notice.setProperty("class", "MutedHint")
        notice.setWordWrap(True)
        layout.addWidget(notice)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.reset_ledger_btn = QPushButton("Reset Ledger Defaults")
        self.reset_ledger_btn.clicked.connect(self._reset_ledger_defaults)
        btn_row.addWidget(self.reset_ledger_btn)
        btn_row.addStretch()

        self.save_btn = QPushButton("Save Server Settings")
        self.save_btn.setIcon(make_icon("check", COLOR_CRUST))
        self.save_btn.setProperty("class", "PrimaryButton")
        self.save_btn.clicked.connect(self._save)
        btn_row.addWidget(self.save_btn)
        layout.addLayout(btn_row)
        layout.addStretch(1)

    def refresh(self) -> None:
        run_async(self.fetch, on_ok=self.render)

    def fetch(self) -> dict[str, Any]:
        assert not is_ui_thread(), "SettingsTab.fetch must run off the UI thread"
        return self.repo_mgr.get_server_config()

    def render(self, cfg: dict[str, Any]) -> None:
        assert is_ui_thread(), "SettingsTab.render must run on the UI thread"
        self.spin_tokens.setValue(int(cfg.get("max_result_tokens", 8192)))
        self.spin_req_bytes.setValue(int(cfg.get("max_request_bytes", 1048576)))
        self.spin_nodes.setValue(int(cfg.get("max_graph_nodes", 100)))
        self.spin_symbols.setValue(int(cfg.get("max_symbol_results", 20)))
        self.combo_output.setCurrentText(str(cfg.get("output_mode", "structured")))
        self.combo_view.setCurrentText(str(cfg.get("default_view", "normal")))
        self.chk_extensions.setChecked(bool(cfg.get("enable_extensions", False)))
        self.chk_admin_tools.setChecked(bool(cfg.get("enable_admin_tools", False)))

        self.chk_ledger_enabled.setChecked(bool(cfg.get("ledger_enabled", LedgerConfig.enabled)))
        self.chk_ledger_overlay.setChecked(bool(cfg.get("ledger_overlay_enabled", LedgerConfig.overlay_enabled)))
        self.spin_ledger_max_cards.setValue(int(cfg.get("ledger_max_cards_per_repo", LedgerConfig.max_cards_per_repo)))
        self.spin_ledger_ttl.setValue(int(cfg.get("ledger_ttl_days", LedgerConfig.ttl_days)))
        self.spin_ledger_hint_tokens.setValue(int(cfg.get("ledger_max_hint_tokens", LedgerConfig.max_hint_tokens)))
        self.dspin_ans_jaccard.setValue(float(cfg.get("ledger_answer_jaccard_min", LedgerConfig.answer_jaccard_min)))
        self.spin_ans_overlap.setValue(int(cfg.get("ledger_answer_min_overlap", LedgerConfig.answer_min_overlap)))
        self.dspin_decoy_jaccard.setValue(float(cfg.get("ledger_decoy_jaccard_min", LedgerConfig.decoy_jaccard_min)))

    def _reset_ledger_defaults(self) -> None:
        d = LedgerConfig()
        self.chk_ledger_enabled.setChecked(d.enabled)
        self.chk_ledger_overlay.setChecked(d.overlay_enabled)
        self.spin_ledger_max_cards.setValue(d.max_cards_per_repo)
        self.spin_ledger_ttl.setValue(d.ttl_days)
        self.spin_ledger_hint_tokens.setValue(d.max_hint_tokens)
        self.dspin_ans_jaccard.setValue(d.answer_jaccard_min)
        self.spin_ans_overlap.setValue(d.answer_min_overlap)
        self.dspin_decoy_jaccard.setValue(d.decoy_jaccard_min)

    def _save(self) -> None:
        payload = {
            "max_result_tokens": self.spin_tokens.value(),
            "max_request_bytes": self.spin_req_bytes.value(),
            "max_graph_nodes": self.spin_nodes.value(),
            "max_symbol_results": self.spin_symbols.value(),
            "output_mode": self.combo_output.currentText(),
            "default_view": self.combo_view.currentText(),
            "enable_extensions": self.chk_extensions.isChecked(),
            "enable_admin_tools": self.chk_admin_tools.isChecked(),
            "ledger_enabled": self.chk_ledger_enabled.isChecked(),
            "ledger_overlay_enabled": self.chk_ledger_overlay.isChecked(),
            "ledger_max_cards_per_repo": self.spin_ledger_max_cards.value(),
            "ledger_ttl_days": self.spin_ledger_ttl.value(),
            "ledger_max_hint_tokens": self.spin_ledger_hint_tokens.value(),
            "ledger_answer_jaccard_min": round(self.dspin_ans_jaccard.value(), 3),
            "ledger_answer_min_overlap": self.spin_ans_overlap.value(),
            "ledger_decoy_jaccard_min": round(self.dspin_decoy_jaccard.value(), 3),
        }
        try:
            self.repo_mgr.update_server_config(payload)
            QMessageBox.information(self, "Saved", "Server & Evidence Ledger configuration saved to repos.toml.")
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))

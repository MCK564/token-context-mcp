from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from token_context_mcp.gui.bridge import IndexWorker

if TYPE_CHECKING:
    from token_context_mcp.gui.bridge import RepoManager


class AddRepoDialog(QDialog):
    def __init__(self, repo_mgr: RepoManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repo_mgr = repo_mgr
        self.setWindowTitle("Register New Repository")
        self.resize(500, 240)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("Register Repository to Allowlist")
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #89b4fa;")
        layout.addWidget(title)

        # Repo ID
        id_layout = QVBoxLayout()
        id_layout.setSpacing(4)
        id_layout.addWidget(QLabel("Repository Identifier (short name, e.g. my-service):"))
        self.id_input = QLineEdit()
        self.id_input.setPlaceholderText("lowercase letters, numbers, dash or underscore (e.g. backend_api)")
        id_layout.addWidget(self.id_input)
        layout.addLayout(id_layout)

        # Root Path
        path_layout = QVBoxLayout()
        path_layout.setSpacing(4)
        path_layout.addWidget(QLabel("Root Directory Path:"))
        path_row = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("D:/Projects/my-service")
        path_row.addWidget(self.path_input, 1)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_folder)
        path_row.addWidget(browse_btn)
        path_layout.addLayout(path_row)
        layout.addLayout(path_layout)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        self.save_btn = QPushButton("Register & Save")
        self.save_btn.setProperty("class", "PrimaryButton")
        self.save_btn.clicked.connect(self._validate_and_save)
        btn_row.addWidget(self.save_btn)

        layout.addLayout(btn_row)

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Repository Directory")
        if folder:
            self.path_input.setText(folder)
            if not self.id_input.text().strip():
                # auto-suggest id from folder name
                suggested = Path(folder).name.lower().replace(" ", "-")
                import re
                suggested = re.sub(r"[^a-z0-9_-]", "", suggested)
                if suggested and suggested[0].isalpha():
                    self.id_input.setText(suggested)

    def _validate_and_save(self) -> None:
        repo_id = self.id_input.text().strip()
        root = self.path_input.text().strip()

        if not repo_id or not root:
            QMessageBox.warning(self, "Input Error", "Both Repository ID and Root Path are required.")
            return

        try:
            self.repo_mgr.add_repository(repo_id, root)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Registration Error", str(e))


class RepositoriesTab(QWidget):
    indexing_started = Signal(str)
    indexing_finished = Signal(str)
    indexing_progress = Signal(str, int, int)

    def __init__(self, repo_mgr: RepoManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repo_mgr = repo_mgr
        self._current_worker: IndexWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Top Action Bar
        top_bar = QHBoxLayout()
        top_title = QLabel("Registered Repositories")
        top_title.setProperty("class", "CardHeader")
        top_title.setStyleSheet("font-size: 16px;")
        top_bar.addWidget(top_title)

        top_bar.addStretch()

        self.add_btn = QPushButton("➕ Add Repository")
        self.add_btn.setProperty("class", "PrimaryButton")
        self.add_btn.clicked.connect(self._open_add_dialog)
        top_bar.addWidget(self.add_btn)

        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.clicked.connect(self.load_repositories)
        top_bar.addWidget(self.refresh_btn)

        layout.addLayout(top_bar)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["Repo ID", "Root Path", "Freshness", "Symbols", "Ambiguous Rate", "DB Size", "Actions"]
        )
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)

        # Indexing Progress Card
        self.progress_card = QFrame()
        self.progress_card.setProperty("class", "Card")
        p_layout = QVBoxLayout(self.progress_card)
        p_layout.setContentsMargins(12, 10, 12, 10)
        p_layout.setSpacing(6)

        p_header = QHBoxLayout()
        self.progress_label = QLabel("Indexing Idle")
        self.progress_label.setStyleSheet("font-size: 12px; font-weight: 600; color: #89b4fa;")
        p_header.addWidget(self.progress_label)
        p_header.addStretch()
        p_layout.addLayout(p_header)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        p_layout.addWidget(self.progress_bar)

        layout.addWidget(self.progress_card)

        self.load_repositories()

    def load_repositories(self) -> None:
        repos = self.repo_mgr.list_repositories()
        self.table.setRowCount(len(repos))

        for row, r in enumerate(repos):
            repo_id = r["repo_id"]

            # 0: Repo ID
            id_item = QTableWidgetItem(repo_id)
            id_item.setFont(self.font())
            self.table.setItem(row, 0, id_item)

            # 1: Root Path
            self.table.setItem(row, 1, QTableWidgetItem(r["root"]))

            # 2: Freshness Badge
            freshness = r["freshness"]
            badge = QLabel(freshness.upper())
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if freshness == "fresh":
                badge.setProperty("class", "BadgeFresh")
            elif freshness == "stale":
                badge.setProperty("class", "BadgeStale")
            else:
                badge.setProperty("class", "BadgeNotIndexed")
            self.table.setCellWidget(row, 2, badge)

            # 3: Symbols Count
            sym_item = QTableWidgetItem(f"{r['symbols_count']:,}")
            sym_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 3, sym_item)

            # 4: Ambiguous Rate
            ambig_item = QTableWidgetItem(f"{r['ambiguous_rate']:.1f}%")
            ambig_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 4, ambig_item)

            # 5: DB Size
            size_item = QTableWidgetItem(f"{r['db_size_mb']:.1f} MB")
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 5, size_item)

            # 6: Action Buttons
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(4, 2, 4, 2)
            action_layout.setSpacing(6)

            reindex_btn = QPushButton("⚡ Re-index")
            reindex_btn.setStyleSheet("padding: 3px 8px; font-size: 11px;")
            reindex_btn.clicked.connect(lambda _, rid=repo_id: self.start_indexing(rid))
            action_layout.addWidget(reindex_btn)

            del_btn = QPushButton("🗑️")
            del_btn.setProperty("class", "DangerButton")
            del_btn.setStyleSheet("padding: 3px 6px; font-size: 11px;")
            del_btn.setToolTip("Delete repository from registry")
            del_btn.clicked.connect(lambda _, rid=repo_id: self._confirm_delete(rid))
            action_layout.addWidget(del_btn)

            self.table.setCellWidget(row, 6, action_widget)

    def _open_add_dialog(self) -> None:
        dlg = AddRepoDialog(self.repo_mgr, self)
        if dlg.exec():
            self.load_repositories()

    def _confirm_delete(self, repo_id: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Confirm Unregister")
        box.setText(f"Are you sure you want to remove '{repo_id}' from the repository registry?")

        purge_cb = QCheckBox("Also delete cached SQLite index database file", box)
        purge_cb.setChecked(True)
        box.setCheckBox(purge_cb)

        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)

        if box.exec() == QMessageBox.StandardButton.Yes:
            try:
                self.repo_mgr.delete_repository(repo_id, purge_db=purge_cb.isChecked())
                self.load_repositories()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed deleting repository: {e}")

    def start_indexing(self, repo_id: str) -> None:
        if self._current_worker and self._current_worker.isRunning():
            QMessageBox.warning(self, "Indexing in Progress", "Another indexing task is already running. Please wait.")
            return

        self.progress_label.setText(f"Starting index for '{repo_id}'...")
        self.progress_bar.setValue(0)
        self.indexing_started.emit(repo_id)

        self._current_worker = IndexWorker(repo_id, self.repo_mgr.config_path, self)
        self._current_worker.progress_changed.connect(self._on_progress)
        self._current_worker.index_finished.connect(self._on_index_finished)
        self._current_worker.index_failed.connect(self._on_index_failed)
        self._current_worker.start()

    def _on_progress(self, msg: str, current: int, total: int) -> None:
        self.progress_label.setText(msg)
        if total > 0:
            pct = min(100, int((current / max(1, total)) * 100))
            self.progress_bar.setValue(pct)
        self.indexing_progress.emit(msg, current, total)

    def _on_index_finished(self, repo_id: str, manifest: dict) -> None:
        self.progress_label.setText(f"Indexed '{repo_id}' successfully! ({manifest.get('symbols_indexed', 0)} symbols)")
        self.progress_bar.setValue(100)
        self.load_repositories()
        self.indexing_finished.emit(repo_id)

    def _on_index_failed(self, repo_id: str, err: str) -> None:
        self.progress_label.setText(f"Index error on '{repo_id}': {err}")
        self.progress_bar.setValue(0)
        QMessageBox.critical(self, "Indexing Failed", f"Failed building index for '{repo_id}':\n{err}")

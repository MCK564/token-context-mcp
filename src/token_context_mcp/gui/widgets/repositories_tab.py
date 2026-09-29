from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from token_context_mcp.gui.bridge import IndexProcess
from token_context_mcp.gui.models import RepoTableModel
from token_context_mcp.gui.workers import run_async

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
    indexing_log = Signal(str)

    def __init__(self, repo_mgr: RepoManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repo_mgr = repo_mgr
        self._current_job: IndexProcess | None = None
        self.silent_errors = False  # tests: do not open modal boxes

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Toolbar: the actions of the selected row live here (and in the row's context menu), not in row widgets
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

        self.reindex_btn = QPushButton("⚡ Re-index selected")
        self.reindex_btn.setEnabled(False)
        self.reindex_btn.clicked.connect(self._reindex_selected)
        top_bar.addWidget(self.reindex_btn)

        self.reindex_all_btn = QPushButton("⚡ Re-index all")
        self.reindex_all_btn.clicked.connect(self.start_indexing_all)
        top_bar.addWidget(self.reindex_all_btn)

        self.cancel_btn = QPushButton("⏹ Cancel")
        self.cancel_btn.setProperty("class", "DangerButton")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_indexing)
        top_bar.addWidget(self.cancel_btn)

        self.delete_btn = QPushButton("🗑️ Remove selected")
        self.delete_btn.setProperty("class", "DangerButton")
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self._delete_selected)
        top_bar.addWidget(self.delete_btn)

        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        top_bar.addWidget(self.refresh_btn)

        layout.addLayout(top_bar)

        # Table: QTableView + model (no setCellWidget)
        self.model = RepoTableModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.selectionModel().selectionChanged.connect(self._update_buttons)
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

    # -- fetch / render (M8.2) ------------------------------------------------------------------------------------
    def fetch(self) -> list[dict[str, Any]]:
        """Worker-side: rows for the table. Reads manifests and status only."""
        return self.repo_mgr.list_repositories(force_refresh=True)

    def render(self, rows: list[dict[str, Any]]) -> None:
        """UI-side: keeps the selection when the repository is still listed."""
        selected = self.selected_repo_id()
        self.model.set_rows(rows)
        if selected:
            for row in range(self.model.rowCount()):
                if self.model.repo_id_at(row) == selected:
                    self.table.selectRow(row)
                    break
        self._update_buttons()

    def refresh(self) -> None:
        run_async(self.fetch, on_ok=self.render, on_err=self._log_error)

    load_repositories = refresh  # name used by older callers

    def _log_error(self, error: BaseException) -> None:
        self.indexing_log.emit(f"Could not read repositories: {error}")

    # -- selection and actions --------------------------------------------------------------------------------------
    def selected_repo_id(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        return self.model.repo_id_at(rows[0].row()) if rows else None

    def _update_buttons(self, *_: Any) -> None:
        busy = self._current_job is not None and self._current_job.isRunning()
        has_selection = self.selected_repo_id() is not None
        self.reindex_btn.setEnabled(has_selection and not busy)
        self.reindex_all_btn.setEnabled(not busy)
        self.delete_btn.setEnabled(has_selection and not busy)
        self.cancel_btn.setEnabled(busy)

    def _show_context_menu(self, pos: QPoint) -> None:
        index = self.table.indexAt(pos)
        if index.isValid():
            self.table.selectRow(index.row())
        repo_id = self.selected_repo_id()
        if repo_id is None:
            return
        menu = QMenu(self)
        reindex = QAction(f"Re-index '{repo_id}'", menu)
        reindex.triggered.connect(self._reindex_selected)
        remove = QAction(f"Remove '{repo_id}'...", menu)
        remove.triggered.connect(self._delete_selected)
        menu.addAction(reindex)
        menu.addAction(remove)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _reindex_selected(self) -> None:
        repo_id = self.selected_repo_id()
        if repo_id:
            self.start_indexing(repo_id)

    def _delete_selected(self) -> None:
        repo_id = self.selected_repo_id()
        if repo_id:
            self._confirm_delete(repo_id)

    def _open_add_dialog(self) -> None:
        dlg = AddRepoDialog(self.repo_mgr, self)
        if dlg.exec():
            self.refresh()

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
            purge = purge_cb.isChecked()
            run_async(
                self.repo_mgr.delete_repository,
                repo_id,
                purge_db=purge,
                on_ok=lambda _: self.refresh(),
                on_err=lambda e: QMessageBox.critical(self, "Error", f"Failed deleting repository: {e}"),
            )

    # -- indexing (child process) -------------------------------------------------------------------------------------
    def _begin(self, job: IndexProcess, label: str) -> None:
        self.progress_label.setText(f"Starting index for {label}...")
        self.progress_bar.setValue(0)
        self.indexing_started.emit(job.repo_id)
        self._current_job = job
        job.progress_changed.connect(self._on_progress)
        job.log_emitted.connect(self.indexing_log)
        job.index_finished.connect(self._on_index_finished)
        job.index_failed.connect(self._on_index_failed)
        job.start()
        self._update_buttons()

    def start_indexing(self, repo_id: str) -> None:
        if self._current_job is not None and self._current_job.isRunning():
            if not self.silent_errors:
                QMessageBox.warning(self, "Indexing in Progress", "Another indexing task is already running. Please wait.")
            return
        self._begin(IndexProcess(repo_id, self.repo_mgr.config_path, self), f"'{repo_id}'")

    def start_indexing_all(self) -> None:
        if self._current_job is not None and self._current_job.isRunning():
            return
        self._begin(IndexProcess(None, self.repo_mgr.config_path, self, all_repos=True), "all repositories")

    def isIndexing(self) -> bool:
        return self._current_job is not None and self._current_job.isRunning()

    def cancel_indexing(self) -> None:
        if self._current_job is not None:
            self._current_job.cancel()

    def _on_progress(self, msg: str, current: int, total: int) -> None:
        self.progress_label.setText(msg)
        if total > 0:
            self.progress_bar.setValue(min(100, int((current / max(1, total)) * 100)))
        self.indexing_progress.emit(msg, current, total)

    def _on_index_finished(self, repo_id: str, manifest: dict) -> None:
        if repo_id == "*":
            self.progress_label.setText(f"Indexed {manifest.get('indexed', 0)} repositories, {manifest.get('failed', 0)} failed")
        else:
            self.progress_label.setText(f"Indexed '{repo_id}' successfully! ({manifest.get('symbols_indexed', 0)} symbols)")
        self.progress_bar.setValue(100)
        self._current_job = None
        self.refresh()
        self._update_buttons()
        self.indexing_finished.emit(repo_id)

    def _on_index_failed(self, repo_id: str, err: str) -> None:
        cancelled = self._current_job is not None and self._current_job.cancelled
        self._current_job = None
        self.progress_bar.setValue(0)
        self.progress_label.setText("Indexing cancelled" if cancelled else f"Index error on '{repo_id}': {err}")
        self._update_buttons()
        self.indexing_finished.emit(repo_id)
        if not cancelled and not self.silent_errors:
            QMessageBox.critical(self, "Indexing Failed", f"Failed building index for '{repo_id}':\n{err}")

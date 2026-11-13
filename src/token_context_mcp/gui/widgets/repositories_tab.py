from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSortFilterProxyModel, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
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
    QTableView,
    QVBoxLayout,
    QWidget,
)

from token_context_mcp.gui.bridge import IndexProcess, RepoManager
from token_context_mcp.gui.icons import make_icon
from token_context_mcp.gui.models import RepoTableModel
from token_context_mcp.gui.theme import (
    COLOR_ACCENT,
    COLOR_CRUST,
    COLOR_DANGER,
    COLOR_SUCCESS,
    COLOR_TEXT_PRIMARY,
)
from token_context_mcp.gui.workers import is_ui_thread, run_async

_REPO_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


class AddRepoDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Repository")
        self.resize(520, 235)
        self.setMinimumSize(440, 220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("Register Repository to Allowlist")
        title.setProperty("class", "SectionTitle")
        layout.addWidget(title)

        id_lbl = QLabel("Repository Identifier (e.g. my-service):")
        id_lbl.setProperty("class", "MutedHint")
        layout.addWidget(id_lbl)
        self.repo_id_input = QLineEdit()
        self.repo_id_input.setPlaceholderText("letters, numbers, dash or underscore (e.g. backend_api)")
        layout.addWidget(self.repo_id_input)

        dir_lbl = QLabel("Root Directory Path:")
        dir_lbl.setProperty("class", "MutedHint")
        layout.addWidget(dir_lbl)
        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("D:/Projects/my-service")
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse)
        dir_row.addWidget(self.path_input, 1)
        dir_row.addWidget(browse_btn)
        layout.addLayout(dir_row)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Register && Save")
        save_btn.setProperty("class", "PrimaryButton")
        save_btn.clicked.connect(self._accept_validated)
        btns.addWidget(cancel_btn)
        btns.addWidget(save_btn)
        layout.addLayout(btns)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Repository Root Directory")
        if folder:
            self.path_input.setText(folder)
            if not self.repo_id_input.text().strip():
                suggested = re.sub(r"[^a-zA-Z0-9_-]+", "-", Path(folder).name.lower()).strip("-")
                self.repo_id_input.setText(suggested or "repo")

    def _accept_validated(self) -> None:
        rid = self.repo_id_input.text().strip()
        path = self.path_input.text().strip()
        if not rid or not _REPO_ID_RE.match(rid):
            QMessageBox.warning(self, "Invalid Repository ID", "Use letters, digits, '-' or '_' starting with alphanumeric.")
            return
        if not path or not Path(path).is_dir():
            QMessageBox.warning(self, "Invalid Directory", "Please select an existing directory on disk.")
            return
        self.accept()

    def values(self) -> tuple[str, str]:
        return self.repo_id_input.text().strip(), self.path_input.text().strip()


class RepositoriesTab(QWidget):
    indexing_log = Signal(str)
    indexing_started = Signal(str)
    indexing_progress = Signal(str, int, int, str)
    indexing_finished = Signal(str, bool, str)

    def __init__(self, repo_mgr: RepoManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repo_mgr = repo_mgr
        self._proc: IndexProcess | None = None
        self._queue: list[tuple[str, bool]] = []
        self._current_repo: str = ""
        self._current_full: bool = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # Top row: Title + Search filter + Primary Add button
        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        title = QLabel("Repositories")
        title.setProperty("class", "SectionTitle")
        top_row.addWidget(title)

        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter by Repo ID or Path...")
        self.filter_input.setClearButtonEnabled(True)
        self.filter_input.textChanged.connect(self._on_filter_changed)
        top_row.addWidget(self.filter_input, 1)

        self.add_btn = QPushButton("Add Repository")
        self.add_btn.setIcon(make_icon("add", COLOR_CRUST))
        self.add_btn.setProperty("class", "PrimaryButton")
        self.add_btn.clicked.connect(self._add_repo)
        top_row.addWidget(self.add_btn)
        layout.addLayout(top_row)

        # Action bar row (cleanly fits 960x620 without button clipping)
        act_row = QHBoxLayout()
        act_row.setSpacing(8)

        self.reindex_sel_btn = QPushButton("Re-index")
        self.reindex_sel_btn.setIcon(make_icon("play", COLOR_TEXT_PRIMARY))
        self.reindex_sel_btn.clicked.connect(lambda: self._reindex_selected(full=False))

        self.full_rebuild_btn = QPushButton("Full Rebuild")
        self.full_rebuild_btn.setIcon(make_icon("refresh", COLOR_TEXT_PRIMARY))
        self.full_rebuild_btn.clicked.connect(lambda: self._reindex_selected(full=True))

        self.reindex_all_btn = QPushButton("Re-index All")
        self.reindex_all_btn.setIcon(make_icon("tasks", COLOR_TEXT_PRIMARY))
        self.reindex_all_btn.clicked.connect(self._reindex_all)

        self.open_folder_btn = QPushButton("Open Folder")
        self.open_folder_btn.setIcon(make_icon("repos", COLOR_TEXT_PRIMARY))
        self.open_folder_btn.clicked.connect(self._open_selected_folder)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setIcon(make_icon("stop", COLOR_DANGER))
        self.cancel_btn.setProperty("class", "DangerButton")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_indexing)

        self.delete_btn = QPushButton("Remove")
        self.delete_btn.setIcon(make_icon("trash", COLOR_DANGER))
        self.delete_btn.setProperty("class", "DangerButton")
        self.delete_btn.clicked.connect(self._delete_selected)

        for b in (
            self.reindex_sel_btn,
            self.full_rebuild_btn,
            self.reindex_all_btn,
            self.open_folder_btn,
            self.cancel_btn,
            self.delete_btn,
        ):
            act_row.addWidget(b)
        act_row.addStretch()
        layout.addLayout(act_row)

        # Repositories Table
        self.model = RepoTableModel(self)
        self.proxy_model = QSortFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy_model.setFilterKeyColumn(-1)

        self.table = QTableView()
        self.table.setModel(self.proxy_model)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(0, 145)
        layout.addWidget(self.table, 1)

        # Indexing Progress Card (collapsed when idle to maximize table height)
        self.progress_card = QFrame()
        self.progress_card.setProperty("class", "Card")
        p_layout = QVBoxLayout(self.progress_card)
        p_layout.setContentsMargins(14, 10, 14, 10)
        p_layout.setSpacing(6)

        self.progress_status = QLabel("Indexing Idle")
        self.progress_status.setStyleSheet(f"color: {COLOR_ACCENT}; font-weight: 600;")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        p_layout.addWidget(self.progress_status)
        p_layout.addWidget(self.progress_bar)
        self.progress_card.setVisible(False)
        layout.addWidget(self.progress_card)

    def _on_filter_changed(self, text: str) -> None:
        self.proxy_model.setFilterFixedString(text)

    def isIndexing(self) -> bool:
        return self._proc is not None or bool(self._queue)

    def cancel_indexing(self) -> None:
        self._queue.clear()
        if self._proc is not None:
            self.progress_status.setText(f"Cancelling {self._current_repo}...")
            self.indexing_log.emit(f"[CANCEL] Terminating indexing process for {self._current_repo}...")
            self._proc.cancel()

    def refresh(self) -> None:
        run_async(self.fetch, on_ok=self.render)

    def fetch(self) -> list[dict[str, Any]]:
        assert not is_ui_thread(), "RepositoriesTab.fetch must run off the UI thread"
        self.repo_mgr.invalidate_cache()
        return self.repo_mgr.list_repositories()

    def render(self, repos: list[dict[str, Any]]) -> None:
        assert is_ui_thread(), "RepositoriesTab.render must run on the UI thread"
        self.model.set_rows(repos)

    def _selected_repo(self) -> dict[str, Any] | None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        src_idx = self.proxy_model.mapToSource(indexes[0])
        return self.model.row_at(src_idx.row())

    def _open_selected_folder(self) -> None:
        repo = self._selected_repo()
        if not repo:
            QMessageBox.information(self, "Select Repository", "Select a repository first.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(repo["root"])))

    def _add_repo(self) -> None:
        dlg = AddRepoDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            repo_id, path = dlg.values()
            try:
                self.repo_mgr.add_repository(repo_id, path)
                self.indexing_log.emit(f"[REGISTER] Added repo '{repo_id}' at {path}")
                self.refresh()
            except Exception as exc:
                QMessageBox.critical(self, "Registration Failed", str(exc))

    def _delete_selected(self) -> None:
        repo = self._selected_repo()
        if not repo:
            QMessageBox.information(self, "Select Repository", "Please select a repository row to remove.")
            return
        repo_id = repo["repo_id"]
        reply = QMessageBox.question(
            self,
            "Confirm Removal",
            f"Unregister '{repo_id}' and purge its cached SQLite index snapshot?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                self.repo_mgr.delete_repository(repo_id, purge_db=True)
                self.indexing_log.emit(f"[DELETE] Unregistered '{repo_id}' and purged SQLite DB.")
                self.refresh()
            except Exception as exc:
                QMessageBox.critical(self, "Delete Error", str(exc))

    def _reindex_selected(self, *, full: bool = False) -> None:
        repo = self._selected_repo()
        if not repo:
            QMessageBox.information(self, "Select Repository", "Please select a repository row first.")
            return
        self._start_queue([(repo["repo_id"], full)])

    def _reindex_all(self) -> None:
        ids = [(r["repo_id"], False) for r in self.model.rows()]
        if ids:
            self._start_queue(ids)

    def _start_queue(self, items: list[tuple[str, bool]]) -> None:
        if self.isIndexing():
            QMessageBox.warning(self, "Indexing Busy", "An indexing task is already running.")
            return
        self._queue = list(items)
        self._set_busy_ui(True)
        self._start_next_in_queue()

    def _set_busy_ui(self, busy: bool) -> None:
        self.progress_card.setVisible(busy)
        self.reindex_sel_btn.setEnabled(not busy)
        self.full_rebuild_btn.setEnabled(not busy)
        self.reindex_all_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        self.add_btn.setEnabled(not busy)
        self.delete_btn.setEnabled(not busy)

    def _start_next_in_queue(self) -> None:
        if not self._queue:
            self._set_busy_ui(False)
            self.progress_status.setText("Indexing Completed")
            self.progress_status.setStyleSheet(f"color: {COLOR_SUCCESS}; font-weight: 600;")
            self.refresh()
            return

        self._current_repo, self._current_full = self._queue.pop(0)
        self.progress_bar.setValue(0)
        mode_lbl = "full rebuild" if self._current_full else "incremental"
        self.progress_status.setText(f"Indexing ({mode_lbl}): {self._current_repo}...")
        self.progress_status.setStyleSheet(f"color: {COLOR_ACCENT}; font-weight: 600;")
        self.indexing_log.emit(f"[START] Indexing '{self._current_repo}' ({mode_lbl})...")
        self.indexing_started.emit(self._current_repo)

        proc = IndexProcess(self.repo_mgr.config_path, self._current_repo, full=self._current_full, parent=self)
        proc.progress.connect(self._on_progress)
        proc.log_line.connect(self._on_log)
        proc.finished.connect(self._on_finished)
        self._proc = proc
        proc.start()

    def _on_progress(self, current: int, total: int, msg: str) -> None:
        if total > 0:
            pct = int(current * 100 / total)
            self.progress_bar.setMaximum(100)
            self.progress_bar.setValue(pct)
            self.progress_status.setText(f"Indexing {self._current_repo} ({current}/{total}): {msg}")
        else:
            self.progress_bar.setMaximum(0)
            self.progress_status.setText(f"Indexing {self._current_repo}: {msg}")
        self.indexing_progress.emit(self._current_repo, current, total, msg)

    def _on_log(self, line: str) -> None:
        self.indexing_log.emit(line)

    def _on_finished(self, ok: bool, message: str) -> None:
        proc = self._proc
        self._proc = None
        if proc is not None:
            proc.deleteLater()

        repo_id = self._current_repo
        self.progress_bar.setMaximum(100)
        if ok:
            self.progress_bar.setValue(100)
            self.indexing_log.emit(f"[DONE] '{repo_id}' indexed successfully: {message}")
        else:
            self.progress_bar.setValue(0)
            self.progress_status.setText(f"Failed ({repo_id}): {message}")
            self.progress_status.setStyleSheet(f"color: {COLOR_DANGER}; font-weight: 600;")
            self.indexing_log.emit(f"[FAILED] '{repo_id}': {message}")

        self.indexing_finished.emit(repo_id, ok, message)
        self._start_next_in_queue()

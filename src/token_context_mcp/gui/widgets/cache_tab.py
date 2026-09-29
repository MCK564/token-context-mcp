from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from token_context_mcp.gui.bridge import CacheManager
from token_context_mcp.gui.workers import run_async

if TYPE_CHECKING:
    from token_context_mcp.gui.bridge import RepoManager


class CacheTab(QWidget):
    def __init__(self, repo_mgr: RepoManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repo_mgr = repo_mgr
        self.cache_mgr = CacheManager(repo_mgr.config_path)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Overview Card
        overview_card = QFrame()
        overview_card.setProperty("class", "Card")
        o_layout = QVBoxLayout(overview_card)
        o_layout.setSpacing(10)

        o_title = QLabel("Storage Usage & Cache Health")
        o_title.setProperty("class", "CardHeader")
        o_layout.addWidget(o_title)

        info_row = QHBoxLayout()
        self.total_size_label = QLabel("Total DB Storage: -- MB")
        self.total_size_label.setStyleSheet("font-size: 15px; font-weight: 700; color: #89b4fa;")
        info_row.addWidget(self.total_size_label)

        self.memory_db_label = QLabel("Episodic Memory: -- MB")
        self.memory_db_label.setStyleSheet("color: #a5adcb;")
        info_row.addWidget(self.memory_db_label)

        info_row.addStretch()

        self.dir_label = QLabel("Directory: --")
        self.dir_label.setStyleSheet("color: #6e738d; font-size: 11px;")
        info_row.addWidget(self.dir_label)

        o_layout.addLayout(info_row)
        layout.addWidget(overview_card)

        # Action Buttons Row
        action_row = QHBoxLayout()
        action_row.setSpacing(12)

        self.vacuum_btn = QPushButton("🧹 Vacuum selected databases")
        self.vacuum_btn.setToolTip(
            "Defragment the databases ticked below (memory, governance, audit). Index snapshots are immutable and are never vacuumed."
        )
        self.vacuum_btn.clicked.connect(self._vacuum_db)
        action_row.addWidget(self.vacuum_btn)

        self.clean_stale_btn = QPushButton("🗑️ Clean old snapshots")
        self.clean_stale_btn.setToolTip("Delete index snapshots of repositories no longer registered and superseded snapshots")
        self.clean_stale_btn.clicked.connect(self._clean_stale)
        action_row.addWidget(self.clean_stale_btn)

        self.purge_btn = QPushButton("⚠️ Purge All Cache")
        self.purge_btn.setProperty("class", "DangerButton")
        self.purge_btn.setToolTip("Delete all indexed snapshots. Configuration remains safe.")
        self.purge_btn.clicked.connect(self._purge_all)
        action_row.addWidget(self.purge_btn)

        action_row.addStretch()

        action_row.addWidget(QLabel("Max Cache Warning:"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(50, 10000)
        self.limit_spin.setValue(500)
        self.limit_spin.setSuffix(" MB")
        action_row.addWidget(self.limit_spin)

        layout.addLayout(action_row)

        # Databases the user may vacuum (M8.9): the mutable ones only
        self.vacuum_list = QListWidget()
        self.vacuum_list.setMaximumHeight(90)
        layout.addWidget(self.vacuum_list)

        # Database Breakdown Table
        tbl_label = QLabel("Database Files Breakdown:")
        tbl_label.setStyleSheet("font-size: 13px; font-weight: 600; color: #cad3f5;")
        layout.addWidget(tbl_label)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Repo ID", "Database File", "Size (MB)", "Absolute Path"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)
        self.silent = False  # tests: no modal boxes

    # -- fetch / render (M8.2) ---------------------------------------------------------------------------------------
    def fetch(self) -> dict:
        """Worker-side: sizes of index snapshots and of the mutable databases."""
        stats = self.cache_mgr.get_storage_stats()
        stats["vacuum_targets"] = self.cache_mgr.vacuum_targets()
        return stats

    def refresh(self) -> None:
        run_async(self.fetch, on_ok=self.render)

    refresh_stats = refresh  # name used by older callers

    def render(self, stats: dict) -> None:
        checked = {self.vacuum_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.vacuum_list.count())
                   if self.vacuum_list.item(i).checkState() == Qt.CheckState.Checked}
        self.vacuum_list.clear()
        for target in stats.get("vacuum_targets", []):
            item = QListWidgetItem(f"{target['name']}  ({target['size_bytes'] / 1024:.0f} KB)")
            item.setData(Qt.ItemDataRole.UserRole, target["name"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if target["name"] in checked else Qt.CheckState.Unchecked)
            self.vacuum_list.addItem(item)
        total_mb = stats["total_size_mb"]
        self.total_size_label.setText(f"Total DB Storage: {total_mb:.1f} MB")
        self.memory_db_label.setText(f"Episodic Memory: {stats['memory_db_size_mb']:.2f} MB")
        self.dir_label.setText(f"Indexes: {stats['indexes_directory']}")

        limit = self.limit_spin.value()
        if total_mb > limit:
            self.total_size_label.setStyleSheet("font-size: 15px; font-weight: 700; color: #ed8796;")
        else:
            self.total_size_label.setStyleSheet("font-size: 15px; font-weight: 700; color: #89b4fa;")

        dbs = stats["databases"]
        self.table.setRowCount(len(dbs))
        for row, item in enumerate(dbs):
            self.table.setItem(row, 0, QTableWidgetItem(item["repo_id"]))
            self.table.setItem(row, 1, QTableWidgetItem(item["file_name"]))

            sz_item = QTableWidgetItem(f"{item['size_mb']:.2f} MB")
            sz_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 2, sz_item)

            self.table.setItem(row, 3, QTableWidgetItem(item["path"]))

    def _selected_vacuum_names(self) -> list[str]:
        return [
            self.vacuum_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.vacuum_list.count())
            if self.vacuum_list.item(i).checkState() == Qt.CheckState.Checked
        ]

    def _notify(self, title: str, text: str) -> None:
        self.last_message = (title, text)
        if not self.silent:
            QMessageBox.information(self, title, text)

    def _vacuum_db(self) -> None:
        names = self._selected_vacuum_names()
        if not names:
            self._notify("Nothing selected", "Tick at least one database to vacuum.")
            return
        self.vacuum_btn.setEnabled(False)
        run_async(self.cache_mgr.vacuum_databases, names, on_ok=self._on_vacuum_done, on_err=self._on_action_error)

    def _on_vacuum_done(self, results: list) -> None:
        self.vacuum_btn.setEnabled(True)
        lines = []
        for r in results:
            if r["status"] == "ok":
                lines.append(f"{r['name']}: OK, reclaimed {r['reclaimed_bytes'] / 1024:.1f} KB")
            else:
                lines.append(f"{r['name']}: FAILED - {r['error']}")
        self.refresh()
        self._notify("Vacuum finished", "\n".join(lines))

    def _on_action_error(self, error: BaseException) -> None:
        self.vacuum_btn.setEnabled(True)
        self._notify("Error", str(error))

    def _clean_stale(self) -> None:
        run_async(self.cache_mgr.clean_stale_snapshots, on_ok=self._on_cleaned, on_err=self._on_action_error)

    def _on_cleaned(self, cleaned: list) -> None:
        self.refresh()
        if cleaned:
            self._notify("Old snapshots removed", f"Removed {len(cleaned)} files:\n" + "\n".join(map(str, cleaned)))
        else:
            self._notify("Nothing to clean", "All snapshots belong to registered repositories and are current.")

    def _purge_all(self) -> None:
        confirm = QMessageBox.warning(
            self,
            "Confirm Purge All Cache",
            "This will delete ALL local SQLite index snapshots.\nYour repository configurations (repos.toml) and memory will be kept.\nYou will need to re-index your repositories.\n\nProceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            run_async(self.cache_mgr.purge_all_cache, on_ok=self._on_purged, on_err=self._on_action_error)

    def _on_purged(self, count: int) -> None:
        self.refresh()
        self._notify("Cache Purged", f"Deleted {count} cache artifacts. Ready for re-indexing.")

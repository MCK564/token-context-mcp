from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from token_context_mcp.gui.bridge import CacheManager

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

        self.vacuum_btn = QPushButton("🧹 Vacuum Databases")
        self.vacuum_btn.setToolTip("Defragment SQLite files and reclaim unused disk space")
        self.vacuum_btn.clicked.connect(self._vacuum_db)
        action_row.addWidget(self.vacuum_btn)

        self.clean_stale_btn = QPushButton("🗑️ Clean Stale Snapshots")
        self.clean_stale_btn.setToolTip("Delete index snapshots for repositories no longer in repos.toml")
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

        self.refresh_stats()

    def refresh_stats(self) -> None:
        stats = self.cache_mgr.get_storage_stats()
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

    def _vacuum_db(self) -> None:
        reclaimed_bytes = self.cache_mgr.vacuum_database()
        reclaimed_kb = reclaimed_bytes / 1024
        self.refresh_stats()
        QMessageBox.information(
            self,
            "Vacuum Complete",
            f"Successfully executed VACUUM on all SQLite databases.\nReclaimed: {reclaimed_kb:.1f} KB.",
        )

    def _clean_stale(self) -> None:
        cleaned = self.cache_mgr.clean_stale_snapshots()
        self.refresh_stats()
        if cleaned:
            QMessageBox.information(
                self,
                "Stale Snapshots Cleaned",
                f"Removed {len(cleaned)} orphaned database files:\n" + "\n".join(cleaned),
            )
        else:
            QMessageBox.information(self, "No Stale Snapshots", "All database files belong to active registered repositories.")

    def _purge_all(self) -> None:
        confirm = QMessageBox.warning(
            self,
            "Confirm Purge All Cache",
            "This will delete ALL local SQLite index snapshots.\nYour repository configurations (repos.toml) and memory will be kept.\nYou will need to re-index your repositories.\n\nProceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            count = self.cache_mgr.purge_all_cache()
            self.refresh_stats()
            QMessageBox.information(self, "Cache Purged", f"Deleted {count} cache artifacts. Ready for re-indexing.")

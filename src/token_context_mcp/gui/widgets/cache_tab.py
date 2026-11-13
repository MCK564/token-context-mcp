from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from token_context_mcp.gui.bridge import CacheManager, RepoManager
from token_context_mcp.gui.icons import make_icon
from token_context_mcp.gui.theme import (
    COLOR_DANGER,
    COLOR_SUCCESS,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_WARNING,
)
from token_context_mcp.gui.workers import is_ui_thread, run_async


class CacheTab(QWidget):
    def __init__(self, repo_mgr: RepoManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repo_mgr = repo_mgr
        self.cache_mgr = CacheManager(repo_mgr.config_path)
        self._last_stats: dict[str, Any] = {}

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

        # 1. Storage Overview Card
        overview_card = QFrame()
        overview_card.setProperty("class", "Card")
        o_layout = QVBoxLayout(overview_card)
        o_layout.setContentsMargins(16, 14, 16, 14)
        o_layout.setSpacing(8)

        o_title = QLabel("Storage Usage & Cache Health")
        o_title.setProperty("class", "SectionTitle")
        o_layout.addWidget(o_title)

        stat_row = QHBoxLayout()
        stat_row.setSpacing(14)
        self.total_size_label = QLabel("Total On-Disk: 0.0 MB")
        self.total_size_label.setStyleSheet("font-size: 15px; font-weight: 700;")
        self.active_stale_label = QLabel("Active: 0.0 MB | Stale/Orphan: 0.0 MB")
        self.active_stale_label.setProperty("class", "MutedHint")
        self.sys_dbs_label = QLabel("Memory: 0.0 MB | Ledger: 0.0 MB")
        self.sys_dbs_label.setProperty("class", "MutedHint")
        stat_row.addWidget(self.total_size_label)
        stat_row.addWidget(self.active_stale_label)
        stat_row.addStretch()
        stat_row.addWidget(self.sys_dbs_label)
        o_layout.addLayout(stat_row)

        self.dir_label = QLabel("Indexes: -")
        self.dir_label.setProperty("class", "MutedHint")
        self.dir_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        o_layout.addWidget(self.dir_label)

        layout.addWidget(overview_card)

        # 2. Responsive Action Toolbar (2 compact rows)
        act_row = QHBoxLayout()
        act_row.setSpacing(8)

        self.vacuum_btn = QPushButton("Vacuum Selected")
        self.vacuum_btn.setIcon(make_icon("broom", COLOR_TEXT_PRIMARY))
        self.vacuum_btn.clicked.connect(self._vacuum_selected)

        self.select_all_btn = QPushButton("Select All DBs")
        self.select_all_btn.clicked.connect(self._toggle_select_all_vacuum)

        self.clean_btn = QPushButton("Clean Stale Snapshots")
        self.clean_btn.setIcon(make_icon("trash", COLOR_TEXT_PRIMARY))
        self.clean_btn.clicked.connect(self._clean_stale)

        self.purge_btn = QPushButton("Purge All Cache")
        self.purge_btn.setIcon(make_icon("stop", COLOR_DANGER))
        self.purge_btn.setProperty("class", "DangerButton")
        self.purge_btn.clicked.connect(self._purge_all)

        act_row.addWidget(self.vacuum_btn)
        act_row.addWidget(self.select_all_btn)
        act_row.addWidget(self.clean_btn)
        act_row.addWidget(self.purge_btn)
        act_row.addStretch()
        layout.addLayout(act_row)

        warn_row = QHBoxLayout()
        warn_row.setSpacing(8)
        warn_row.addWidget(QLabel("Max Cache Warning:"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(50, 10000)
        self.limit_spin.setValue(500)
        self.limit_spin.setSuffix(" MB")
        self.limit_spin.valueChanged.connect(lambda _: self._refresh_size_color())
        warn_row.addWidget(self.limit_spin)

        warn_row.addSpacing(12)
        self.stale_only_chk = QCheckBox("Show SUPERSEDED / ORPHAN snapshots only")
        self.stale_only_chk.toggled.connect(lambda _: self._render_db_table())
        warn_row.addWidget(self.stale_only_chk)
        warn_row.addStretch()
        layout.addLayout(warn_row)

        # 3. Mutable databases vacuum list (includes ledger.sqlite!)
        vac_lbl = QLabel("Mutable System Databases (Safe to VACUUM — excludes immutable index snapshots):")
        vac_lbl.setProperty("class", "MutedHint")
        layout.addWidget(vac_lbl)

        self.vacuum_list = QListWidget()
        self.vacuum_list.setMaximumHeight(105)
        self.vacuum_list.setAlternatingRowColors(True)
        layout.addWidget(self.vacuum_list)

        # 4. Databases Breakdown Table
        tbl_lbl = QLabel("Index Snapshot Files Breakdown:")
        tbl_lbl.setProperty("class", "SectionTitle")
        layout.addWidget(tbl_lbl)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Repo ID", "Status", "Snapshot File", "Size (MB)", "Absolute Path"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(2, 215)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(200)
        layout.addWidget(self.table, 1)

    def refresh(self) -> None:
        run_async(self.fetch, on_ok=self.render)

    def fetch(self) -> dict[str, Any]:
        assert not is_ui_thread(), "CacheTab.fetch must run off the UI thread"
        return {
            "stats": self.cache_mgr.get_storage_stats(),
            "targets": self.cache_mgr.vacuum_targets(),
        }

    def render(self, snap: dict[str, Any]) -> None:
        assert is_ui_thread(), "CacheTab.render must run on the UI thread"
        stats = snap["stats"] if "stats" in snap else snap
        targets = snap.get("targets", [])
        self._last_stats = stats

        total_mb = stats.get("total_size_mb", 0.0)
        active_mb = stats.get("active_size_mb", total_mb)
        stale_mb = stats.get("stale_size_mb", 0.0)
        mem_mb = stats.get("memory_db_size_mb", 0.0)
        led_mb = stats.get("ledger_db_size_mb", 0.0)

        self.total_size_label.setText(f"Total On-Disk: {total_mb:.2f} MB")
        self.active_stale_label.setText(f"(Active: {active_mb:.2f} MB · Stale/Orphan: {stale_mb:.2f} MB)")
        self.sys_dbs_label.setText(f"Memory DB: {mem_mb:.2f} MB · Ledger DB: {led_mb:.2f} MB")
        self.dir_label.setText(f"Indexes: {stats.get('indexes_directory', '-')}")
        self._refresh_size_color()

        # Populate vacuum checkboxes
        self.vacuum_list.clear()
        for target in targets:
            kb = target["size_bytes"] / 1024.0
            label = f"{target['name']}  ({kb:.1f} KB)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, target["name"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.vacuum_list.addItem(item)
        self.vacuum_btn.setEnabled(bool(targets))

        self._render_db_table()

    def _refresh_size_color(self) -> None:
        total_mb = float(self._last_stats.get("total_size_mb", 0.0) or 0.0)
        limit_mb = self.limit_spin.value()
        color = COLOR_DANGER if total_mb > limit_mb else COLOR_SUCCESS
        self.total_size_label.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {color};")

    def _render_db_table(self) -> None:
        dbs = list(self._last_stats.get("databases", []))
        if self.stale_only_chk.isChecked():
            dbs = [d for d in dbs if d.get("status") != "ACTIVE"]
        self.table.setRowCount(len(dbs))
        for row, db in enumerate(dbs):
            status = str(db.get("status", "ACTIVE"))
            st_item = QTableWidgetItem(status)
            st_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if status == "ACTIVE":
                st_item.setForeground(QColor(COLOR_SUCCESS))
            elif status == "SUPERSEDED":
                st_item.setForeground(QColor(COLOR_WARNING))
            else:
                st_item.setForeground(QColor(COLOR_DANGER))

            sz_item = QTableWidgetItem(f"{db['size_mb']:.2f} MB")
            sz_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            self.table.setItem(row, 0, QTableWidgetItem(str(db["repo_id"])))
            self.table.setItem(row, 1, st_item)
            self.table.setItem(row, 2, QTableWidgetItem(str(db["file_name"])))
            self.table.setItem(row, 3, sz_item)
            self.table.setItem(row, 4, QTableWidgetItem(str(db["path"])))

    def _toggle_select_all_vacuum(self) -> None:
        any_unchecked = any(
            self.vacuum_list.item(i).checkState() != Qt.CheckState.Checked
            for i in range(self.vacuum_list.count())
        )
        new_state = Qt.CheckState.Checked if any_unchecked else Qt.CheckState.Unchecked
        for i in range(self.vacuum_list.count()):
            self.vacuum_list.item(i).setCheckState(new_state)

    def _vacuum_selected(self) -> None:
        chosen = [
            self.vacuum_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.vacuum_list.count())
            if self.vacuum_list.item(i).checkState() == Qt.CheckState.Checked
        ]
        if not chosen:
            QMessageBox.information(self, "Nothing Selected", "Check one or more mutable databases to VACUUM.")
            return
        self.vacuum_btn.setEnabled(False)
        run_async(self.cache_mgr.vacuum_databases, chosen, on_ok=self._on_vacuum_done, on_err=self._on_op_error)

    def _on_vacuum_done(self, results: list[dict[str, Any]]) -> None:
        self.vacuum_btn.setEnabled(True)
        lines = []
        for r in results:
            if r["status"] == "ok":
                lines.append(f"OK {r['name']}: reclaimed {r['reclaimed_bytes']:,} bytes")
            else:
                lines.append(f"ERR {r['name']}: {r['error']}")
        QMessageBox.information(self, "VACUUM Complete", "\n".join(lines))
        self.refresh()

    def _on_op_error(self, exc: BaseException) -> None:
        self.vacuum_btn.setEnabled(True)
        QMessageBox.warning(self, "Operation Failed", str(exc))

    def _clean_stale(self) -> None:
        run_async(self.cache_mgr.clean_stale_snapshots, on_ok=self._on_clean_done, on_err=self._on_op_error)

    def _on_clean_done(self, removed: list[str]) -> None:
        if removed:
            QMessageBox.information(self, "Snapshots Cleaned", f"Removed {len(removed)} stale/orphan snapshot file(s).")
        else:
            QMessageBox.information(self, "Clean", "No stale or orphan snapshot files found.")
        self.refresh()

    def _purge_all(self) -> None:
        reply = QMessageBox.warning(
            self,
            "Confirm Purge All Cache",
            "This deletes ALL cached SQLite index snapshots while keeping repos.toml intact. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            run_async(self.cache_mgr.purge_all_cache, on_ok=self._on_purge_done, on_err=self._on_op_error)

    def _on_purge_done(self, cnt: int) -> None:
        QMessageBox.information(self, "Cache Purged", f"Deleted {cnt} index cache file(s).")
        self.refresh()

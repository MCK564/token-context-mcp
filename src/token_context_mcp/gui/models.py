"""Table model for the repository list (M8.6): no per-row widgets, badges are colours of the status cell."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QBrush, QColor

COLUMNS = ("Repo ID", "Root Path", "Status", "Symbols", "Ambiguous", "DB Size")

STATUS_COLORS = {
    "FRESH": "#a6da95",
    "STALE": "#eed49f",
    "DOCS_CHANGED": "#8aadf4",
    "SCHEMA_OUTDATED": "#f5a97f",
    "NOT_INDEXED": "#6e738d",
}
STATUS_HINTS = {
    "FRESH": "The index matches the files on disk.",
    "STALE": "Indexed files changed since the last index: re-index.",
    "DOCS_CHANGED": "Only files that are not indexed changed (docs, configs): the index is still valid.",
    "SCHEMA_OUTDATED": "The index was built by an older schema: re-index to use the current one.",
    "NOT_INDEXED": "No index yet.",
}

_RIGHT = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


class RepoTableModel(QAbstractTableModel):
    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []

    # -- data ------------------------------------------------------------------------------------------------
    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def row_at(self, row: int) -> dict[str, Any] | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def repo_id_at(self, row: int) -> str | None:
        item = self.row_at(row)
        return None if item is None else str(item["repo_id"])

    # -- Qt model API -----------------------------------------------------------------------------------------
    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        item = self._rows[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return item["repo_id"]
            if column == 1:
                return item["root"]
            if column == 2:
                return item["status"]
            if column == 3:
                return f"{item['symbols_count']:,}"
            if column == 4:
                return f"{item['ambiguous_rate'] * 100:.1f}%"  # stored as a 0-1 ratio, shown as a percentage
            if column == 5:
                return f"{item['db_size_mb']:.1f} MB"
        elif role == Qt.ItemDataRole.TextAlignmentRole and column >= 3:
            return _RIGHT
        elif role == Qt.ItemDataRole.ForegroundRole and column == 2:
            return QBrush(QColor(STATUS_COLORS.get(item["status"], "#cad3f5")))
        elif role == Qt.ItemDataRole.ToolTipRole and column == 2:
            return STATUS_HINTS.get(item["status"], "")
        elif role == Qt.ItemDataRole.UserRole:
            return item
        return None

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


class V2TaskTableModel(QAbstractTableModel):
    HEADERS = ["相对路径", "状态", "缓存目录"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks = []

    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._tasks)

    def columnCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        task = self._tasks[index.row()]
        if index.column() == 0:
            return str(task.relative_path)
        if index.column() == 1:
            return task.status if task.cache_valid else "需转写"
        if index.column() == 2:
            return str(task.cache_dir)
        return None

    def headerData(self, section: int, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return str(section + 1)

    def set_tasks(self, tasks: list) -> None:
        self.beginResetModel()
        self._tasks = list(tasks)
        self.endResetModel()

    def tasks(self) -> list:
        return list(self._tasks)

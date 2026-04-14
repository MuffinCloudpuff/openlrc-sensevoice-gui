from __future__ import annotations

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QDialog,
        QDialogButtonBox,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QMessageBox,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 未安装，无法加载翻译确认弹窗。") from exc


class ConfirmationDialog(QDialog):
    def __init__(self, state: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("翻译确认")
        self.resize(920, 560)
        self._build_ui()
        self._load_state()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.summary_grid = QGridLayout()
        self.summary_labels: dict[str, QLabel] = {}
        for index, key in enumerate(["待确认文件", "保底估算", "建议预留", "目标语言"]):
            title = QLabel(key)
            title.setStyleSheet("font-weight: 600;")
            value = QLabel()
            value.setWordWrap(True)
            row = index // 2
            col = (index % 2) * 2
            self.summary_grid.addWidget(title, row, col)
            self.summary_grid.addWidget(value, row, col + 1)
            self.summary_labels[key] = value
        layout.addLayout(self.summary_grid)

        action_row = QHBoxLayout()
        self.select_all_button = QPushButton("全选待翻译文件")
        self.select_all_button.clicked.connect(self._select_all)
        action_row.addWidget(self.select_all_button)

        self.clear_all_button = QPushButton("全不选")
        self.clear_all_button.clicked.connect(self._clear_all)
        action_row.addWidget(self.clear_all_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["翻译", "相对路径", "保底估算", "建议预留"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

        self.selection_hint = QLabel("未选择的文件会保留 ASR 缓存，后续仍可继续翻译。")
        self.selection_hint.setWordWrap(True)
        layout.addWidget(self.selection_hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept_checked)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_state(self) -> None:
        entries = self.state.get("entries", [])
        self.summary_labels["待确认文件"].setText(str(len(entries)))
        self.summary_labels["保底估算"].setText(f"${float(self.state.get('total_floor_fee', 0.0)):.4f}")
        self.summary_labels["建议预留"].setText(f"${float(self.state.get('total_likely_fee', 0.0)):.4f}")
        self.summary_labels["目标语言"].setText(str(self.state.get("target_lang", "")))

        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            checked_item = QTableWidgetItem()
            checked_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            checked_item.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(row, 0, checked_item)
            self.table.setItem(row, 1, QTableWidgetItem(entry["relative_path"]))
            self.table.setItem(row, 2, QTableWidgetItem(f"${float(entry['estimate']['total_floor_fee']):.4f}"))
            self.table.setItem(row, 3, QTableWidgetItem(f"${float(entry['estimate']['total_likely_fee']):.4f}"))
        self.table.resizeColumnsToContents()

    def _select_all(self) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(Qt.CheckState.Checked)

    def _clear_all(self) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(Qt.CheckState.Unchecked)

    def selected_relative_paths(self) -> list[str]:
        selected: list[str] = []
        for row in range(self.table.rowCount()):
            checked_item = self.table.item(row, 0)
            path_item = self.table.item(row, 1)
            if checked_item and path_item and checked_item.checkState() == Qt.CheckState.Checked:
                selected.append(path_item.text())
        return selected

    def _accept_checked(self) -> None:
        if not self.selected_relative_paths():
            QMessageBox.warning(self, "未选择文件", "请至少选择一个文件再继续。")
            return
        self.accept()

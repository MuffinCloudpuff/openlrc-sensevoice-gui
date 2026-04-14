from __future__ import annotations

from PySide6.QtWidgets import QFrame, QPushButton, QVBoxLayout


class V2Sidebar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 28, 0, 28)
        layout.setSpacing(14)

        self.btn_task = self._sidebar_button("✓", "任务流水线")
        self.btn_task.setChecked(True)
        self.btn_history = self._sidebar_button("◷", "近期处理记录")
        self.btn_setting = self._sidebar_button("⚙", "全局设置")

        layout.addWidget(self.btn_task)
        layout.addWidget(self.btn_history)
        layout.addStretch()
        layout.addWidget(self.btn_setting)

    def _sidebar_button(self, text: str, tooltip: str) -> QPushButton:
        button = QPushButton(text)
        button.setToolTip(tooltip)
        button.setCheckable(True)
        button.clicked.connect(lambda checked=False, b=button: self.select_button(b))
        return button

    def select_button(self, selected_button: QPushButton) -> None:
        for button in [self.btn_task, self.btn_history, self.btn_setting]:
            button.setChecked(button is selected_button)

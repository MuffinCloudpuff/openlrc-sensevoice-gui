from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QMainWindow, QScrollArea, QSizePolicy, QWidget

from .controllers.v2_controller import V2Controller
from .styles.apple_dark import APPLE_DARK_STYLE
from .widgets.v2_settings_drawer import V2SettingsDrawer
from .widgets.v2_sidebar import V2Sidebar
from .widgets.v2_workspace import V2Workspace


class MainWindowV2(QMainWindow):
    def __init__(self, config_path: str | Path | None = None):
        super().__init__()
        self.setWindowTitle("OpenLRC Studio V2")
        self.resize(1280, 800)
        self.setMinimumSize(980, 620)
        self.setStyleSheet(APPLE_DARK_STYLE)

        self.is_left_drawer_open = True
        self.left_drawer_width = 82
        self.is_right_drawer_open = True
        self.right_drawer_width = 420
        self.right_scroll: QScrollArea | None = None

        self.central = QWidget()
        self.setCentralWidget(self.central)
        main_layout = QHBoxLayout(self.central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.sidebar = V2Sidebar()
        self.workspace = V2Workspace()
        self.settings_drawer = V2SettingsDrawer()

        self.left_wrapper = self._create_drawer_wrapper(self.sidebar, self.left_drawer_width, scrollable=False)
        self.right_wrapper = self._create_drawer_wrapper(self.settings_drawer, self.right_drawer_width, scrollable=True)

        main_layout.addWidget(self.left_wrapper)
        main_layout.addWidget(self.workspace, stretch=1)
        main_layout.addWidget(self.right_wrapper)

        self.workspace.btn_toggle_left.clicked.connect(self.toggle_left_sidebar)
        self.workspace.btn_toggle_right.clicked.connect(self.toggle_right_drawer)

        self.anim_left = self._build_drawer_animation(self.left_wrapper)
        self.anim_right = self._build_drawer_animation(self.right_wrapper)
        self.anim_left.finished.connect(self._finalize_left_drawer)
        self.anim_right.finished.connect(self._finalize_right_drawer)

        self.controller = V2Controller(self, Path(config_path) if config_path else None)
        self.controller.initialize()

    def _create_drawer_wrapper(self, inner_widget: QWidget, width: int, scrollable: bool) -> QFrame:
        wrapper = QFrame()
        if scrollable:
            wrapper.setObjectName("rightDrawerWrapper")
        wrapper.setMinimumWidth(width)
        wrapper.setMaximumWidth(width)
        wrapper.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if scrollable:
            scroll = QScrollArea()
            scroll.setObjectName("rightDrawerScroll")
            scroll.setWidget(inner_widget)
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
            scroll.setFrameShape(QFrame.NoFrame)
            inner_widget.setMinimumWidth(width)
            inner_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            layout.addWidget(scroll)
            self.right_scroll = scroll
        else:
            inner_widget.setFixedWidth(width)
            layout.addWidget(inner_widget)
        return wrapper

    def _build_drawer_animation(self, widget: QWidget) -> QPropertyAnimation:
        anim = QPropertyAnimation(widget, b"maximumWidth", self)
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        anim.setDuration(240)
        return anim

    def _animate_drawer(self, wrapper: QWidget, animation: QPropertyAnimation, open_width: int, should_open: bool) -> None:
        animation.stop()
        wrapper.setMinimumWidth(0)
        animation.setStartValue(wrapper.width())
        animation.setEndValue(open_width if should_open else 0)
        animation.start()

    def _finalize_left_drawer(self) -> None:
        if self.is_left_drawer_open:
            self.left_wrapper.setMinimumWidth(self.left_drawer_width)
            self.left_wrapper.setMaximumWidth(self.left_drawer_width)
        else:
            self.left_wrapper.setMinimumWidth(0)
            self.left_wrapper.setMaximumWidth(0)

    def _finalize_right_drawer(self) -> None:
        if self.is_right_drawer_open:
            self.right_wrapper.setMinimumWidth(self.right_drawer_width)
            self.right_wrapper.setMaximumWidth(self.right_drawer_width)
        else:
            self.right_wrapper.setMinimumWidth(0)
            self.right_wrapper.setMaximumWidth(0)

    def toggle_left_sidebar(self) -> None:
        self.is_left_drawer_open = not self.is_left_drawer_open
        self._animate_drawer(self.left_wrapper, self.anim_left, self.left_drawer_width, self.is_left_drawer_open)
        self.workspace.btn_toggle_left.setText("隐藏侧栏" if self.is_left_drawer_open else "显示侧栏")

    def toggle_right_drawer(self) -> None:
        self.is_right_drawer_open = not self.is_right_drawer_open
        self._animate_drawer(self.right_wrapper, self.anim_right, self.right_drawer_width, self.is_right_drawer_open)
        self.workspace.btn_toggle_right.setText("隐藏配置" if self.is_right_drawer_open else "显示配置")



if __name__ == "__main__":
    app = QApplication([])
    window = MainWindowV2()
    window.show()
    app.exec()

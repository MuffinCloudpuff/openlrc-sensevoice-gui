from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class FluidAccordionCard(QFrame):
    expansion_changed = Signal(bool)

    def __init__(self, title: str, status_text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("class", "FluidCard")
        self.is_expanded = False
        self.header_height = 0
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 55))
        self.setGraphicsEffect(shadow)
        self.shadow = shadow

        self._build_ui(title, status_text)
        self.anim = QPropertyAnimation(self, b"maximumHeight", self)
        self.anim.setEasingCurve(QEasingCurve.InOutCubic)
        self.anim.setDuration(260)
        self.anim.valueChanged.connect(self._on_height_animating)
        self.anim.finished.connect(self._finalize_animation)

    def _build_ui(self, title: str, status_text: str) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.header = QFrame()
        self.header.setProperty("class", "FluidCardHeader")
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.header.mousePressEvent = self.toggle_expansion

        h_layout = QHBoxLayout(self.header)
        h_layout.setContentsMargins(20, 16, 20, 16)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("title")
        self.title_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        h_layout.addWidget(self.title_label)
        h_layout.addStretch()

        self.status_label = QLabel(status_text)
        self.status_label.setStyleSheet("color: #AEAEB2;")
        self.status_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        h_layout.addWidget(self.status_label)

        self.arrow = QLabel("▸")
        self.arrow.setStyleSheet("color: #AEAEB2; font-size: 12px; margin-left: 6px;")
        self.arrow.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        h_layout.addWidget(self.arrow)
        main_layout.addWidget(self.header)
        self.header_height = self.header.sizeHint().height()

        self.content_widget = QFrame()
        self.content_widget.setProperty("class", "FluidContentBox")
        self.content_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(20, 18, 20, 22)
        self.content_layout.setSpacing(14)
        self.content_widget.setMaximumHeight(0)
        self.setMinimumHeight(self.header_height)
        self.setMaximumHeight(self.header_height)
        self.setFixedHeight(self.header_height)
        main_layout.addWidget(self.content_widget)

    def set_content_layout(self, layout: QVBoxLayout | QFormLayout) -> None:
        QWidget().setLayout(self.content_widget.layout())
        self.content_widget.setLayout(layout)
        self.content_layout = layout
        self.content_widget.adjustSize()
        self.adjustSize()

    def sizeHint(self):
        hint = super().sizeHint()
        return hint.expandedTo(self.minimumSizeHint())

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        return hint.expandedTo(hint.__class__(hint.width(), self.height()))

    def expand(self) -> None:
        if not self.is_expanded:
            self.toggle_expansion()
        self.anim.stop()
        self._finalize_animation()

    def collapse(self) -> None:
        if self.is_expanded:
            self.toggle_expansion()

    def toggle_expansion(self, event=None) -> None:
        self.is_expanded = not self.is_expanded
        self.expansion_changed.emit(self.is_expanded)
        content_height = self._expanded_content_height()
        target_card_height = self.header_height + content_height

        self.anim.stop()
        self.anim.setStartValue(self.height())
        if self.is_expanded:
            self.content_widget.setMaximumHeight(content_height)
            self.anim.setEndValue(target_card_height)
            self.arrow.setText("▾")
            self.setStyleSheet(".FluidCard { border: 1px solid #0A84FF; background-color: #2C2C2E; }")
            self.shadow.setColor(QColor(0, 0, 0, 90))
        else:
            self.anim.setEndValue(self.header_height)
            self.arrow.setText("▸")
            self.setStyleSheet(".FluidCard { border: 1px solid #3A3A3C; background-color: #2C2C2E; }")
            self.shadow.setColor(QColor(0, 0, 0, 55))
        self.anim.start()

    def _expanded_content_height(self) -> int:
        return max(self.content_layout.sizeHint().height() + 12, self.content_widget.sizeHint().height(), 1)

    def _on_height_animating(self, value) -> None:
        card_height = int(value)
        content_height = max(card_height - self.header_height, 0)
        self.content_widget.setMaximumHeight(content_height)
        self.setFixedHeight(card_height)
        self._refresh_ancestor_layouts()

    def _finalize_animation(self) -> None:
        if self.is_expanded:
            content_height = self._expanded_content_height()
            self.content_widget.setMaximumHeight(content_height)
            self.setMinimumHeight(self.header_height + content_height)
            self.setMaximumHeight(self.header_height + content_height)
            self.setFixedHeight(self.header_height + content_height)
        else:
            self.content_widget.setMaximumHeight(0)
            self.setMinimumHeight(self.header_height)
            self.setMaximumHeight(self.header_height)
            self.setFixedHeight(self.header_height)
        self._refresh_ancestor_layouts()

    def _refresh_ancestor_layouts(self) -> None:
        self.updateGeometry()
        content_container = self.parentWidget()
        if content_container is not None:
            if content_container.layout():
                content_container.layout().invalidate()
                content_container.layout().activate()
            content_container.adjustSize()
            content_container.updateGeometry()

            scroll_content = content_container.parentWidget()
            if scroll_content is not None:
                if scroll_content.layout():
                    scroll_content.layout().invalidate()
                    scroll_content.layout().activate()
                scroll_content.updateGeometry()

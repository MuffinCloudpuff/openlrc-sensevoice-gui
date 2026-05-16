from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
    QScrollArea,
)

from ..models import SRC_LANG_OPTIONS
from .v2_task_table_model import V2TaskTableModel


class V2Workspace(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("workspace")
        self.runtime_fields: dict[str, object] = {}
        self.summary_labels: list[tuple[QLabel, QLabel]] = []
        self.task_model = V2TaskTableModel(self)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("workspaceScroll")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.content_widget = QWidget()
        self.content_widget.setObjectName("workspaceContent")
        self.content_widget.setStyleSheet("background-color: transparent;")
        self.scroll_area.setWidget(self.content_widget)
        main_layout.addWidget(self.scroll_area)

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self.content_widget)
        layout.setContentsMargins(38, 30, 38, 38)
        layout.setSpacing(22)

        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)

        self.btn_toggle_left = QPushButton("隐藏侧栏")
        self.btn_toggle_left.setToolTip("显示/隐藏左侧导航栏")
        top_layout.addWidget(self.btn_toggle_left)

        title_lbl = QLabel("  音频处理流水线")
        title_lbl.setFont(QFont("Microsoft YaHei UI", 22, QFont.Bold))
        top_layout.addWidget(title_lbl)
        top_layout.addStretch()

        self.btn_toggle_right = QPushButton("隐藏配置")
        self.btn_toggle_right.setToolTip("显示/隐藏参数配置")
        top_layout.addWidget(self.btn_toggle_right)
        layout.addWidget(top_bar)

        step1 = QGroupBox("步骤 1 · 目录与任务参数")
        step1_layout = QVBoxLayout(step1)
        step1_layout.setSpacing(14)

        self.dropzone = QLabel("选择一个根目录，系统会递归扫描其中所有音频文件。")
        self.dropzone.setObjectName("dropzone")
        self.dropzone.setAlignment(Qt.AlignCenter)
        self.dropzone.setMinimumHeight(110)
        step1_layout.addWidget(self.dropzone)

        root_row = QHBoxLayout()
        self.scan_root_dir_edit = QLineEdit()
        self.scan_root_dir_edit.setPlaceholderText("选择包含音频文件的根目录")
        root_row.addWidget(self.scan_root_dir_edit, 1)
        self.browse_button = QPushButton("选择")
        root_row.addWidget(self.browse_button)
        self.scan_button = QPushButton("扫描")
        root_row.addWidget(self.scan_button)
        step1_layout.addLayout(root_row)

        self.scan_status_label = QLabel("请选择一个根文件夹，系统会递归处理其中所有音频文件。")
        self.scan_status_label.setWordWrap(True)
        step1_layout.addWidget(self.scan_status_label)

        lang_row = QHBoxLayout()
        self.src_lang_combo = QComboBox()
        self.src_lang_combo.addItems(SRC_LANG_OPTIONS)
        self.runtime_fields["src_lang"] = self.src_lang_combo
        lang_row.addWidget(self._wrap_labeled_widget("源语言", self.src_lang_combo))

        self.target_lang_edit = QLineEdit()
        self.target_lang_edit.setPlaceholderText("zh-cn")
        self.runtime_fields["target_lang"] = self.target_lang_edit
        lang_row.addWidget(self._wrap_labeled_widget("目标语言", self.target_lang_edit))
        step1_layout.addLayout(lang_row)

        mode_row = QHBoxLayout()
        self.skip_trans_checkbox = QCheckBox("仅转写")
        self.runtime_fields["skip_trans"] = self.skip_trans_checkbox
        mode_row.addWidget(self.skip_trans_checkbox)
        self.noise_suppress_checkbox = QCheckBox("降噪")
        self.runtime_fields["noise_suppress"] = self.noise_suppress_checkbox
        mode_row.addWidget(self.noise_suppress_checkbox)
        self.bilingual_sub_checkbox = QCheckBox("双语字幕")
        self.runtime_fields["bilingual_sub"] = self.bilingual_sub_checkbox
        mode_row.addWidget(self.bilingual_sub_checkbox)
        mode_row.addStretch(1)
        step1_layout.addLayout(mode_row)
        layout.addWidget(step1)

        step2 = QGroupBox("步骤 2 · 任务摘要")
        step2_layout = QVBoxLayout(step2)
        step2_note = QLabel("开始前先检查当前模式、模型、设备、费用和根目录。")
        step2_note.setWordWrap(True)
        step2_layout.addWidget(step2_note)

        self.summary_grid = QGridLayout()
        for index in range(8):
            title = QLabel()
            title.setStyleSheet("font-weight: 600;")
            value = QLabel()
            value.setWordWrap(True)
            row = index // 4
            col = (index % 4) * 2
            self.summary_grid.addWidget(title, row, col)
            self.summary_grid.addWidget(value, row, col + 1)
            self.summary_labels.append((title, value))
        step2_layout.addLayout(self.summary_grid)
        layout.addWidget(step2)

        self.task_table = QTableView()
        self.task_table.setModel(self.task_model)
        self.task_table.verticalHeader().setVisible(False)
        self.task_table.horizontalHeader().setStretchLastSection(True)
        self.task_table.setShowGrid(False)
        self.task_table.setMinimumHeight(240)
        layout.addWidget(self.task_table)

        step3 = QGroupBox("步骤 3 · 翻译确认")
        step3_layout = QVBoxLayout(step3)
        self.confirmation_label = QLabel("ASR 和费用估算完成后，这里会显示翻译确认摘要。")
        self.confirmation_label.setWordWrap(True)
        step3_layout.addWidget(self.confirmation_label)
        self.open_confirmation_button = QPushButton("打开翻译确认")
        self.open_confirmation_button.setEnabled(False)
        step3_layout.addWidget(self.open_confirmation_button)
        self.replan_label = QLabel("")
        self.replan_label.setWordWrap(True)
        step3_layout.addWidget(self.replan_label)
        layout.addWidget(step3)

        status_group = QGroupBox("运行状态")
        status_layout = QVBoxLayout(status_group)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        status_layout.addWidget(self.progress_bar)
        self.stage_label = QLabel("等待开始...")
        self.stage_label.setWordWrap(True)
        status_layout.addWidget(self.stage_label)
        self.current_file_label = QLabel("当前文件：")
        self.current_file_label.setWordWrap(True)
        status_layout.addWidget(self.current_file_label)
        self.estimate_label = QLabel("费用估算：")
        self.estimate_label.setWordWrap(True)
        status_layout.addWidget(self.estimate_label)
        self.status_label = QLabel("处理开始后，这里会固定显示阶段进度、当前文件和实时日志。")
        self.status_label.setWordWrap(True)
        status_layout.addWidget(self.status_label)
        self.console = QPlainTextEdit()
        self.console.setObjectName("console")
        self.console.setReadOnly(True)
        self.console.setMinimumHeight(180)
        status_layout.addWidget(self.console)
        action_row = QHBoxLayout()
        self.start_button = QPushButton("开始处理")
        action_row.addWidget(self.start_button)
        self.rescan_button = QPushButton("重新扫描")
        action_row.addWidget(self.rescan_button)
        action_row.addStretch(1)
        status_layout.addLayout(action_row)
        layout.addWidget(status_group)
        layout.addStretch(1)

    def _wrap_labeled_widget(self, title: str, widget: QWidget) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(QLabel(title))
        layout.addWidget(widget)
        return wrapper

    def bind_runtime_handlers(self, callback) -> None:
        for widget in self.runtime_fields.values():
            if isinstance(widget, QComboBox):
                widget.currentTextChanged.connect(callback)
            elif isinstance(widget, QLineEdit):
                widget.textChanged.connect(callback)
            elif isinstance(widget, QCheckBox):
                widget.toggled.connect(callback)

    def load_runtime_config(self, config) -> None:
        for key, widget in self.runtime_fields.items():
            value = getattr(config, key)
            if isinstance(widget, QComboBox):
                widget.setCurrentText(str(value))
            elif isinstance(widget, QLineEdit):
                widget.setText(str(value))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
        self.scan_root_dir_edit.setText(config.scan_root_dir)

    def collect_runtime_config(self, config) -> None:
        config.scan_root_dir = self.scan_root_dir_edit.text().strip()
        for key, widget in self.runtime_fields.items():
            if isinstance(widget, QComboBox):
                value = widget.currentText()
            elif isinstance(widget, QLineEdit):
                value = widget.text().strip()
            elif isinstance(widget, QCheckBox):
                value = widget.isChecked()
            else:
                continue
            setattr(config, key, value)

    def render_summary(self, items: list) -> None:
        for pair, item in zip(self.summary_labels, items):
            pair[0].setText(item.label)
            pair[1].setText(item.value)

    def render_tasks(self, tasks: list) -> None:
        self.task_model.set_tasks(tasks)
        self.task_table.resizeColumnsToContents()

    def reset_progress(self) -> None:
        self.progress_bar.setValue(0)
        self.stage_label.setText("等待开始...")
        self.current_file_label.setText("当前文件：")
        self.estimate_label.setText("费用估算：")
        self.status_label.setText("处理开始后，这里会固定显示阶段进度、当前文件和实时日志。")

    def append_log(self, message: str) -> None:
        self.console.appendPlainText(message)

from __future__ import annotations

from pathlib import Path

from .config_store import load_config, save_config
from .models import (
    ASR_MODEL_OPTIONS,
    COMPUTE_TYPE_OPTIONS,
    ENDPOINT_MODE_OPTIONS,
    RELAY_PROVIDER_OPTIONS,
    SRC_LANG_OPTIONS,
    TRANSLATION_BACKEND_OPTIONS,
    AppConfig,
    ScanResult,
)
from .services.orchestrator import build_summary_items, cache_summary, detect_default_device, has_nvidia_gpu, scan_root_directory
from .services.validation import validate_before_processing
from .translation.replan import build_replan_text
from .widgets.confirmation_dialog import ConfirmationDialog
from .workers.process_worker import ProcessWorker

try:
    from PySide6.QtCore import Qt, QThread
    from PySide6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QDoubleSpinBox,
        QFileDialog,
        QFormLayout,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QSpinBox,
        QSplitter,
        QTableWidget,
        QTableWidgetItem,
        QToolBox,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 未安装，无法加载桌面界面。") from exc


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OpenLRC")
        self.resize(1480, 960)

        self.default_device = detect_default_device()
        self.config = load_config()
        if self.config.device not in ["cuda", "cpu"]:
            self.config.device = self.default_device
        self.scan_result = ScanResult()
        self.pending_confirmation_state: dict | None = None
        self.auto_open_confirmation_requested = False
        self.last_log_path: str | None = None
        self.worker_thread: QThread | None = None
        self.worker: ProcessWorker | None = None
        self._loading_config = False

        self._build_ui()
        self._load_config_to_widgets()
        self.refresh_scan()

    def _build_ui(self) -> None:
        root = QWidget(self)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_main_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([360, 1100])

        self.setCentralWidget(root)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("配置")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)

        self.toolbox = QToolBox()
        self.toolbox.addItem(self._build_asr_page(), "ASR")
        self.toolbox.addItem(self._build_translation_page(), "翻译")
        self.toolbox.addItem(self._build_performance_page(), "费用与性能")
        self.toolbox.addItem(self._build_advanced_page(), "输出与高级")
        layout.addWidget(self.toolbox)
        return panel

    def _build_main_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("OpenLRC")
        title.setStyleSheet("font-size: 28px; font-weight: 700;")
        subtitle = QLabel("使用 SenseVoice 和大语言模型进行音频转写与字幕翻译。")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.device_warning = QLabel("检测到 NVIDIA 显卡，但当前 Python/PyTorch 不是 CUDA 版；现在会按 CPU 跑。")
        self.device_warning.setStyleSheet("color: #b45309;")
        self.device_warning.setVisible(has_nvidia_gpu() and self.default_device != "cuda")
        layout.addWidget(self.device_warning)

        layout.addWidget(self._build_step1_group())
        layout.addWidget(self._build_step2_group())
        layout.addWidget(self._build_step3_group())
        layout.addWidget(self._build_status_group(), 1)
        return panel

    def _build_asr_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self.asr_model_combo = QComboBox()
        self.asr_model_combo.addItems(ASR_MODEL_OPTIONS)
        self.asr_model_combo.currentTextChanged.connect(self._on_config_changed)
        form.addRow("SenseVoice 模型", self.asr_model_combo)
        return page

    def _build_translation_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self.translation_backend_combo = QComboBox()
        self.translation_backend_combo.addItems(TRANSLATION_BACKEND_OPTIONS)
        self.translation_backend_combo.currentTextChanged.connect(self._on_endpoint_mode_changed)
        form.addRow("翻译模式", self.translation_backend_combo)

        self.endpoint_mode_combo = QComboBox()
        self.endpoint_mode_combo.addItems(ENDPOINT_MODE_OPTIONS)
        self.endpoint_mode_combo.currentTextChanged.connect(self._on_endpoint_mode_changed)
        form.addRow("接口模式", self.endpoint_mode_combo)

        self.relay_provider_combo = QComboBox()
        self.relay_provider_combo.addItems(RELAY_PROVIDER_OPTIONS)
        self.relay_provider_combo.currentTextChanged.connect(self._on_config_changed)
        form.addRow("中转提供商", self.relay_provider_combo)

        self.relay_base_url_edit = QLineEdit()
        self.relay_base_url_edit.textChanged.connect(self._on_config_changed)
        form.addRow("Base URL", self.relay_base_url_edit)

        self.relay_model_name_edit = QLineEdit()
        self.relay_model_name_edit.textChanged.connect(self._on_config_changed)
        form.addRow("中转模型名", self.relay_model_name_edit)

        self.remember_relay_key_checkbox = QCheckBox("记住中转 API Key")
        self.remember_relay_key_checkbox.toggled.connect(self._on_config_changed)
        form.addRow("", self.remember_relay_key_checkbox)

        self.relay_api_key_edit = QLineEdit()
        self.relay_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.relay_api_key_edit.textChanged.connect(self._on_config_changed)
        form.addRow("中转 API Key", self.relay_api_key_edit)

        self.openai_api_key_edit = QLineEdit()
        self.openai_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_api_key_edit.textChanged.connect(self._on_config_changed)
        form.addRow("OpenAI API Key", self.openai_api_key_edit)

        self.anthropic_api_key_edit = QLineEdit()
        self.anthropic_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.anthropic_api_key_edit.textChanged.connect(self._on_config_changed)
        form.addRow("Anthropic API Key", self.anthropic_api_key_edit)

        self.google_api_key_edit = QLineEdit()
        self.google_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.google_api_key_edit.textChanged.connect(self._on_config_changed)
        form.addRow("Google API Key", self.google_api_key_edit)

        self.openrouter_api_key_edit = QLineEdit()
        self.openrouter_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.openrouter_api_key_edit.textChanged.connect(self._on_config_changed)
        form.addRow("OpenRouter API Key", self.openrouter_api_key_edit)

        self.chatbot_model_edit = QLineEdit()
        self.chatbot_model_edit.textChanged.connect(self._on_config_changed)
        form.addRow("官方模型名", self.chatbot_model_edit)

        self.local_mt_model_id_edit = QLineEdit()
        self.local_mt_model_id_edit.textChanged.connect(self._on_config_changed)
        form.addRow("Ollama 模型名", self.local_mt_model_id_edit)

        self.local_mt_host_edit = QLineEdit()
        self.local_mt_host_edit.textChanged.connect(self._on_config_changed)
        form.addRow("Ollama 地址", self.local_mt_host_edit)

        self.local_mt_tokenizer_dir_edit = QLineEdit()
        self.local_mt_tokenizer_dir_edit.textChanged.connect(self._on_config_changed)
        form.addRow("Tokenizer 目录", self.local_mt_tokenizer_dir_edit)

        self.local_mt_gguf_path_edit = QLineEdit()
        self.local_mt_gguf_path_edit.textChanged.connect(self._on_config_changed)
        form.addRow("GGUF 文件", self.local_mt_gguf_path_edit)

        self.local_mt_max_new_tokens_spin = QSpinBox()
        self.local_mt_max_new_tokens_spin.setRange(64, 4096)
        self.local_mt_max_new_tokens_spin.valueChanged.connect(self._on_config_changed)
        form.addRow("max_new_tokens", self.local_mt_max_new_tokens_spin)

        self.local_mt_batch_size_spin = QSpinBox()
        self.local_mt_batch_size_spin.setRange(1, 8)
        self.local_mt_batch_size_spin.valueChanged.connect(self._on_config_changed)
        form.addRow("batch_size", self.local_mt_batch_size_spin)

        self.local_mt_temperature_spin = QDoubleSpinBox()
        self.local_mt_temperature_spin.setRange(0.0, 2.0)
        self.local_mt_temperature_spin.setDecimals(2)
        self.local_mt_temperature_spin.setSingleStep(0.1)
        self.local_mt_temperature_spin.valueChanged.connect(self._on_config_changed)
        form.addRow("temperature", self.local_mt_temperature_spin)

        self.local_mt_top_p_spin = QDoubleSpinBox()
        self.local_mt_top_p_spin.setRange(0.0, 1.0)
        self.local_mt_top_p_spin.setDecimals(2)
        self.local_mt_top_p_spin.setSingleStep(0.05)
        self.local_mt_top_p_spin.valueChanged.connect(self._on_config_changed)
        form.addRow("top_p", self.local_mt_top_p_spin)

        self.local_mt_top_k_spin = QSpinBox()
        self.local_mt_top_k_spin.setRange(1, 200)
        self.local_mt_top_k_spin.valueChanged.connect(self._on_config_changed)
        form.addRow("top_k", self.local_mt_top_k_spin)

        self.local_mt_repetition_penalty_spin = QDoubleSpinBox()
        self.local_mt_repetition_penalty_spin.setRange(1.0, 2.0)
        self.local_mt_repetition_penalty_spin.setDecimals(2)
        self.local_mt_repetition_penalty_spin.setSingleStep(0.05)
        self.local_mt_repetition_penalty_spin.valueChanged.connect(self._on_config_changed)
        form.addRow("repetition_penalty", self.local_mt_repetition_penalty_spin)
        return page

    def _build_performance_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self.fee_limit_spin = QDoubleSpinBox()
        self.fee_limit_spin.setRange(0.0, 9999.0)
        self.fee_limit_spin.setDecimals(2)
        self.fee_limit_spin.setSingleStep(0.5)
        self.fee_limit_spin.valueChanged.connect(self._on_config_changed)
        form.addRow("费用上限", self.fee_limit_spin)

        self.consumer_thread_spin = QSpinBox()
        self.consumer_thread_spin.setRange(1, 12)
        self.consumer_thread_spin.valueChanged.connect(self._on_config_changed)
        form.addRow("翻译线程数", self.consumer_thread_spin)
        return page

    def _build_advanced_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self.device_combo = QComboBox()
        self.device_combo.addItems(["cuda", "cpu"])
        self.device_combo.currentTextChanged.connect(self._on_config_changed)
        form.addRow("运行设备", self.device_combo)

        self.compute_type_combo = QComboBox()
        self.compute_type_combo.addItems(COMPUTE_TYPE_OPTIONS)
        self.compute_type_combo.currentTextChanged.connect(self._on_config_changed)
        form.addRow("计算精度", self.compute_type_combo)

        self.proxy_edit = QLineEdit()
        self.proxy_edit.textChanged.connect(self._on_config_changed)
        form.addRow("代理", self.proxy_edit)

        self.batch_size_spin = QSpinBox()
        self.batch_size_spin.setRange(1, 300)
        self.batch_size_spin.valueChanged.connect(self._on_config_changed)
        form.addRow("批处理时长（秒）", self.batch_size_spin)

        self.merge_length_spin = QSpinBox()
        self.merge_length_spin.setRange(1, 120)
        self.merge_length_spin.valueChanged.connect(self._on_config_changed)
        form.addRow("VAD 合并时长（秒）", self.merge_length_spin)

        self.use_itn_checkbox = QCheckBox("启用 ITN")
        self.use_itn_checkbox.toggled.connect(self._on_config_changed)
        form.addRow("", self.use_itn_checkbox)

        self.output_timestamp_checkbox = QCheckBox("输出时间戳")
        self.output_timestamp_checkbox.toggled.connect(self._on_config_changed)
        form.addRow("", self.output_timestamp_checkbox)

        self.max_single_segment_spin = QSpinBox()
        self.max_single_segment_spin.setRange(1000, 120000)
        self.max_single_segment_spin.setSingleStep(1000)
        self.max_single_segment_spin.valueChanged.connect(self._on_config_changed)
        form.addRow("单段最大时长（毫秒）", self.max_single_segment_spin)

        self.atten_limit_spin = QSpinBox()
        self.atten_limit_spin.setRange(0, 100)
        self.atten_limit_spin.valueChanged.connect(self._on_config_changed)
        form.addRow("响度限制（dB）", self.atten_limit_spin)
        return page

    def _build_step1_group(self) -> QWidget:
        group = QGroupBox("步骤 1 · 上传与任务参数")
        layout = QVBoxLayout(group)

        note = QLabel("选择一个根文件夹，系统会递归扫描其中所有音频文件，并把生成的 LRC 直接保存回源文件所在目录。")
        note.setWordWrap(True)
        layout.addWidget(note)

        root_row = QHBoxLayout()
        self.scan_root_dir_edit = QLineEdit()
        self.scan_root_dir_edit.textChanged.connect(self._on_scan_root_dir_changed)
        root_row.addWidget(self.scan_root_dir_edit, 1)

        self.browse_button = QPushButton("选择")
        self.browse_button.clicked.connect(self._choose_directory)
        root_row.addWidget(self.browse_button)

        self.scan_button = QPushButton("扫描")
        self.scan_button.clicked.connect(self.refresh_scan)
        root_row.addWidget(self.scan_button)
        layout.addLayout(root_row)

        self.scan_status_label = QLabel("请选择一个根文件夹，系统会递归处理其中所有音频文件。")
        self.scan_status_label.setWordWrap(True)
        layout.addWidget(self.scan_status_label)

        lang_row = QHBoxLayout()
        self.src_lang_combo = QComboBox()
        self.src_lang_combo.addItems(SRC_LANG_OPTIONS)
        self.src_lang_combo.currentTextChanged.connect(self._on_runtime_options_changed)
        lang_row.addWidget(self._wrap_labeled_widget("源语言", self.src_lang_combo))

        self.target_lang_edit = QLineEdit()
        self.target_lang_edit.textChanged.connect(self._on_runtime_options_changed)
        lang_row.addWidget(self._wrap_labeled_widget("目标语言", self.target_lang_edit))
        layout.addLayout(lang_row)

        mode_row = QHBoxLayout()
        self.skip_trans_checkbox = QCheckBox("仅转写")
        self.skip_trans_checkbox.toggled.connect(self._on_runtime_options_changed)
        mode_row.addWidget(self.skip_trans_checkbox)

        self.noise_suppress_checkbox = QCheckBox("降噪")
        self.noise_suppress_checkbox.toggled.connect(self._on_runtime_options_changed)
        mode_row.addWidget(self.noise_suppress_checkbox)

        self.bilingual_sub_checkbox = QCheckBox("双语字幕")
        self.bilingual_sub_checkbox.toggled.connect(self._on_runtime_options_changed)
        mode_row.addWidget(self.bilingual_sub_checkbox)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        self.task_table = QTableWidget(0, 3)
        self.task_table.setHorizontalHeaderLabels(["相对路径", "状态", "缓存目录"])
        self.task_table.horizontalHeader().setStretchLastSection(True)
        self.task_table.verticalHeader().setVisible(False)
        layout.addWidget(self.task_table)
        return group

    def _build_step2_group(self) -> QWidget:
        group = QGroupBox("步骤 2 · 任务摘要")
        layout = QVBoxLayout(group)

        note = QLabel("开始前先检查当前模式、模型、设备、费用和根目录；最终 LRC 会保存回各自源音频所在目录。")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.summary_grid = QGridLayout()
        self.summary_labels: list[tuple[QLabel, QLabel]] = []
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
        layout.addLayout(self.summary_grid)
        return group

    def _build_step3_group(self) -> QWidget:
        group = QGroupBox("步骤 3 · 翻译确认")
        layout = QVBoxLayout(group)

        self.confirmation_label = QLabel("ASR 和费用估算完成后，这里会显示翻译确认摘要。")
        self.confirmation_label.setWordWrap(True)
        layout.addWidget(self.confirmation_label)

        self.open_confirmation_button = QPushButton("打开翻译确认")
        self.open_confirmation_button.setEnabled(False)
        self.open_confirmation_button.clicked.connect(self._open_confirmation_dialog)
        layout.addWidget(self.open_confirmation_button)

        self.replan_label = QLabel("")
        self.replan_label.setWordWrap(True)
        layout.addWidget(self.replan_label)
        return group

    def _build_status_group(self) -> QWidget:
        group = QGroupBox("运行状态")
        layout = QVBoxLayout(group)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.stage_label = QLabel("等待开始...")
        self.stage_label.setWordWrap(True)
        layout.addWidget(self.stage_label)

        self.current_file_label = QLabel("当前文件：")
        self.current_file_label.setWordWrap(True)
        layout.addWidget(self.current_file_label)

        self.estimate_label = QLabel("费用估算：")
        self.estimate_label.setWordWrap(True)
        layout.addWidget(self.estimate_label)

        self.status_label = QLabel("处理开始后，这里会固定显示阶段进度、当前文件和实时日志。")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output, 1)

        button_row = QHBoxLayout()
        self.start_button = QPushButton("开始处理")
        self.start_button.clicked.connect(self._start_processing)
        button_row.addWidget(self.start_button)

        self.rescan_button = QPushButton("重新扫描")
        self.rescan_button.clicked.connect(self.refresh_scan)
        button_row.addWidget(self.rescan_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        return group

    def _wrap_labeled_widget(self, title: str, widget: QWidget) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(QLabel(title))
        layout.addWidget(widget)
        return wrapper

    def _load_config_to_widgets(self) -> None:
        self._loading_config = True
        self.translation_backend_combo.setCurrentText(self.config.translation_backend)
        self.asr_model_combo.setCurrentText(self.config.asr_model)
        self.endpoint_mode_combo.setCurrentText(self.config.endpoint_mode)
        self.relay_provider_combo.setCurrentText(self.config.relay_provider)
        self.relay_base_url_edit.setText(self.config.relay_base_url)
        self.relay_model_name_edit.setText(self.config.relay_model_name)
        self.remember_relay_key_checkbox.setChecked(self.config.remember_relay_api_key)
        self.relay_api_key_edit.setText(self.config.relay_api_key)
        self.openai_api_key_edit.setText(self.config.openai_api_key)
        self.anthropic_api_key_edit.setText(self.config.anthropic_api_key)
        self.google_api_key_edit.setText(self.config.google_api_key)
        self.openrouter_api_key_edit.setText(self.config.openrouter_api_key)
        self.chatbot_model_edit.setText(self.config.chatbot_model or "")
        self.local_mt_model_id_edit.setText(self.config.local_mt_model_id)
        self.local_mt_host_edit.setText(self.config.local_mt_host)
        self.local_mt_tokenizer_dir_edit.setText(self.config.local_mt_tokenizer_dir)
        self.local_mt_gguf_path_edit.setText(self.config.local_mt_gguf_path)
        self.local_mt_max_new_tokens_spin.setValue(self.config.local_mt_max_new_tokens)
        self.local_mt_batch_size_spin.setValue(self.config.local_mt_batch_size)
        self.local_mt_temperature_spin.setValue(self.config.local_mt_temperature)
        self.local_mt_top_p_spin.setValue(self.config.local_mt_top_p)
        self.local_mt_top_k_spin.setValue(self.config.local_mt_top_k)
        self.local_mt_repetition_penalty_spin.setValue(self.config.local_mt_repetition_penalty)
        self.fee_limit_spin.setValue(self.config.fee_limit)
        self.consumer_thread_spin.setValue(self.config.consumer_thread)
        self.device_combo.setCurrentText(self.config.device)
        self.compute_type_combo.setCurrentText(self.config.compute_type)
        self.proxy_edit.setText(self.config.proxy)
        self.batch_size_spin.setValue(self.config.batch_size_s)
        self.merge_length_spin.setValue(self.config.merge_length_s)
        self.use_itn_checkbox.setChecked(self.config.use_itn)
        self.output_timestamp_checkbox.setChecked(self.config.output_timestamp)
        self.max_single_segment_spin.setValue(self.config.max_single_segment_time)
        self.atten_limit_spin.setValue(self.config.atten_lim_db)
        self.scan_root_dir_edit.setText(self.config.scan_root_dir)
        self.src_lang_combo.setCurrentText(self.config.src_lang)
        self.target_lang_edit.setText(self.config.target_lang)
        self.skip_trans_checkbox.setChecked(self.config.skip_trans)
        self.noise_suppress_checkbox.setChecked(self.config.noise_suppress)
        self.bilingual_sub_checkbox.setChecked(self.config.bilingual_sub)
        self._apply_endpoint_mode()
        self.replan_label.setText(build_replan_text(self.config))
        self._loading_config = False

    def _collect_config_from_widgets(self) -> AppConfig:
        self.config.translation_backend = self.translation_backend_combo.currentText()
        self.config.asr_model = self.asr_model_combo.currentText()
        self.config.endpoint_mode = self.endpoint_mode_combo.currentText()
        if self.config.translation_backend == "中转 API":
            self.config.endpoint_mode = "中转平台"
        elif self.config.translation_backend == "官方 API":
            self.config.endpoint_mode = "官方 API"
        self.config.use_custom_translation_endpoint = self.config.endpoint_mode == "中转平台"
        self.config.relay_provider = self.relay_provider_combo.currentText()
        self.config.relay_base_url = self.relay_base_url_edit.text().strip()
        self.config.relay_model_name = self.relay_model_name_edit.text().strip()
        self.config.remember_relay_api_key = self.remember_relay_key_checkbox.isChecked()
        self.config.relay_api_key = self.relay_api_key_edit.text().strip()
        self.config.openai_api_key = self.openai_api_key_edit.text().strip()
        self.config.anthropic_api_key = self.anthropic_api_key_edit.text().strip()
        self.config.google_api_key = self.google_api_key_edit.text().strip()
        self.config.openrouter_api_key = self.openrouter_api_key_edit.text().strip()
        self.config.chatbot_model = self.chatbot_model_edit.text().strip() or None
        self.config.local_mt_model_id = self.local_mt_model_id_edit.text().strip()
        self.config.local_mt_host = self.local_mt_host_edit.text().strip()
        self.config.local_mt_tokenizer_dir = self.local_mt_tokenizer_dir_edit.text().strip()
        self.config.local_mt_gguf_path = self.local_mt_gguf_path_edit.text().strip()
        self.config.local_mt_max_new_tokens = self.local_mt_max_new_tokens_spin.value()
        self.config.local_mt_batch_size = self.local_mt_batch_size_spin.value()
        self.config.local_mt_temperature = self.local_mt_temperature_spin.value()
        self.config.local_mt_top_p = self.local_mt_top_p_spin.value()
        self.config.local_mt_top_k = self.local_mt_top_k_spin.value()
        self.config.local_mt_repetition_penalty = self.local_mt_repetition_penalty_spin.value()
        self.config.fee_limit = self.fee_limit_spin.value()
        self.config.consumer_thread = self.consumer_thread_spin.value()
        self.config.device = self.device_combo.currentText()
        self.config.compute_type = self.compute_type_combo.currentText()
        self.config.proxy = self.proxy_edit.text().strip()
        self.config.batch_size_s = self.batch_size_spin.value()
        self.config.merge_length_s = self.merge_length_spin.value()
        self.config.use_itn = self.use_itn_checkbox.isChecked()
        self.config.output_timestamp = self.output_timestamp_checkbox.isChecked()
        self.config.max_single_segment_time = self.max_single_segment_spin.value()
        self.config.atten_lim_db = self.atten_limit_spin.value()
        self.config.scan_root_dir = self.scan_root_dir_edit.text().strip()
        self.config.src_lang = self.src_lang_combo.currentText()
        self.config.target_lang = self.target_lang_edit.text().strip()
        self.config.skip_trans = self.skip_trans_checkbox.isChecked()
        self.config.noise_suppress = self.noise_suppress_checkbox.isChecked()
        self.config.bilingual_sub = self.bilingual_sub_checkbox.isChecked()
        return self.config

    def _apply_endpoint_mode(self) -> None:
        backend = self.translation_backend_combo.currentText()
        relay_enabled = backend == "中转 API"
        official_enabled = backend == "官方 API"
        local_enabled = backend == "本地 HY-MT"

        self.endpoint_mode_combo.setEnabled(backend in ["官方 API", "中转 API"])
        for widget in [
            self.relay_provider_combo,
            self.relay_base_url_edit,
            self.relay_model_name_edit,
            self.remember_relay_key_checkbox,
            self.relay_api_key_edit,
        ]:
            widget.setEnabled(relay_enabled)

        for widget in [
            self.openai_api_key_edit,
            self.anthropic_api_key_edit,
            self.google_api_key_edit,
            self.openrouter_api_key_edit,
            self.chatbot_model_edit,
        ]:
            widget.setEnabled(official_enabled)

        for widget in [
            self.local_mt_model_id_edit,
            self.local_mt_host_edit,
            self.local_mt_tokenizer_dir_edit,
            self.local_mt_gguf_path_edit,
            self.local_mt_max_new_tokens_spin,
            self.local_mt_batch_size_spin,
            self.local_mt_temperature_spin,
            self.local_mt_top_p_spin,
            self.local_mt_top_k_spin,
            self.local_mt_repetition_penalty_spin,
        ]:
            widget.setEnabled(local_enabled)

    def _set_task_table_rows(self) -> None:
        self.task_table.setRowCount(len(self.scan_result.tasks))
        for row, task in enumerate(self.scan_result.tasks):
            self.task_table.setItem(row, 0, QTableWidgetItem(str(task.relative_path)))
            self.task_table.setItem(row, 1, QTableWidgetItem(task.status if task.cache_valid else "需转写"))
            self.task_table.setItem(row, 2, QTableWidgetItem(str(task.cache_dir)))
        self.task_table.resizeColumnsToContents()

    def _update_summary(self) -> None:
        items = build_summary_items(self._collect_config_from_widgets(), self.scan_result)
        for pair, item in zip(self.summary_labels, items):
            pair[0].setText(item.label)
            pair[1].setText(item.value)

    def _append_log(self, message: str) -> None:
        self.log_output.appendPlainText(message)

    def _persist_and_refresh(self) -> None:
        if self._loading_config:
            return
        self._collect_config_from_widgets()
        save_config(self.config)
        self._apply_endpoint_mode()
        self._update_summary()
        self.replan_label.setText(build_replan_text(self.config))

    def _on_config_changed(self) -> None:
        self._persist_and_refresh()

    def _on_endpoint_mode_changed(self) -> None:
        self._persist_and_refresh()

    def _on_runtime_options_changed(self) -> None:
        self._persist_and_refresh()
        self._update_summary()

    def _on_scan_root_dir_changed(self) -> None:
        self._persist_and_refresh()

    def _choose_directory(self) -> None:
        current_dir = self.scan_root_dir_edit.text().strip() or str(Path.home())
        selected_dir = QFileDialog.getExistingDirectory(self, "选择根文件夹", current_dir)
        if selected_dir:
            self.scan_root_dir_edit.setText(selected_dir)
            self.refresh_scan()

    def refresh_scan(self) -> None:
        self._collect_config_from_widgets()
        self.scan_result = scan_root_directory(self.config.scan_root_dir)
        if self.scan_result.error:
            self.scan_status_label.setText(self.scan_result.error)
            self._append_log(self.scan_result.error)
        elif self.scan_result.tasks:
            self.scan_status_label.setText(f"共发现 {len(self.scan_result.tasks)} 个音频文件。{cache_summary(self.scan_result.tasks)}。")
            self._append_log(
                f"扫描完成：{self.scan_result.root_dir}，发现 {len(self.scan_result.tasks)} 个音频文件，{cache_summary(self.scan_result.tasks)}。"
            )
        else:
            self.scan_status_label.setText("请选择一个根文件夹，系统会递归处理其中所有音频文件。")
        self._set_task_table_rows()
        self._update_summary()

    def _set_running_state(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.scan_button.setEnabled(not running)
        self.browse_button.setEnabled(not running)
        self.rescan_button.setEnabled(not running)
        self.open_confirmation_button.setEnabled(bool(self.pending_confirmation_state) and not running)

    def _reset_progress(self) -> None:
        self.progress_bar.setValue(0)
        self.stage_label.setText("等待开始...")
        self.current_file_label.setText("当前文件：")
        self.estimate_label.setText("费用估算：")
        self.status_label.setText("处理开始后，这里会固定显示阶段进度、当前文件和实时日志。")

    def _start_processing(self) -> None:
        if self.worker_thread is not None:
            QMessageBox.information(self, "处理中", "当前已有任务在运行，请等待完成。")
            return

        self._collect_config_from_widgets()
        errors = validate_before_processing(self.config, self.scan_result)
        if errors:
            QMessageBox.critical(self, "参数错误", "\n".join(errors))
            return

        self.pending_confirmation_state = None
        self.auto_open_confirmation_requested = False
        self.open_confirmation_button.setEnabled(False)
        self.confirmation_label.setText("正在进行 ASR 与费用估算...")
        self.log_output.clear()
        self._reset_progress()
        self.status_label.setText("已收到处理请求，正在检查参数并启动后台任务...")
        self._start_worker(mode="prepare")

    def _start_worker(
        self,
        *,
        mode: str,
        confirmation_state: dict | None = None,
        selected_relative_paths: list[str] | None = None,
    ) -> None:
        worker_config = AppConfig.from_dict(self.config.to_dict())
        self.worker_thread = QThread(self)
        self.worker = ProcessWorker(
            worker_config,
            mode=mode,
            confirmation_state=confirmation_state,
            selected_relative_paths=selected_relative_paths,
        )
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress_changed.connect(self._on_progress_changed)
        self.worker.stage_changed.connect(self._on_stage_changed)
        self.worker.current_file_changed.connect(self._on_current_file_changed)
        self.worker.estimate_changed.connect(self._on_estimate_changed)
        self.worker.log_line.connect(self._append_log)
        self.worker.confirmation_ready.connect(self._on_confirmation_ready)
        self.worker.completed.connect(self._on_worker_completed)
        self.worker.failed.connect(self._on_worker_failed)
        self.worker.done.connect(self.worker_thread.quit)
        self.worker.done.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(self._on_worker_thread_finished)
        self._set_running_state(True)
        self.worker_thread.start()

    def _on_progress_changed(self, value: int, text: str) -> None:
        self.progress_bar.setValue(value)
        self.status_label.setText(text)

    def _on_stage_changed(self, text: str) -> None:
        self.stage_label.setText(text)

    def _on_current_file_changed(self, text: str) -> None:
        self.current_file_label.setText(text)

    def _on_estimate_changed(self, text: str) -> None:
        self.estimate_label.setText(text)

    def _on_confirmation_ready(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        self.pending_confirmation_state = data.get("state")
        self.last_log_path = data.get("log_path")
        if not self.pending_confirmation_state:
            return
        self.auto_open_confirmation_requested = True
        state = self.pending_confirmation_state
        self.confirmation_label.setText(
            f"待确认文件：{len(state.get('entries', []))} 个 | "
            f"保底估算 ${float(state.get('total_floor_fee', 0.0)):.4f} | "
            f"建议预留 ${float(state.get('total_likely_fee', 0.0)):.4f}"
        )
        self.open_confirmation_button.setEnabled(False)
        self.status_label.setText("ASR 和费用估算已完成，等待翻译确认。")

    def _open_confirmation_dialog(self, auto_open: bool = False) -> None:
        if not self.pending_confirmation_state:
            if not auto_open:
                QMessageBox.information(self, "无待确认任务", "当前没有待确认的翻译任务。")
            return

        dialog = ConfirmationDialog(self.pending_confirmation_state, self)
        if dialog.exec() != 1:
            self.confirmation_label.setText("翻译确认已取消，可稍后再次打开确认窗口继续。")
            self.open_confirmation_button.setEnabled(True)
            self.auto_open_confirmation_requested = False
            return

        selected_relative_paths = dialog.selected_relative_paths()
        self.auto_open_confirmation_requested = False
        self.confirmation_label.setText(f"已确认翻译 {len(selected_relative_paths)} 个文件，正在启动翻译任务...")
        self.status_label.setText("已收到翻译确认，正在启动翻译任务...")
        self._start_worker(
            mode="translate",
            confirmation_state=self.pending_confirmation_state,
            selected_relative_paths=selected_relative_paths,
        )

    def _on_worker_completed(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        generated_files = data.get("generated_files", [])
        self.last_log_path = data.get("log_path")
        self.pending_confirmation_state = data.get("remaining_confirmation_state")
        self.open_confirmation_button.setEnabled(bool(self.pending_confirmation_state))

        if self.pending_confirmation_state:
            state = self.pending_confirmation_state
            self.confirmation_label.setText(
                f"剩余待确认文件：{len(state.get('entries', []))} 个 | "
                f"保底估算 ${float(state.get('total_floor_fee', 0.0)):.4f} | "
                f"建议预留 ${float(state.get('total_likely_fee', 0.0)):.4f}"
            )
        else:
            self.confirmation_label.setText("当前没有待确认的翻译任务。")
        self.auto_open_confirmation_requested = False

        self.status_label.setText(f"处理完成，共生成 {len(generated_files)} 个文件。")
        self._append_log(f"处理完成，共生成 {len(generated_files)} 个文件。")
        for path in generated_files:
            self._append_log(f"输出文件：{path}")
        self.refresh_scan()
        QMessageBox.information(self, "处理完成", f"处理完成，共生成 {len(generated_files)} 个文件。")

    def _on_worker_failed(self, message: str, tb: str) -> None:
        self.status_label.setText(f"处理失败：{message}")
        self._append_log(f"处理失败：{message}")
        self._append_log(tb)
        QMessageBox.critical(self, "处理失败", message)

    def _on_worker_thread_finished(self) -> None:
        self.worker = None
        self.worker_thread = None
        self._set_running_state(False)
        if self.pending_confirmation_state and self.auto_open_confirmation_requested:
            self._open_confirmation_dialog(auto_open=True)

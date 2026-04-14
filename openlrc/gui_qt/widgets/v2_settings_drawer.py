from __future__ import annotations

from collections import OrderedDict

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QLineEdit,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
)

from ..models import (
    ASR_MODEL_OPTIONS,
    COMPUTE_TYPE_OPTIONS,
    ENDPOINT_MODE_OPTIONS,
    RELAY_PROVIDER_OPTIONS,
    TRANSLATION_BACKEND_OPTIONS,
)
from .fluid_card import FluidAccordionCard


class V2SettingsDrawer(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsPane")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.fields: OrderedDict[str, object] = OrderedDict()
        self.cards: list[FluidAccordionCard] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 38)
        layout.setSpacing(18)

        self.card_asr = FluidAccordionCard("ASR", "SenseVoice")
        self.card_translation = FluidAccordionCard("翻译", "本地 HY-MT")
        self.card_perf = FluidAccordionCard("费用与性能", "线程与上限")
        self.card_adv = FluidAccordionCard("输出与高级", "CUDA")
        self.cards = [self.card_asr, self.card_translation, self.card_perf, self.card_adv]

        asr_layout = QFormLayout()
        self._add_combo(asr_layout, "asr_model", "SenseVoice 模型", ASR_MODEL_OPTIONS)
        self.card_asr.set_content_layout(asr_layout)
        layout.addWidget(self.card_asr)

        translation_layout = QFormLayout()
        self._add_combo(translation_layout, "translation_backend", "翻译模式", TRANSLATION_BACKEND_OPTIONS)
        self._add_combo(translation_layout, "endpoint_mode", "接口模式", ENDPOINT_MODE_OPTIONS)
        self._add_combo(translation_layout, "relay_provider", "中转提供商", RELAY_PROVIDER_OPTIONS)
        self._add_line_edit(translation_layout, "relay_base_url", "Base URL")
        self._add_line_edit(translation_layout, "relay_model_name", "中转模型名")
        self._add_checkbox(translation_layout, "remember_relay_api_key", "记住中转 API Key")
        self._add_line_edit(translation_layout, "relay_api_key", "中转 API Key", password=True)
        self._add_line_edit(translation_layout, "openai_api_key", "OpenAI API Key", password=True)
        self._add_line_edit(translation_layout, "anthropic_api_key", "Anthropic API Key", password=True)
        self._add_line_edit(translation_layout, "google_api_key", "Google API Key", password=True)
        self._add_line_edit(translation_layout, "openrouter_api_key", "OpenRouter API Key", password=True)
        self._add_line_edit(translation_layout, "chatbot_model", "官方模型名")
        self._add_line_edit(translation_layout, "local_mt_model_id", "Ollama 模型名")
        self._add_line_edit(translation_layout, "local_mt_host", "Ollama 地址")
        self._add_line_edit(translation_layout, "local_mt_tokenizer_dir", "Tokenizer 目录")
        self._add_line_edit(translation_layout, "local_mt_gguf_path", "GGUF 文件")
        self._add_spin(translation_layout, "local_mt_max_new_tokens", "max_new_tokens", 64, 4096)
        self._add_spin(translation_layout, "local_mt_batch_size", "batch_size", 1, 8)
        self._add_double_spin(translation_layout, "local_mt_temperature", "temperature", 0.0, 2.0, 2, 0.1)
        self._add_double_spin(translation_layout, "local_mt_top_p", "top_p", 0.0, 1.0, 2, 0.05)
        self._add_spin(translation_layout, "local_mt_top_k", "top_k", 1, 200)
        self._add_double_spin(translation_layout, "local_mt_repetition_penalty", "repetition_penalty", 1.0, 2.0, 2, 0.05)
        self.card_translation.set_content_layout(translation_layout)
        layout.addWidget(self.card_translation)

        perf_layout = QFormLayout()
        self._add_double_spin(perf_layout, "fee_limit", "费用上限", 0.0, 9999.0, 2, 0.5)
        self._add_spin(perf_layout, "consumer_thread", "翻译线程数", 1, 12)
        self.card_perf.set_content_layout(perf_layout)
        layout.addWidget(self.card_perf)

        adv_layout = QFormLayout()
        self._add_combo(adv_layout, "device", "运行设备", ["cuda", "cpu"])
        self._add_combo(adv_layout, "compute_type", "计算精度", COMPUTE_TYPE_OPTIONS)
        self._add_line_edit(adv_layout, "proxy", "代理")
        self._add_spin(adv_layout, "batch_size_s", "批处理时长（秒）", 1, 300)
        self._add_spin(adv_layout, "merge_length_s", "VAD 合并时长（秒）", 1, 120)
        self._add_checkbox(adv_layout, "use_itn", "启用 ITN")
        self._add_checkbox(adv_layout, "output_timestamp", "输出时间戳")
        self._add_spin(adv_layout, "max_single_segment_time", "单段最大时长（毫秒）", 1000, 120000, 1000)
        self._add_spin(adv_layout, "atten_lim_db", "响度限制（dB）", 0, 100)
        self.card_adv.set_content_layout(adv_layout)
        layout.addWidget(self.card_adv)

        self.card_asr.expand()
        layout.addStretch()

    def _add_combo(self, layout: QFormLayout, key: str, label: str, options: list[str]) -> None:
        widget = QComboBox()
        widget.addItems(options)
        layout.addRow(label, widget)
        self.fields[key] = widget

    def _add_line_edit(self, layout: QFormLayout, key: str, label: str, password: bool = False) -> None:
        widget = QLineEdit()
        if password:
            widget.setEchoMode(QLineEdit.Password)
        layout.addRow(label, widget)
        self.fields[key] = widget

    def _add_checkbox(self, layout: QFormLayout, key: str, label: str) -> None:
        widget = QCheckBox(label)
        layout.addRow("", widget)
        self.fields[key] = widget

    def _add_spin(self, layout: QFormLayout, key: str, label: str, minimum: int, maximum: int, step: int = 1) -> None:
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        widget.setSingleStep(step)
        layout.addRow(label, widget)
        self.fields[key] = widget

    def _add_double_spin(
        self,
        layout: QFormLayout,
        key: str,
        label: str,
        minimum: float,
        maximum: float,
        decimals: int,
        step: float,
    ) -> None:
        widget = QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        widget.setDecimals(decimals)
        widget.setSingleStep(step)
        layout.addRow(label, widget)
        self.fields[key] = widget

    def bind_change_handlers(self, callback, mode_callback) -> None:
        for key, widget in self.fields.items():
            if isinstance(widget, QComboBox):
                if key in {"translation_backend", "endpoint_mode"}:
                    widget.currentTextChanged.connect(mode_callback)
                else:
                    widget.currentTextChanged.connect(callback)
            elif isinstance(widget, QLineEdit):
                widget.textChanged.connect(callback)
            elif isinstance(widget, QCheckBox):
                widget.toggled.connect(callback)
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                widget.valueChanged.connect(callback)

    def bind_card_state_handlers(self, callback) -> None:
        for key, card in self.card_map().items():
            card.expansion_changed.connect(lambda expanded, k=key: callback(k, expanded))

    def card_map(self) -> OrderedDict[str, FluidAccordionCard]:
        return OrderedDict(
            [
                ("asr", self.card_asr),
                ("translation", self.card_translation),
                ("performance", self.card_perf),
                ("advanced", self.card_adv),
            ]
        )

    def load_config(self, config) -> None:
        for key, widget in self.fields.items():
            value = getattr(config, key)
            if isinstance(widget, QComboBox):
                widget.setCurrentText(str(value))
            elif isinstance(widget, QLineEdit):
                widget.setText("" if value is None else str(value))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QSpinBox):
                widget.setValue(int(value))
            elif isinstance(widget, QDoubleSpinBox):
                widget.setValue(float(value))

    def collect_into(self, config) -> None:
        for key, widget in self.fields.items():
            if isinstance(widget, QComboBox):
                value = widget.currentText()
            elif isinstance(widget, QLineEdit):
                text = widget.text().strip()
                value = text or None if key == "chatbot_model" else text
            elif isinstance(widget, QCheckBox):
                value = widget.isChecked()
            elif isinstance(widget, QSpinBox):
                value = widget.value()
            elif isinstance(widget, QDoubleSpinBox):
                value = widget.value()
            else:
                continue
            setattr(config, key, value)

    def apply_backend_state(self, backend: str) -> None:
        relay_enabled = backend == "中转 API"
        official_enabled = backend == "官方 API"
        local_enabled = backend == "本地 HY-MT"

        self.fields["endpoint_mode"].setEnabled(backend in {"官方 API", "中转 API"})
        for key in ["relay_provider", "relay_base_url", "relay_model_name", "remember_relay_api_key", "relay_api_key"]:
            self.fields[key].setEnabled(relay_enabled)
        for key in ["openai_api_key", "anthropic_api_key", "google_api_key", "openrouter_api_key", "chatbot_model"]:
            self.fields[key].setEnabled(official_enabled)
        for key in [
            "local_mt_model_id",
            "local_mt_host",
            "local_mt_tokenizer_dir",
            "local_mt_gguf_path",
            "local_mt_max_new_tokens",
            "local_mt_batch_size",
            "local_mt_temperature",
            "local_mt_top_p",
            "local_mt_top_k",
            "local_mt_repetition_penalty",
        ]:
            self.fields[key].setEnabled(local_enabled)

    def apply_card_state(self, card_state: dict[str, bool]) -> None:
        for key, card in self.card_map().items():
            should_expand = bool(card_state.get(key, False))
            if should_expand:
                card.expand()
            else:
                card.collapse()

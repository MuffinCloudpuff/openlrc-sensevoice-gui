from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from openlrc.directory_workflow import DirectoryTask

GUI_CONFIG_PATH = Path(__file__).resolve().parents[2] / ".openlrc_gui_config.json"
PROJECT_ROOT = GUI_CONFIG_PATH.parent

ASR_MODEL_OPTIONS = ["small", "large", "iic/SenseVoiceSmall", "iic/SenseVoiceLarge"]
COMPUTE_TYPE_OPTIONS = ["int8", "int8_float16", "int16", "float16", "float32"]
RELAY_PROVIDER_OPTIONS = ["OpenAI 兼容", "Anthropic 兼容"]
ENDPOINT_MODE_OPTIONS = ["中转平台", "官方 API"]
TRANSLATION_BACKEND_OPTIONS = ["官方 API", "中转 API", "本地 HY-MT"]
SRC_LANG_OPTIONS = [
    "自动检测",
    "ca",
    "zh",
    "hr",
    "da",
    "nl",
    "en",
    "fi",
    "fr",
    "de",
    "el",
    "it",
    "ja",
    "ko",
    "lt",
    "mk",
    "nb",
    "pl",
    "pt",
    "ro",
    "ru",
    "sl",
    "es",
    "sv",
    "uk",
]


def detect_local_hymt_tokenizer_dir() -> str:
    candidate_dirs = [
        PROJECT_ROOT / "HY-MT1.5-1.8B-GPTQ-Int4",
        PROJECT_ROOT / "models" / "hy-mt" / "HY-MT1.5-1.8B-GPTQ-Int4",
    ]
    for candidate in candidate_dirs:
        if (candidate / "tokenizer_config.json").exists():
            return str(candidate)
    return ""


def detect_local_hymt_gguf_path() -> str:
    candidate_files = [
        PROJECT_ROOT / "models" / "hy-mt-gguf" / "HY-MT1.5-1.8B-Q4_K_M.gguf",
        PROJECT_ROOT / "HY-MT1.5-1.8B-Q4_K_M.gguf",
    ]
    for candidate in candidate_files:
        if candidate.exists():
            return str(candidate)
    return ""


def _existing_dir_or_detect(path_text: str, detector) -> str:
    path = Path(path_text).expanduser() if path_text else None
    if path and path.exists() and path.is_dir():
        return str(path)
    detected = detector()
    return detected or str(path_text or "")


def _existing_file_or_detect(path_text: str, detector) -> str:
    path = Path(path_text).expanduser() if path_text else None
    if path and path.exists() and path.is_file():
        return str(path)
    detected = detector()
    return detected or str(path_text or "")


def default_local_mt_model_name() -> str:
    return "hy-mt-q4km"


def default_local_mt_host() -> str:
    return "http://127.0.0.1:11434"


@dataclass(slots=True)
class AppConfig:
    asr_model: str = "small"
    device: str = "cuda"
    compute_type: str = "float16"
    proxy: str = ""
    scan_root_dir: str = ""
    translation_backend: str = "中转 API"
    use_custom_translation_endpoint: bool = True
    endpoint_mode: str = "中转平台"
    relay_provider: str = "OpenAI 兼容"
    relay_base_url: str = ""
    relay_model_name: str = ""
    remember_relay_api_key: bool = False
    relay_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""
    openrouter_api_key: str = ""
    local_mt_model_id: str = field(default_factory=default_local_mt_model_name)
    local_mt_host: str = field(default_factory=default_local_mt_host)
    local_mt_tokenizer_dir: str = field(default_factory=detect_local_hymt_tokenizer_dir)
    local_mt_gguf_path: str = field(default_factory=detect_local_hymt_gguf_path)
    local_mt_max_new_tokens: int = 512
    local_mt_batch_size: int = 3
    local_mt_temperature: float = 0.7
    local_mt_top_p: float = 0.6
    local_mt_top_k: int = 20
    local_mt_repetition_penalty: float = 1.05
    fee_limit: float = 10.0
    consumer_thread: int = 6
    chatbot_model: str | None = None
    batch_size_s: int = 60
    merge_length_s: int = 15
    use_itn: bool = True
    output_timestamp: bool = True
    max_single_segment_time: int = 30000
    atten_lim_db: int = 15
    src_lang: str = "自动检测"
    target_lang: str = "zh-cn"
    skip_trans: bool = False
    noise_suppress: bool = False
    bilingual_sub: bool = False

    @classmethod
    def from_dict(cls, payload: dict) -> AppConfig:
        config = cls()
        for field_name in cls.__dataclass_fields__:
            if field_name in payload:
                setattr(config, field_name, payload[field_name])

        if "endpoint_mode" not in payload:
            config.endpoint_mode = "中转平台" if config.use_custom_translation_endpoint else "官方 API"
        config.use_custom_translation_endpoint = config.endpoint_mode == "中转平台"
        if "translation_backend" not in payload or not str(payload.get("translation_backend") or "").strip():
            config.translation_backend = "中转 API" if config.endpoint_mode == "中转平台" else "官方 API"
        if payload.get("local_mt_model_id") and str(payload.get("local_mt_model_id")).lower().endswith(".gguf"):
            config.local_mt_gguf_path = str(payload.get("local_mt_model_id"))
            config.local_mt_model_id = default_local_mt_model_name()
        elif payload.get("local_mt_model_id") and Path(str(payload.get("local_mt_model_id"))).is_dir():
            config.local_mt_tokenizer_dir = str(payload.get("local_mt_model_id"))
            config.local_mt_model_id = default_local_mt_model_name()
        if not config.local_mt_model_id:
            config.local_mt_model_id = default_local_mt_model_name()
        if not config.local_mt_host:
            config.local_mt_host = default_local_mt_host()
        config.local_mt_tokenizer_dir = _existing_dir_or_detect(
            config.local_mt_tokenizer_dir, detect_local_hymt_tokenizer_dir
        )
        config.local_mt_gguf_path = _existing_file_or_detect(config.local_mt_gguf_path, detect_local_hymt_gguf_path)
        return config

    def to_dict(self) -> dict:
        self.use_custom_translation_endpoint = self.endpoint_mode == "中转平台"
        return {
            "asr_model": self.asr_model,
            "device": self.device,
            "compute_type": self.compute_type,
            "proxy": self.proxy,
            "scan_root_dir": self.scan_root_dir,
            "translation_backend": self.translation_backend,
            "use_custom_translation_endpoint": self.use_custom_translation_endpoint,
            "endpoint_mode": self.endpoint_mode,
            "relay_provider": self.relay_provider,
            "relay_base_url": self.relay_base_url,
            "relay_model_name": self.relay_model_name,
            "remember_relay_api_key": self.remember_relay_api_key,
            "relay_api_key": self.relay_api_key if self.remember_relay_api_key else "",
            "openai_api_key": self.openai_api_key,
            "anthropic_api_key": self.anthropic_api_key,
            "google_api_key": self.google_api_key,
            "openrouter_api_key": self.openrouter_api_key,
            "local_mt_model_id": self.local_mt_model_id,
            "local_mt_host": self.local_mt_host,
            "local_mt_tokenizer_dir": self.local_mt_tokenizer_dir,
            "local_mt_gguf_path": self.local_mt_gguf_path,
            "local_mt_max_new_tokens": self.local_mt_max_new_tokens,
            "local_mt_batch_size": self.local_mt_batch_size,
            "local_mt_temperature": self.local_mt_temperature,
            "local_mt_top_p": self.local_mt_top_p,
            "local_mt_top_k": self.local_mt_top_k,
            "local_mt_repetition_penalty": self.local_mt_repetition_penalty,
            "fee_limit": self.fee_limit,
            "consumer_thread": self.consumer_thread,
            "chatbot_model": self.chatbot_model,
            "batch_size_s": self.batch_size_s,
            "merge_length_s": self.merge_length_s,
            "use_itn": self.use_itn,
            "output_timestamp": self.output_timestamp,
            "max_single_segment_time": self.max_single_segment_time,
            "atten_lim_db": self.atten_lim_db,
            "src_lang": self.src_lang,
            "target_lang": self.target_lang,
            "skip_trans": self.skip_trans,
            "noise_suppress": self.noise_suppress,
            "bilingual_sub": self.bilingual_sub,
        }


@dataclass(slots=True)
class SummaryItem:
    label: str
    value: str


@dataclass(slots=True)
class ScanResult:
    root_dir: Path | None = None
    tasks: list[DirectoryTask] = field(default_factory=list)
    error: str = ""

    @property
    def audio_count(self) -> int:
        return len(self.tasks)

    @property
    def relative_paths(self) -> list[str]:
        return [str(task.relative_path) for task in self.tasks]


@dataclass(slots=True)
class ReplanStep:
    step: str
    duration_label: str

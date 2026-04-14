from __future__ import annotations

from ...models import AppConfig, ReplanStep
from .base import TranslationProvider
from .local_hymt_runtime import detect_ollama_exe, ensure_ollama_available


class LocalHYMTProvider(TranslationProvider):
    backend_key = "local_hymt"
    label = "本地 HY-MT"
    module_file = "openlrc/gui_qt/translation/providers/local_hymt.py"
    estimated_duration = "首次创建模型约 1-3 分钟，后续按本机算力决定"

    def validate(self, config: AppConfig) -> list[str]:
        if config.skip_trans:
            return []
        errors: list[str] = []
        if not config.local_mt_model_id.strip():
            errors.append("本地 HY-MT 模式下必须填写 Ollama 模型名。")
        if not config.local_mt_host.strip():
            errors.append("本地 HY-MT 模式下必须填写 Ollama 地址。")
        if not config.local_mt_gguf_path.strip():
            errors.append("本地 HY-MT 模式下必须填写 GGUF 文件路径。")
        if not config.local_mt_tokenizer_dir.strip():
            errors.append("本地 HY-MT 模式下必须填写 tokenizer 目录。")
        if not detect_ollama_exe():
            errors.append("未找到 Ollama 可执行文件。")
        else:
            try:
                ensure_ollama_available(config)
            except RuntimeError as exc:
                errors.append(str(exc))
        return errors

    def summary(self, config: AppConfig) -> str:
        return f"HY-MT / Ollama:{config.local_mt_model_id.strip()}"

    def build_replan(self, config: AppConfig) -> list[ReplanStep]:
        return [
            ReplanStep("加载本地 HY-MT 模块配置", "10 秒"),
            ReplanStep("执行 ASR 与零费用估算", "按音频长度"),
            ReplanStep("检查或创建 Ollama 本地模型", self.estimated_duration),
            ReplanStep("通过 Ollama 执行本地翻译并导出字幕", "按显卡/CPU性能决定"),
        ]

from __future__ import annotations

from ...models import AppConfig, ReplanStep
from .base import TranslationProvider


class OfficialApiProvider(TranslationProvider):
    backend_key = "official_api"
    label = "官方 API"
    module_file = "openlrc/gui_qt/translation/providers/official_api.py"
    estimated_duration = "约 1-3 分钟（不含模型响应波动）"

    def validate(self, config: AppConfig) -> list[str]:
        if config.skip_trans:
            return []
        keys = [
            config.openai_api_key.strip(),
            config.anthropic_api_key.strip(),
            config.google_api_key.strip(),
            config.openrouter_api_key.strip(),
        ]
        return [] if any(keys) else ["当前启用了翻译，但官方 API 模式下没有设置任何 API Key。"]

    def summary(self, config: AppConfig) -> str:
        return str(config.chatbot_model or "未设置")

    def build_replan(self, config: AppConfig) -> list[ReplanStep]:
        return [
            ReplanStep("加载官方 API 模式参数", "10 秒"),
            ReplanStep("执行 ASR 与费用估算", "按音频长度"),
            ReplanStep("等待人工确认后调用官方 API 翻译", self.estimated_duration),
        ]

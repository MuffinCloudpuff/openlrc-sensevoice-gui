from __future__ import annotations

from ...models import AppConfig, ReplanStep
from .base import TranslationProvider


class RelayApiProvider(TranslationProvider):
    backend_key = "relay_api"
    label = "中转 API"
    module_file = "openlrc/gui_qt/translation/providers/relay_api.py"
    estimated_duration = "约 1-3 分钟（取决于中转平台和上游模型）"

    def validate(self, config: AppConfig) -> list[str]:
        if config.skip_trans:
            return []
        errors: list[str] = []
        if not config.relay_base_url.strip() or not config.relay_model_name.strip():
            errors.append("启用了中转 API 模式时，必须填写模型名和 Base URL。")
        relay_or_fallback_keys = [
            config.relay_api_key.strip(),
            config.openai_api_key.strip(),
            config.anthropic_api_key.strip(),
            config.openrouter_api_key.strip(),
        ]
        if not any(relay_or_fallback_keys):
            errors.append("当前启用了翻译，但中转 API 模式下没有设置可用凭证。")
        return errors

    def summary(self, config: AppConfig) -> str:
        return f"{config.relay_provider} / {config.relay_model_name.strip() or '未填写'}"

    def build_replan(self, config: AppConfig) -> list[ReplanStep]:
        return [
            ReplanStep("加载中转 API 模式参数", "10 秒"),
            ReplanStep("执行 ASR 与费用估算", "按音频长度"),
            ReplanStep("等待人工确认后调用中转模型翻译", self.estimated_duration),
        ]

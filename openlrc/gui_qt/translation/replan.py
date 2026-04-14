from __future__ import annotations

from ..models import AppConfig
from .registry import get_provider_by_label


def build_replan_text(config: AppConfig) -> str:
    provider = get_provider_by_label(config.translation_backend)
    steps = provider.build_replan(config)
    lines = [
        f"当前模块：{provider.label}",
        f"模块文件：{provider.module_file}",
        f"预计时长：{provider.estimated_duration}",
    ]
    for index, step in enumerate(steps, start=1):
        lines.append(f"{index}. {step.step}（{step.duration_label}）")
    return "\n".join(lines)

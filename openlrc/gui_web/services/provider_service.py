from __future__ import annotations

from ...gui_qt.models import AppConfig
from ...gui_qt.translation.providers.local_hymt_runtime import translate_lines_with_hymt
from ...gui_qt.translation.registry import TRANSLATION_PROVIDERS, get_provider_by_label
from ...gui_qt.translation.replan import build_replan_text


def list_provider_payloads(config: AppConfig) -> list[dict]:
    payloads: list[dict] = []
    for provider in TRANSLATION_PROVIDERS:
        is_active = provider.label == config.translation_backend
        errors: list[str] = []
        if is_active:
            try:
                errors = provider.validate(config)
            except Exception as exc:
                errors = [str(exc)]
        payloads.append(
            {
                "backend_key": provider.backend_key,
                "label": provider.label,
                "module_file": provider.module_file,
                "estimated_duration": provider.estimated_duration,
                "summary": provider.summary(config),
                "active": is_active,
                "validation_errors": errors,
                "replan_text": build_replan_text(config) if is_active else "",
                "replan_steps": [
                    {"step": step.step, "duration_label": step.duration_label}
                    for step in provider.build_replan(config)
                ] if is_active else [],
            }
        )
    return payloads


def validate_provider_selection(config: AppConfig) -> list[str]:
    try:
        provider = get_provider_by_label(config.translation_backend)
    except KeyError:
        return [f"未知翻译模式：{config.translation_backend}"]
    return provider.validate(config)


def test_local_hymt_translation(config: AppConfig, sample_text: str) -> dict:
    translations = translate_lines_with_hymt([sample_text], None, config.target_lang or "zh-cn", config)
    return {
        "ok": True,
        "model_id": config.local_mt_model_id,
        "host": config.local_mt_host,
        "translated_text": translations[0] if translations else "",
    }

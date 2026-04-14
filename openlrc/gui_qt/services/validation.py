from __future__ import annotations

from ..models import AppConfig, ScanResult
from ..translation.registry import get_provider_by_label


def validate_before_processing(config: AppConfig, scan_result: ScanResult) -> list[str]:
    errors: list[str] = []
    if not scan_result.root_dir or not scan_result.tasks:
        errors.append("请先选择一个有效根文件夹，并确保其中至少包含一个可处理的音频文件。")

    provider = get_provider_by_label(config.translation_backend)
    errors.extend(provider.validate(config))
    return errors

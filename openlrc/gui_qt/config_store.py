from __future__ import annotations

import json
from pathlib import Path

from .models import AppConfig, GUI_CONFIG_PATH


def _sanitize_loaded_config(config: AppConfig) -> AppConfig:
    if config.scan_root_dir:
        scan_root = Path(config.scan_root_dir).expanduser()
        if not scan_root.is_dir():
            config.scan_root_dir = ""
    if not config.target_lang.strip():
        config.target_lang = "zh-cn"
    return config


def load_config(config_path: Path = GUI_CONFIG_PATH) -> AppConfig:
    if not config_path.exists():
        return AppConfig()

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return AppConfig()

    return _sanitize_loaded_config(AppConfig.from_dict(payload))


def save_config(config: AppConfig, config_path: Path = GUI_CONFIG_PATH) -> None:
    config_path.write_text(
        json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

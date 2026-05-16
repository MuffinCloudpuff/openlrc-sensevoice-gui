from __future__ import annotations

from pathlib import Path

from ...gui_qt.config_store import load_config, save_config
from ...gui_qt.models import AppConfig
from ..core.path_policy import ensure_existing_directory


def load_web_config() -> AppConfig:
    return load_config()


def save_web_config(payload: dict) -> AppConfig:
    config = AppConfig.from_dict(payload)
    if config.scan_root_dir:
        try:
            ensure_existing_directory(config.scan_root_dir, field_name="scan_root_dir")
        except Exception:
            config.scan_root_dir = ""
    if not config.target_lang.strip():
        config.target_lang = "zh-cn"
    save_config(config)
    return config


def serialize_config(config: AppConfig) -> dict:
    return config.to_dict()


def config_path() -> Path:
    from ...gui_qt.models import GUI_CONFIG_PATH

    return GUI_CONFIG_PATH

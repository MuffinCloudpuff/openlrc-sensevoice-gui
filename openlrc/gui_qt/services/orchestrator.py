from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from openlrc.directory_workflow import DirectoryTask, scan_directory

from ..models import AppConfig, ScanResult, SummaryItem
from ..translation.registry import get_provider_by_label


def detect_default_device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def has_nvidia_gpu() -> bool:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return False

    try:
        result = subprocess.run([nvidia_smi, "-L"], capture_output=True, text=True, timeout=5, check=False)
    except Exception:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def cache_summary(tasks: list[DirectoryTask]) -> str:
    cached_count = sum(1 for task in tasks if task.cache_valid)
    pending_count = max(len(tasks) - cached_count, 0)
    return f"ASR 可复用 {cached_count} / 需转写 {pending_count}"


def mode_label(skip_trans: bool, bilingual_sub: bool) -> str:
    if skip_trans:
        return "仅转写"
    if bilingual_sub:
        return "完整翻译 + 双语字幕"
    return "完整翻译"


def scan_root_directory(root_dir_text: str) -> ScanResult:
    root_text = (root_dir_text or "").strip()
    if not root_text:
        return ScanResult()

    root_dir = Path(root_text).expanduser()
    if not root_dir.exists() or not root_dir.is_dir():
        return ScanResult(root_dir=root_dir, error="当前根文件夹不存在，或不是一个有效目录。")

    tasks = scan_directory(root_dir)
    return ScanResult(root_dir=root_dir.resolve(), tasks=tasks)


def build_summary_items(config: AppConfig, scan_result: ScanResult) -> list[SummaryItem]:
    provider = get_provider_by_label(config.translation_backend)
    translation_summary = provider.summary(config)
    root_value = str(scan_result.root_dir) if scan_result.root_dir else "未选择"
    advanced_value = f"线程 {config.consumer_thread} / ITN {'开' if config.use_itn else '关'}"
    return [
        SummaryItem("文件数", str(scan_result.audio_count)),
        SummaryItem("任务模式", mode_label(config.skip_trans, config.bilingual_sub)),
        SummaryItem("ASR 模型", config.asr_model),
        SummaryItem("运行设备", config.device),
        SummaryItem("翻译配置", f"{provider.label} / {translation_summary}"),
        SummaryItem("费用上限", f"${config.fee_limit:.2f}"),
        SummaryItem("根目录", root_value),
        SummaryItem("高级参数", advanced_value),
    ]

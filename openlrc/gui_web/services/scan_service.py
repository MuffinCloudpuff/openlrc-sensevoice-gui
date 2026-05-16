from __future__ import annotations

from ...gui_qt.models import AppConfig, ScanResult, SummaryItem
from ...gui_qt.services.orchestrator import build_summary_items, scan_root_directory


def scan_directory_for_web(root_dir_text: str) -> ScanResult:
    return scan_root_directory(root_dir_text)


def build_scan_payload(config: AppConfig, scan_result: ScanResult) -> dict:
    tasks = []
    for task in scan_result.tasks:
        tasks.append(
            {
                "relative_path": str(task.relative_path),
                "audio_path": str(task.audio_path),
                "cache_dir": str(task.cache_dir),
                "lrc_path": str(task.lrc_path),
                "status": task.status,
                "cache_valid": task.cache_valid,
                "meta": task.meta,
                "translation_estimate_path": str(task.translation_estimate_path),
            }
        )

    summary: list[SummaryItem] = build_summary_items(config, scan_result)
    return {
        "root_dir": str(scan_result.root_dir) if scan_result.root_dir else "",
        "audio_count": scan_result.audio_count,
        "relative_paths": scan_result.relative_paths,
        "tasks": tasks,
        "summary": [{"label": item.label, "value": item.value} for item in summary],
        "error": scan_result.error,
    }

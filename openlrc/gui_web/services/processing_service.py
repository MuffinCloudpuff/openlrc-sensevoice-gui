from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from ...directory_workflow import (
    STATUS_ASR_DONE,
    STATUS_TRANSLATION_PENDING,
    materialize_asr_cache,
    scan_directory,
    store_asr_cache,
    store_translated_cache,
    store_translation_estimate_cache,
)
from ...gui_qt.models import AppConfig
from ...gui_qt.services.runtime import (
    apply_runtime_api_keys,
    build_lrcer,
    build_translation_confirmation_state,
    ensure_file_logger,
    estimate_translation_fee,
    is_local_translation_backend,
    normalize_src_lang,
    selected_fee_summary,
)
from ...gui_qt.translation.providers.local_hymt_runtime import ensure_ollama_model_ready, translate_lines_with_hymt
from ...logger import logger
from ...subtitle import Subtitle
from ...utils import get_preprocessed_path
from ..core.job_manager import JobCancelled


class ForwardingLogHandler(logging.Handler):
    def __init__(self, emit: Callable[[str, dict], None]) -> None:
        super().__init__()
        self._emit = emit
        self.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)-8s [%(threadName)s] %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._emit("log", {"message": self.format(record)})
        except Exception:
            pass


def _raise_if_cancelled(is_cancelled: Callable[[], bool]) -> None:
    if is_cancelled():
        raise JobCancelled()


def _preprocess_tasks_for_asr(
    lrcer,
    tasks,
    noise_suppress: bool,
    emit: Callable[[str, dict], None],
    is_cancelled: Callable[[], bool],
) -> None:
    if not tasks:
        return

    total = len(tasks)
    pending_tasks = []
    completed = 0
    for task in tasks:
        cache_ready = task.cache_valid and task.asr_raw_path.exists() and task.asr_optimized_path.exists()
        if cache_ready or get_preprocessed_path(task.audio_path).exists():
            completed += 1
            continue
        pending_tasks.append(task)

    emit("stage", {"message": "预处理音频"})
    emit(
        "progress",
        {
            "progress": int(8 + 20 * completed / max(total, 1)),
            "message": f"预处理 {completed}/{total}",
        },
    )
    if completed:
        emit("current_file", {"message": f"已复用预处理缓存 {completed}/{total}"})

    if not pending_tasks:
        return

    task_by_audio = {task.audio_path.resolve(): task for task in pending_tasks}

    def on_preprocess_progress(done: int, _batch_total: int, audio_path: Path) -> None:
        _raise_if_cancelled(is_cancelled)
        current_done = completed + done
        task = task_by_audio.get(Path(audio_path).resolve())
        current_file = str(task.relative_path) if task else str(audio_path)
        emit("current_file", {"message": f"正在预处理 {current_done}/{total}：{current_file}"})
        emit(
            "progress",
            {
                "progress": int(8 + 20 * current_done / max(total, 1)),
                "message": f"预处理 {current_done}/{total}",
                "current_file": current_file,
            },
        )

    lrcer.pre_process(
        [task.audio_path for task in pending_tasks],
        noise_suppress=noise_suppress,
        progress_callback=on_preprocess_progress,
    )


def _run_asr_for_preprocessed_task(
    lrcer,
    task,
    src_lang: str | None,
    target_lang: str | None,
    cache_status: str,
    preprocessed_path: Path,
) -> tuple[Path, Path]:
    if not preprocessed_path.exists():
        raise FileNotFoundError(f"Preprocessed audio not found: {preprocessed_path}")

    transcribed_path = lrcer._transcribe_single(preprocessed_path, src_lang)
    transcribed_sub = Subtitle.from_json(transcribed_path)
    transcribed_opt_sub = lrcer.post_process(transcribed_sub, update_name=True)
    optimized_path = transcribed_opt_sub.filename
    store_asr_cache(task, transcribed_path, optimized_path, target_lang=target_lang, status=cache_status)
    return transcribed_path, optimized_path


def _build_local_hymt_subtitle(
    config: AppConfig,
    task,
    optimized_path: Path,
    target_lang: str,
) -> Subtitle:
    transcribed_opt_sub = Subtitle.from_json(optimized_path)
    translated_texts = translate_lines_with_hymt(
        transcribed_opt_sub.texts,
        transcribed_opt_sub.lang,
        target_lang,
        config,
    )
    final_subtitle = Subtitle.from_json(optimized_path)
    final_subtitle.set_texts(translated_texts, lang=target_lang)
    final_json_path = optimized_path.with_name(f"{task.audio_path.stem}.json")
    final_subtitle.save(final_json_path, update_name=True)
    return final_subtitle


def _load_or_rebuild_asr_artifacts(
    lrcer,
    task,
    src_lang: str | None,
    target_lang: str | None,
    cache_status: str,
    emit: Callable[[str, dict], None],
    is_cancelled: Callable[[], bool],
    preprocessed_path: Path | None = None,
) -> tuple[Path, Path]:
    _raise_if_cancelled(is_cancelled)
    cache_ready = task.cache_valid and task.asr_raw_path.exists() and task.asr_optimized_path.exists()
    if cache_ready:
        try:
            return materialize_asr_cache(task)
        except Exception as exc:
            emit(
                "log",
                {
                    "message": f"缓存不完整，回退为重转写：{task.relative_path} ({exc})",
                },
            )
    return _run_asr_for_preprocessed_task(
        lrcer,
        task,
        src_lang,
        target_lang,
        cache_status,
        preprocessed_path or get_preprocessed_path(task.audio_path),
    )


def run_prepare_job(
    config: AppConfig,
    emit: Callable[[str, dict], None],
    is_cancelled: Callable[[], bool],
) -> dict:
    root_dir = Path(config.scan_root_dir).expanduser().resolve()
    scan_result = scan_directory(root_dir)
    if not scan_result:
        raise ValueError("当前根目录下没有可处理的音频文件。")

    log_path = root_dir / "openlrc_run.log"
    ensure_file_logger(log_path)
    apply_runtime_api_keys(config)
    lrcer, translation_model = build_lrcer(config)
    lrcer.preprocess_options["preprocess_workers"] = config.preprocess_workers
    src_lang = normalize_src_lang(config.src_lang)
    handler = ForwardingLogHandler(emit)
    logger.addHandler(handler)
    try:
        if is_local_translation_backend(config) and not config.skip_trans:
            emit("stage", {"message": "检查本地 HY-MT 模型"})
            emit("current_file", {"message": f"检查 Ollama 模型：{config.local_mt_model_id}"})
            ensure_ollama_model_ready(config)

        emit("stage", {"message": "准备任务"})
        emit("current_file", {"message": f"根目录：{root_dir}"})
        emit("progress", {"progress": 6, "message": "已完成任务准备"})

        asr_outputs: list[tuple] = []
        cache_status = STATUS_ASR_DONE if config.skip_trans else STATUS_TRANSLATION_PENDING
        _preprocess_tasks_for_asr(lrcer, scan_result, config.noise_suppress, emit, is_cancelled)
        _raise_if_cancelled(is_cancelled)
        emit("stage", {"message": "ASR 缓存与转写"})
        for index, task in enumerate(scan_result, start=1):
            _raise_if_cancelled(is_cancelled)
            emit(
                "current_file",
                {
                    "message": (
                        f"复用 ASR 缓存 {index}/{len(scan_result)}：{task.relative_path}"
                        if task.cache_valid
                        else f"正在转写 {index}/{len(scan_result)}：{task.relative_path}"
                    )
                },
            )
            transcribed_path, optimized_path = _load_or_rebuild_asr_artifacts(
                lrcer,
                task,
                src_lang,
                config.target_lang if not config.skip_trans else None,
                cache_status,
                emit,
                is_cancelled,
                get_preprocessed_path(task.audio_path),
            )
            asr_outputs.append((task, transcribed_path, optimized_path))
            emit(
                "progress",
                {
                    "progress": int(30 + 36 * index / max(len(scan_result), 1)),
                    "message": f"ASR {index}/{len(scan_result)}",
                    "current_file": str(task.relative_path),
                },
            )

        if config.skip_trans:
            emit("stage", {"message": "仅转写与导出"})
            generated_files: list[str] = []
            for index, (task, _transcribed_path, optimized_path) in enumerate(asr_outputs, start=1):
                _raise_if_cancelled(is_cancelled)
                base_name = task.audio_path.stem
                transcribed_opt_sub = Subtitle.from_json(optimized_path)
                final_subtitle = lrcer._build_final_subtitle(base_name, None, transcribed_opt_sub, True)
                lrcer._generate_subtitle_files(final_subtitle, base_name, "lrc")
                generated_files.extend(str(path) for path in lrcer.transcribed_paths[-1:])
                emit(
                    "progress",
                    {
                        "progress": int(72 + 26 * index / max(len(asr_outputs), 1)),
                        "message": f"导出 {index}/{len(asr_outputs)}",
                        "current_file": str(task.relative_path),
                    },
                )
            return {
                "status": "completed",
                "generated_files": generated_files,
                "log_path": str(log_path),
            }

        if is_local_translation_backend(config):
            emit("stage", {"message": "本地 HY-MT 翻译与导出"})
            generated_files: list[str] = []
            for index, (task, transcribed_path, optimized_path) in enumerate(asr_outputs, start=1):
                _raise_if_cancelled(is_cancelled)
                base_name = task.audio_path.stem
                emit("current_file", {"message": f"正在本地翻译 {index}/{len(asr_outputs)}：{task.relative_path}"})
                final_subtitle = _build_local_hymt_subtitle(config, task, optimized_path, config.target_lang)
                emit(
                    "progress",
                    {
                        "progress": int(72 + 18 * index / max(len(asr_outputs), 1)),
                        "message": f"翻译 {index}/{len(asr_outputs)}",
                        "current_file": str(task.relative_path),
                    },
                )

                lrcer._generate_subtitle_files(final_subtitle, base_name, "lrc")
                if config.bilingual_sub:
                    transcribed_opt_sub = Subtitle.from_json(optimized_path)
                    lrcer._handle_bilingual_subtitles(transcribed_path, base_name, transcribed_opt_sub, "lrc")
                store_translated_cache(task, final_subtitle.filename, target_lang=config.target_lang)
                generated_files.extend(str(path) for path in lrcer.transcribed_paths[-1:])
                emit(
                    "progress",
                    {
                        "progress": int(90 + 8 * index / max(len(asr_outputs), 1)),
                        "message": f"导出 {index}/{len(asr_outputs)}",
                        "current_file": str(task.relative_path),
                    },
                )

            return {
                "status": "completed",
                "generated_files": generated_files,
                "log_path": str(log_path),
            }

        emit("stage", {"message": "费用估算与确认"})
        confirmation_entries = []
        for index, (task, _transcribed_path, optimized_path) in enumerate(asr_outputs, start=1):
            _raise_if_cancelled(is_cancelled)
            base_name = task.audio_path.stem
            transcribed_opt_sub = Subtitle.from_json(optimized_path)
            emit("current_file", {"message": f"估算费用 {index}/{len(asr_outputs)}：{task.relative_path}"})
            cost_estimate = estimate_translation_fee(
                transcribed_opt_sub.texts,
                src_lang=transcribed_opt_sub.lang,
                target_lang=config.target_lang,
                chatbot_model=translation_model,
                title=base_name,
                glossary=lrcer.glossary,
            )
            store_translation_estimate_cache(task, cost_estimate)
            confirmation_entries.append(
                {
                    "relative_path": str(task.relative_path),
                    "cache_dir": str(task.cache_dir),
                    "estimate": cost_estimate,
                }
            )
            emit(
                "estimate",
                {
                    "message": (
                        f"{task.relative_path} | 行数 {int(cost_estimate['line_count'])} | "
                        f"保底 ${float(cost_estimate['total_floor_fee']):.4f} | "
                        f"建议 ${float(cost_estimate['total_likely_fee']):.4f}"
                    )
                },
            )
            emit(
                "progress",
                {
                    "progress": int(66 + 18 * index / max(len(asr_outputs), 1)),
                    "message": f"估算 {index}/{len(asr_outputs)}",
                    "current_file": str(task.relative_path),
                },
            )

        confirmation_state = build_translation_confirmation_state(root_dir, config.target_lang, confirmation_entries)
        return {
            "status": "waiting_confirmation",
            "confirmation_state": confirmation_state,
            "log_path": str(log_path),
        }
    finally:
        logger.removeHandler(handler)
        handler.close()


def run_translation_job(
    config: AppConfig,
    confirmation_state: dict,
    selected_relative_paths: list[str],
    emit: Callable[[str, dict], None],
    is_cancelled: Callable[[], bool],
) -> dict:
    if not confirmation_state:
        raise ValueError("缺少翻译确认状态。")
    if not selected_relative_paths:
        raise ValueError("未选择需要翻译的文件。")

    root_dir = Path(confirmation_state["root_dir"]).expanduser().resolve()
    log_path = root_dir / "openlrc_run.log"
    ensure_file_logger(log_path)
    apply_runtime_api_keys(config)
    lrcer, _translation_model = build_lrcer(config)
    handler = ForwardingLogHandler(emit)
    logger.addHandler(handler)
    try:
        tasks_by_relative = {str(task.relative_path): task for task in scan_directory(root_dir)}
        selected_tasks = [tasks_by_relative[relative] for relative in selected_relative_paths if relative in tasks_by_relative]
        if not selected_tasks:
            raise ValueError("所选文件在当前根目录下不存在。")

        selected_floor_fee, selected_likely_fee = selected_fee_summary(confirmation_state, selected_relative_paths)
        emit(
            "estimate",
            {
                "message": (
                    f"本次翻译：文件 {len(selected_tasks)} 个 | 保底 ${selected_floor_fee:.4f} | "
                    f"建议 ${selected_likely_fee:.4f} | 当前上限 ${config.fee_limit:.2f}"
                )
            },
        )
        if selected_floor_fee > config.fee_limit:
            raise ValueError(
                f"本次勾选文件的保底估算超过费用上限。当前上限 ${config.fee_limit:.2f}，保底估算 ${selected_floor_fee:.4f}。"
            )

        if is_local_translation_backend(config):
            emit("stage", {"message": "检查本地 HY-MT 模型"})
            ensure_ollama_model_ready(config)

        emit("stage", {"message": "翻译与导出"})
        generated_files: list[str] = []
        for index, task in enumerate(selected_tasks, start=1):
            _raise_if_cancelled(is_cancelled)
            transcribed_path, optimized_path = _load_or_rebuild_asr_artifacts(
                lrcer,
                task,
                normalize_src_lang(config.src_lang),
                confirmation_state["target_lang"],
                STATUS_TRANSLATION_PENDING,
                emit,
                is_cancelled,
                get_preprocessed_path(task.audio_path),
            )
            transcribed_opt_sub = Subtitle.from_json(optimized_path)
            base_name = task.audio_path.stem
            emit("current_file", {"message": f"正在翻译 {index}/{len(selected_tasks)}：{task.relative_path}"})

            if is_local_translation_backend(config):
                final_subtitle = _build_local_hymt_subtitle(
                    config,
                    task,
                    optimized_path,
                    confirmation_state["target_lang"],
                )
            else:
                final_subtitle = lrcer._build_final_subtitle(
                    base_name,
                    confirmation_state["target_lang"],
                    transcribed_opt_sub,
                    False,
                )
                if final_subtitle is None:
                    if lrcer.exception:
                        raise lrcer.exception
                    raise RuntimeError(f"翻译未返回字幕结果：{task.relative_path}")

            emit(
                "progress",
                {
                    "progress": int(70 + 20 * index / max(len(selected_tasks), 1)),
                    "message": f"翻译 {index}/{len(selected_tasks)}",
                    "current_file": str(task.relative_path),
                },
            )

            emit("stage", {"message": "导出字幕"})
            lrcer._generate_subtitle_files(final_subtitle, base_name, "lrc")
            if config.bilingual_sub:
                lrcer._handle_bilingual_subtitles(transcribed_path, base_name, transcribed_opt_sub, "lrc")
            store_translated_cache(task, final_subtitle.filename, target_lang=confirmation_state["target_lang"])
            generated_files.extend(str(path) for path in lrcer.transcribed_paths[-1:])
            emit(
                "progress",
                {
                    "progress": int(90 + 8 * index / max(len(selected_tasks), 1)),
                    "message": f"导出 {index}/{len(selected_tasks)}",
                    "current_file": str(task.relative_path),
                },
            )

        selected_set = set(selected_relative_paths)
        remaining_entries = [
            entry for entry in confirmation_state.get("entries", []) if entry["relative_path"] not in selected_set
        ]
        if remaining_entries:
            remaining_state = build_translation_confirmation_state(
                root_dir,
                confirmation_state["target_lang"],
                remaining_entries,
            )
            return {
                "status": "waiting_confirmation",
                "confirmation_state": remaining_state,
                "remaining_confirmation_state": remaining_state,
                "generated_files": generated_files,
                "log_path": str(log_path),
            }

        return {
            "status": "completed",
            "generated_files": generated_files,
            "log_path": str(log_path),
        }
    finally:
        logger.removeHandler(handler)
        handler.close()

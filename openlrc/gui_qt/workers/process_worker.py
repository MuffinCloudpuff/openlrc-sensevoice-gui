from __future__ import annotations

import logging
import traceback
from pathlib import Path

from openlrc.directory_workflow import (
    CACHE_DIR_NAME,
    STATUS_ASR_DONE,
    STATUS_TRANSLATION_PENDING,
    materialize_asr_cache,
    scan_directory,
    store_asr_cache,
    store_translated_cache,
    store_translation_estimate_cache,
)
from openlrc.logger import logger
from openlrc.subtitle import Subtitle

from ..models import AppConfig
from ..services.runtime import (
    apply_runtime_api_keys,
    build_lrcer,
    build_translation_confirmation_state,
    ensure_file_logger,
    estimate_translation_fee,
    is_local_translation_backend,
    normalize_src_lang,
    run_asr_for_task,
    selected_fee_summary,
)
from ..translation.providers.local_hymt_runtime import ensure_ollama_model_ready, translate_lines_with_hymt

try:
    from PySide6.QtCore import QObject, Signal
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 未安装，无法加载后台 worker。") from exc


class SignalLogHandler(logging.Handler):
    def __init__(self, callback):
        super().__init__()
        self._callback = callback
        self.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)-8s %(message)s"))

    def emit(self, record) -> None:
        try:
            self._callback(self.format(record))
        except Exception:
            pass


class ProcessWorker(QObject):
    progress_changed = Signal(int, str)
    stage_changed = Signal(str)
    current_file_changed = Signal(str)
    estimate_changed = Signal(str)
    log_line = Signal(str)
    confirmation_ready = Signal(object)
    completed = Signal(object)
    failed = Signal(str, str)
    done = Signal()

    def __init__(
        self,
        config: AppConfig,
        *,
        mode: str,
        confirmation_state: dict | None = None,
        selected_relative_paths: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.mode = mode
        self.confirmation_state = confirmation_state
        self.selected_relative_paths = selected_relative_paths or []
        self.log_path: Path | None = None

    def run(self) -> None:
        handler = SignalLogHandler(self.log_line.emit)
        logger.addHandler(handler)
        try:
            if self.mode == "prepare":
                self._run_prepare()
            elif self.mode == "translate":
                self._run_translate()
            else:
                raise ValueError(f"未知 worker 模式: {self.mode}")
        except Exception as exc:
            self.failed.emit(str(exc), traceback.format_exc())
        finally:
            logger.removeHandler(handler)
            self.done.emit()

    def _emit_progress(self, value: float, text: str) -> None:
        self.progress_changed.emit(max(0, min(100, int(value * 100))), text)

    def _run_prepare(self) -> None:
        root_dir = Path(self.config.scan_root_dir).expanduser().resolve()
        tasks = scan_directory(root_dir)
        self.log_path = root_dir / "openlrc_run.log"
        ensure_file_logger(self.log_path)
        apply_runtime_api_keys(self.config)
        lrcer, translation_model = build_lrcer(self.config)
        src_lang = normalize_src_lang(self.config.src_lang)
        phase_total = 4
        if is_local_translation_backend(self.config) and not self.config.skip_trans:
            self.stage_changed.emit("阶段 1/4：检查本地 HY-MT 模型")
            self.current_file_changed.emit(f"检查 Ollama 模型：{self.config.local_mt_model_id}")
            ensure_ollama_model_ready(self.config)

        self.stage_changed.emit("阶段 1/4：准备任务")
        self.current_file_changed.emit(f"根目录：{root_dir}")
        self._emit_progress(1 / phase_total, "已完成任务准备")

        self.stage_changed.emit("阶段 2/4：ASR 缓存与转写")
        asr_outputs: list[tuple] = []
        cache_status = STATUS_ASR_DONE if self.config.skip_trans else STATUS_TRANSLATION_PENDING
        for idx, task in enumerate(tasks, start=1):
            if task.cache_valid:
                self.current_file_changed.emit(f"复用 ASR 缓存 {idx}/{len(tasks)}：{task.relative_path}")
                transcribed_path, optimized_path = materialize_asr_cache(task)
                logger.info(f"Reused ASR cache for {task.relative_path}: {task.cache_dir}")
            else:
                self.current_file_changed.emit(f"正在转写 {idx}/{len(tasks)}：{task.relative_path}")
                transcribed_path, optimized_path = run_asr_for_task(
                    lrcer,
                    task,
                    src_lang,
                    self.config.noise_suppress,
                    self.config.target_lang if not self.config.skip_trans else None,
                    cache_status,
                )
            asr_outputs.append((task, transcribed_path, optimized_path))
            self._emit_progress((1 + idx / max(len(tasks), 1)) / phase_total, f"ASR 阶段 {idx}/{len(tasks)}")

        if self.config.skip_trans:
            self.stage_changed.emit("阶段 3/4：仅转写导出")
            for idx, (task, transcribed_path, optimized_path) in enumerate(asr_outputs, start=1):
                base_name = task.audio_path.stem
                self.current_file_changed.emit(f"正在导出 {idx}/{len(asr_outputs)}：{task.relative_path}")
                transcribed_opt_sub = Subtitle.from_json(optimized_path)
                final_subtitle = lrcer._build_final_subtitle(base_name, None, transcribed_opt_sub, True)
                lrcer._generate_subtitle_files(final_subtitle, base_name, "lrc")
                store_asr_cache(task, transcribed_path, optimized_path, target_lang=None, status=STATUS_ASR_DONE)
                self._emit_progress((2 + idx / max(len(asr_outputs), 1)) / phase_total, f"导出中 {idx}/{len(asr_outputs)}")

            self.stage_changed.emit("阶段 4/4：完成")
            self._emit_progress(1.0, "全部完成")
            self.completed.emit(
                {
                    "mode": "transcribe_only",
                    "generated_files": [str(path) for path in lrcer.transcribed_paths],
                    "root_dir": str(root_dir),
                    "log_path": str(self.log_path),
                    "remaining_confirmation_state": None,
                }
            )
            return

        self.stage_changed.emit("阶段 3/4：费用估算")
        confirmation_entries = []
        for idx, (task, _transcribed_path, optimized_path) in enumerate(asr_outputs, start=1):
            base_name = task.audio_path.stem
            transcribed_opt_sub = Subtitle.from_json(optimized_path)
            self.current_file_changed.emit(f"正在估算 {idx}/{len(asr_outputs)}：{task.relative_path}")

            if is_local_translation_backend(self.config):
                cost_estimate = {
                    "chunk_count": 1,
                    "line_count": len(transcribed_opt_sub.texts),
                    "context_fee": 0.0,
                    "chunk_floor_fee": 0.0,
                    "chunk_likely_fee": 0.0,
                    "total_floor_fee": 0.0,
                    "total_likely_fee": 0.0,
                    "estimated_guideline_tokens": 0,
                }
            else:
                cost_estimate = estimate_translation_fee(
                    transcribed_opt_sub.texts,
                    src_lang=transcribed_opt_sub.lang,
                    target_lang=self.config.target_lang,
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
            self.estimate_changed.emit(
                f"当前文件：{task.relative_path} | 行数 {int(cost_estimate['line_count'])} | "
                f"保底 ${float(cost_estimate['total_floor_fee']):.4f} | 建议 ${float(cost_estimate['total_likely_fee']):.4f}"
            )
            self._emit_progress((2 + idx / max(len(asr_outputs), 1)) / phase_total, f"费用估算 {idx}/{len(asr_outputs)}")

        confirmation_state = build_translation_confirmation_state(root_dir, self.config.target_lang, confirmation_entries)
        self.stage_changed.emit("ASR 与费用估算完成，等待翻译确认")
        self.current_file_changed.emit("请选择要翻译的文件。")
        self.confirmation_ready.emit(
            {
                "state": confirmation_state,
                "log_path": str(self.log_path),
            }
        )

    def _run_translate(self) -> None:
        if not self.confirmation_state:
            raise ValueError("缺少翻译确认状态。")
        if not self.selected_relative_paths:
            raise ValueError("未选择要翻译的文件。")

        root_dir = Path(self.confirmation_state["root_dir"]).expanduser().resolve()
        self.log_path = root_dir / "openlrc_run.log"
        ensure_file_logger(self.log_path)
        apply_runtime_api_keys(self.config)
        lrcer, _translation_model = build_lrcer(self.config)

        tasks_by_relative = {str(task.relative_path): task for task in scan_directory(root_dir)}
        selected_tasks = [
            tasks_by_relative[relative_path]
            for relative_path in self.selected_relative_paths
            if relative_path in tasks_by_relative
        ]
        if not selected_tasks:
            raise ValueError("选中的文件在当前根目录下不存在。")

        selected_floor_fee, selected_likely_fee = selected_fee_summary(self.confirmation_state, self.selected_relative_paths)
        self.estimate_changed.emit(
            f"已确认本次翻译范围：文件 {len(selected_tasks)} 个 | 保底 ${selected_floor_fee:.4f} | "
            f"建议 ${selected_likely_fee:.4f} | 当前费用上限 ${self.config.fee_limit:.2f}"
        )
        if selected_floor_fee > self.config.fee_limit:
            raise ValueError(
                f"本次勾选文件的保底估算超过费用上限。当前上限 ${self.config.fee_limit:.2f}，"
                f"保底估算 ${selected_floor_fee:.4f}，建议预留 ${selected_likely_fee:.4f}。"
            )

        self.stage_changed.emit("阶段 3/4：翻译所选文件")
        generated_files: list[str] = []
        for idx, task in enumerate(selected_tasks, start=1):
            transcribed_path, optimized_path = materialize_asr_cache(task)
            transcribed_opt_sub = Subtitle.from_json(optimized_path)
            base_name = task.audio_path.stem

            self.current_file_changed.emit(f"正在翻译 {idx}/{len(selected_tasks)}：{task.relative_path}")
            if is_local_translation_backend(self.config):
                translated_texts = translate_lines_with_hymt(
                    transcribed_opt_sub.texts,
                    transcribed_opt_sub.lang,
                    self.confirmation_state["target_lang"],
                    self.config,
                )
                final_subtitle = Subtitle.from_json(optimized_path)
                final_subtitle.set_texts(translated_texts, lang=self.confirmation_state["target_lang"])
                final_json_path = optimized_path.with_name(f"{base_name}.json")
                final_subtitle.save(final_json_path, update_name=True)
            else:
                final_subtitle = lrcer._build_final_subtitle(base_name, self.confirmation_state["target_lang"], transcribed_opt_sub, False)
                if final_subtitle is None:
                    if lrcer.exception:
                        raise lrcer.exception
                    raise RuntimeError(f"翻译未返回字幕结果：{task.relative_path}")
            self._emit_progress(0.75 + 0.15 * (idx / max(len(selected_tasks), 1)), f"翻译中 {idx}/{len(selected_tasks)}")

            self.stage_changed.emit("阶段 4/4：导出字幕")
            self.current_file_changed.emit(f"正在导出字幕 {idx}/{len(selected_tasks)}：{task.relative_path}")
            lrcer._generate_subtitle_files(final_subtitle, base_name, "lrc")
            if self.config.bilingual_sub:
                self.current_file_changed.emit(f"正在导出双语字幕 {idx}/{len(selected_tasks)}：{task.relative_path}")
                lrcer._handle_bilingual_subtitles(transcribed_path, base_name, transcribed_opt_sub, "lrc")
            store_translated_cache(task, final_subtitle.filename, target_lang=self.confirmation_state["target_lang"])
            generated_files.extend(str(path) for path in lrcer.transcribed_paths[-1:])
            self._emit_progress(0.9 + 0.1 * (idx / max(len(selected_tasks), 1)), f"导出完成 {idx}/{len(selected_tasks)}")

        selected_set = set(self.selected_relative_paths)
        remaining_entries = [
            entry for entry in self.confirmation_state.get("entries", []) if entry["relative_path"] not in selected_set
        ]
        remaining_state = None
        if remaining_entries:
            remaining_state = build_translation_confirmation_state(
                root_dir,
                self.confirmation_state["target_lang"],
                remaining_entries,
            )

        self.stage_changed.emit("处理完成")
        self._emit_progress(1.0, "全部完成")
        self.completed.emit(
            {
                "mode": "translation",
                "generated_files": generated_files,
                "root_dir": str(root_dir),
                "log_path": str(self.log_path),
                "remaining_confirmation_state": remaining_state,
            }
        )

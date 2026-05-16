from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Slot
from PySide6.QtWidgets import QFileDialog, QMessageBox

from ..config_store import load_config, save_config
from ..models import AppConfig, ScanResult
from ..services.orchestrator import build_summary_items, cache_summary, detect_default_device, scan_root_directory
from ..services.validation import validate_before_processing
from ..translation.replan import build_replan_text
from ..widgets.confirmation_dialog import ConfirmationDialog
from ..workers.process_worker import ProcessWorker


class V2Controller(QObject):
    def __init__(self, window, config_path: Path | None = None) -> None:
        super().__init__(window)
        self.window = window
        self.config_path = config_path
        self.default_device = detect_default_device()
        self.config = load_config(config_path) if config_path else load_config()
        if self.config.device not in ["cuda", "cpu"]:
            self.config.device = self.default_device
        self.scan_result = ScanResult()
        self.pending_confirmation_state: dict | None = None
        self.auto_open_confirmation_requested = False
        self.last_log_path: str | None = None
        self.worker_thread: QThread | None = None
        self.worker: ProcessWorker | None = None
        self._loading_config = False
        self.card_state = {
            "asr": True,
            "translation": False,
            "performance": False,
            "advanced": False,
        }

    @property
    def workspace(self):
        return self.window.workspace

    @property
    def settings_drawer(self):
        return self.window.settings_drawer

    def initialize(self) -> None:
        self._connect_ui()
        self._load_config_to_widgets()
        self.refresh_scan()

    def _connect_ui(self) -> None:
        self.workspace.scan_root_dir_edit.textChanged.connect(self._on_scan_root_dir_changed)
        self.workspace.browse_button.clicked.connect(self.choose_directory)
        self.workspace.scan_button.clicked.connect(self.refresh_scan)
        self.workspace.start_button.clicked.connect(self.start_processing)
        self.workspace.rescan_button.clicked.connect(self.refresh_scan)
        self.workspace.open_confirmation_button.clicked.connect(self.open_confirmation_dialog)
        self.workspace.bind_runtime_handlers(self._on_runtime_options_changed)
        self.settings_drawer.bind_change_handlers(self._on_config_changed, self._on_endpoint_mode_changed)
        self.settings_drawer.bind_card_state_handlers(self._on_card_state_changed)

    def _load_config_to_widgets(self) -> None:
        self._loading_config = True
        self.settings_drawer.load_config(self.config)
        self.settings_drawer.apply_card_state(self.card_state)
        self.workspace.load_runtime_config(self.config)
        self._apply_endpoint_mode()
        self.workspace.replan_label.setText(build_replan_text(self.config))
        self._loading_config = False

    def collect_config(self) -> AppConfig:
        self.settings_drawer.collect_into(self.config)
        self.workspace.collect_runtime_config(self.config)
        if self.config.translation_backend == "中转 API":
            self.config.endpoint_mode = "中转平台"
        elif self.config.translation_backend == "官方 API":
            self.config.endpoint_mode = "官方 API"
        self.config.use_custom_translation_endpoint = self.config.endpoint_mode == "中转平台"
        return self.config

    def _apply_endpoint_mode(self) -> None:
        self.settings_drawer.apply_backend_state(self.settings_drawer.fields["translation_backend"].currentText())

    def _persist_and_refresh(self) -> None:
        if self._loading_config:
            return
        self.collect_config()
        if self.config_path:
            save_config(self.config, self.config_path)
        else:
            save_config(self.config)
        self._apply_endpoint_mode()
        self.workspace.render_summary(build_summary_items(self.config, self.scan_result))
        self.workspace.replan_label.setText(build_replan_text(self.config))

    def _on_config_changed(self) -> None:
        self._persist_and_refresh()

    def _on_endpoint_mode_changed(self) -> None:
        self._persist_and_refresh()

    def _on_runtime_options_changed(self) -> None:
        self._persist_and_refresh()

    def _on_scan_root_dir_changed(self) -> None:
        self._persist_and_refresh()

    def _on_card_state_changed(self, key: str, expanded: bool) -> None:
        self.card_state[key] = expanded

    def choose_directory(self) -> None:
        current_dir = self.workspace.scan_root_dir_edit.text().strip() or str(Path.home())
        selected_dir = QFileDialog.getExistingDirectory(self.window, "选择根文件夹", current_dir)
        if selected_dir:
            self.workspace.scan_root_dir_edit.setText(selected_dir)
            self.refresh_scan()

    def refresh_scan(self) -> None:
        self.collect_config()
        self.scan_result = scan_root_directory(self.config.scan_root_dir)
        if self.scan_result.error:
            self.workspace.scan_status_label.setText(self.scan_result.error)
            self.workspace.append_log(self.scan_result.error)
        elif self.scan_result.tasks:
            message = f"共发现 {len(self.scan_result.tasks)} 个音频文件。{cache_summary(self.scan_result.tasks)}。"
            self.workspace.scan_status_label.setText(message)
            self.workspace.append_log(f"扫描完成：{self.scan_result.root_dir}，{message}")
        else:
            self.workspace.scan_status_label.setText("请选择一个根文件夹，系统会递归处理其中所有音频文件。")
        self.workspace.render_tasks(self.scan_result.tasks)
        self.workspace.render_summary(build_summary_items(self.config, self.scan_result))

    def _set_running_state(self, running: bool) -> None:
        self.workspace.start_button.setEnabled(not running)
        self.workspace.scan_button.setEnabled(not running)
        self.workspace.browse_button.setEnabled(not running)
        self.workspace.rescan_button.setEnabled(not running)
        self.workspace.open_confirmation_button.setEnabled(bool(self.pending_confirmation_state) and not running)

    def start_processing(self) -> None:
        if self.worker_thread is not None:
            QMessageBox.information(self.window, "处理中", "当前已有任务在运行，请等待完成。")
            return

        self.collect_config()
        errors = validate_before_processing(self.config, self.scan_result)
        if errors:
            QMessageBox.critical(self.window, "参数错误", "\n".join(errors))
            return

        self.pending_confirmation_state = None
        self.auto_open_confirmation_requested = False
        self.workspace.open_confirmation_button.setEnabled(False)
        self.workspace.confirmation_label.setText("正在进行 ASR 与费用估算...")
        self.workspace.console.clear()
        self.workspace.reset_progress()
        self.workspace.status_label.setText("已收到处理请求，正在检查参数并启动后台任务...")
        self._start_worker(mode="prepare")

    def _start_worker(self, *, mode: str, confirmation_state: dict | None = None, selected_relative_paths: list[str] | None = None) -> None:
        worker_config = AppConfig.from_dict(self.config.to_dict())
        self.worker_thread = QThread(self.window)
        self.worker = ProcessWorker(
            worker_config,
            mode=mode,
            confirmation_state=confirmation_state,
            selected_relative_paths=selected_relative_paths,
        )
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress_changed.connect(self._on_progress_changed, Qt.QueuedConnection)
        self.worker.stage_changed.connect(self._on_stage_changed, Qt.QueuedConnection)
        self.worker.current_file_changed.connect(self._on_current_file_changed, Qt.QueuedConnection)
        self.worker.estimate_changed.connect(self._on_estimate_changed, Qt.QueuedConnection)
        self.worker.log_line.connect(self.workspace.append_log, Qt.QueuedConnection)
        self.worker.confirmation_ready.connect(self._on_confirmation_ready, Qt.QueuedConnection)
        self.worker.completed.connect(self._on_worker_completed, Qt.QueuedConnection)
        self.worker.failed.connect(self._on_worker_failed, Qt.QueuedConnection)
        self.worker.done.connect(self.worker_thread.quit, Qt.QueuedConnection)
        self.worker.done.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(self._on_worker_thread_finished, Qt.QueuedConnection)
        self._set_running_state(True)
        self.worker_thread.start()

    @Slot(int, str)
    def _on_progress_changed(self, value: int, text: str) -> None:
        self.workspace.progress_bar.setValue(value)
        self.workspace.status_label.setText(text)

    @Slot(str)
    def _on_stage_changed(self, text: str) -> None:
        self.workspace.stage_label.setText(text)

    @Slot(str)
    def _on_current_file_changed(self, text: str) -> None:
        self.workspace.current_file_label.setText(text)

    @Slot(str)
    def _on_estimate_changed(self, text: str) -> None:
        self.workspace.estimate_label.setText(text)

    @Slot(object)
    def _on_confirmation_ready(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        self.pending_confirmation_state = data.get("state")
        self.last_log_path = data.get("log_path")
        if not self.pending_confirmation_state:
            return
        self.auto_open_confirmation_requested = True
        state = self.pending_confirmation_state
        self.workspace.confirmation_label.setText(
            f"待确认文件：{len(state.get('entries', []))} 个 | "
            f"保底估算 ${float(state.get('total_floor_fee', 0.0)):.4f} | "
            f"建议预留 ${float(state.get('total_likely_fee', 0.0)):.4f}"
        )
        self.workspace.open_confirmation_button.setEnabled(False)
        self.workspace.status_label.setText("ASR 和费用估算已完成，等待翻译确认。")
        self._maybe_open_pending_confirmation()

    def open_confirmation_dialog(self, auto_open: bool = False) -> None:
        if not self.pending_confirmation_state:
            if not auto_open:
                QMessageBox.information(self.window, "无待确认任务", "当前没有待确认的翻译任务。")
            return
        dialog = ConfirmationDialog(self.pending_confirmation_state, self.window)
        if dialog.exec() != 1:
            self.workspace.confirmation_label.setText("翻译确认已取消，可稍后再次打开确认窗口继续。")
            self.workspace.open_confirmation_button.setEnabled(True)
            self.auto_open_confirmation_requested = False
            return
        selected_relative_paths = dialog.selected_relative_paths()
        self.auto_open_confirmation_requested = False
        self.workspace.confirmation_label.setText(f"已确认翻译 {len(selected_relative_paths)} 个文件，正在启动翻译任务...")
        self.workspace.status_label.setText("已收到翻译确认，正在启动翻译任务...")
        self._start_worker(
            mode="translate",
            confirmation_state=self.pending_confirmation_state,
            selected_relative_paths=selected_relative_paths,
        )

    @Slot(object)
    def _on_worker_completed(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        generated_files = data.get("generated_files", [])
        self.last_log_path = data.get("log_path")
        self.pending_confirmation_state = data.get("remaining_confirmation_state")
        self.workspace.open_confirmation_button.setEnabled(bool(self.pending_confirmation_state))
        if self.pending_confirmation_state:
            state = self.pending_confirmation_state
            self.workspace.confirmation_label.setText(
                f"剩余待确认文件：{len(state.get('entries', []))} 个 | "
                f"保底估算 ${float(state.get('total_floor_fee', 0.0)):.4f} | "
                f"建议预留 ${float(state.get('total_likely_fee', 0.0)):.4f}"
            )
        else:
            self.workspace.confirmation_label.setText("当前没有待确认的翻译任务。")
        self.workspace.status_label.setText(f"处理完成，共生成 {len(generated_files)} 个文件。")
        self.workspace.append_log(f"处理完成，共生成 {len(generated_files)} 个文件。")
        for path in generated_files:
            self.workspace.append_log(f"输出文件：{path}")
        self.refresh_scan()
        QMessageBox.information(self.window, "处理完成", f"处理完成，共生成 {len(generated_files)} 个文件。")

    @Slot(str, str)
    def _on_worker_failed(self, message: str, tb: str) -> None:
        self.workspace.status_label.setText(f"处理失败：{message}")
        self.workspace.append_log(f"处理失败：{message}")
        self.workspace.append_log(tb)
        QMessageBox.critical(self.window, "处理失败", message)

    @Slot()
    def _on_worker_thread_finished(self) -> None:
        self.worker = None
        self.worker_thread = None
        self._set_running_state(False)
        self._maybe_open_pending_confirmation()

    def _maybe_open_pending_confirmation(self) -> None:
        if self.pending_confirmation_state and self.auto_open_confirmation_requested:
            if self.worker_thread is not None:
                return
            QTimer.singleShot(0, lambda: self.open_confirmation_dialog(auto_open=True))

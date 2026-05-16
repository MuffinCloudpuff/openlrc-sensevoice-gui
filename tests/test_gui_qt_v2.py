from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from openlrc.gui_qt.main_window_v2 import MainWindowV2


class TestGuiQtV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_v2_scan_updates_model_driven_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "gui_config.json"
            (root / "song.mp3").write_bytes(b"audio")
            window = MainWindowV2(config_path=config_path)
            window.workspace.scan_root_dir_edit.setText(str(root))
            window.controller.refresh_scan()

            self.assertEqual(window.workspace.task_model.rowCount(), 1)
            self.assertEqual(window.workspace.summary_labels[0][1].text(), "1")
            window.close()

    def test_v2_controller_lives_on_ui_thread(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "gui_config.json"
            window = MainWindowV2(config_path=config_path)

            self.assertIs(window.controller.thread(), self._app.thread())
            self.assertIs(window.controller.parent(), window)
            window.close()

    def test_v2_local_mode_switch_disables_api_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "gui_config.json"
            window = MainWindowV2(config_path=config_path)
            window.settings_drawer.fields["translation_backend"].setCurrentText("本地 HY-MT")
            window.controller._on_endpoint_mode_changed()

            self.assertTrue(window.settings_drawer.fields["local_mt_model_id"].isEnabled())
            self.assertFalse(window.settings_drawer.fields["openai_api_key"].isEnabled())
            self.assertFalse(window.settings_drawer.fields["relay_base_url"].isEnabled())
            window.close()

    def test_v2_card_state_is_managed_by_controller(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "gui_config.json"
            window = MainWindowV2(config_path=config_path)
            card = window.settings_drawer.card_translation
            card.expand()

            self.assertTrue(window.controller.card_state["translation"])
            card.collapse()
            self.assertFalse(window.controller.card_state["translation"])
            window.close()

    def test_v2_start_processing_routes_to_worker_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "gui_config.json"
            (root / "song.mp3").write_bytes(b"audio")
            window = MainWindowV2(config_path=config_path)
            window.workspace.scan_root_dir_edit.setText(str(root))
            window.controller.refresh_scan()
            window.workspace.skip_trans_checkbox.setChecked(True)

            with patch.object(window.controller, "_start_worker") as mocked_start_worker:
                window.controller.start_processing()
                mocked_start_worker.assert_called_once()

            window.close()

    def test_confirmation_auto_open_is_not_order_dependent(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "gui_config.json"
            window = MainWindowV2(config_path=config_path)
            state = {
                "root_dir": str(Path(tmp)),
                "target_lang": "zh-cn",
                "entries": [],
                "total_floor_fee": 0.0,
                "total_likely_fee": 0.0,
            }

            calls: list[bool] = []
            window.controller.auto_open_confirmation_requested = True
            window.controller.worker_thread = object()
            with patch.object(window.controller, "open_confirmation_dialog", side_effect=lambda auto_open=False: calls.append(auto_open)):
                window.controller._on_confirmation_ready({"state": state, "log_path": ""})
                self.assertEqual(calls, [])

                window.controller.worker_thread = None
                window.controller._maybe_open_pending_confirmation()
                QTimer.singleShot(0, self._app.quit)
                self._app.exec()

            self.assertEqual(calls, [True])
            window.close()

    def test_v2_ignores_stale_saved_scan_root_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "gui_config.json"
            stale_root = Path(tmp) / "deleted-root"
            config_path.write_text(
                json.dumps({"scan_root_dir": str(stale_root)}, ensure_ascii=False),
                encoding="utf-8",
            )

            window = MainWindowV2(config_path=config_path)

            self.assertEqual(window.controller.config.scan_root_dir, "")
            self.assertEqual(window.workspace.scan_root_dir_edit.text(), "")
            self.assertEqual(window.workspace.task_model.rowCount(), 0)
            window.close()


if __name__ == "__main__":
    unittest.main()

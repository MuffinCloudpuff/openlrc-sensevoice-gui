from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from openlrc.gui_qt.main_window_v2 import MainWindowV2


class TestGuiQtV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_v2_scan_updates_model_driven_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "song.mp3").write_bytes(b"audio")
            window = MainWindowV2()
            window.workspace.scan_root_dir_edit.setText(str(root))
            window.controller.refresh_scan()

            self.assertEqual(window.workspace.task_model.rowCount(), 1)
            self.assertEqual(window.workspace.summary_labels[0][1].text(), "1")
            window.close()

    def test_v2_local_mode_switch_disables_api_fields(self):
        window = MainWindowV2()
        window.settings_drawer.fields["translation_backend"].setCurrentText("本地 HY-MT")
        window.controller._on_endpoint_mode_changed()

        self.assertTrue(window.settings_drawer.fields["local_mt_model_id"].isEnabled())
        self.assertFalse(window.settings_drawer.fields["openai_api_key"].isEnabled())
        self.assertFalse(window.settings_drawer.fields["relay_base_url"].isEnabled())
        window.close()

    def test_v2_card_state_is_managed_by_controller(self):
        window = MainWindowV2()
        card = window.settings_drawer.card_translation
        card.expand()

        self.assertTrue(window.controller.card_state["translation"])
        card.collapse()
        self.assertFalse(window.controller.card_state["translation"])
        window.close()

    def test_v2_start_processing_routes_to_worker_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "song.mp3").write_bytes(b"audio")
            window = MainWindowV2()
            window.workspace.scan_root_dir_edit.setText(str(root))
            window.controller.refresh_scan()
            window.workspace.skip_trans_checkbox.setChecked(True)

            with patch.object(window.controller, "_start_worker") as mocked_start_worker:
                window.controller.start_processing()
                mocked_start_worker.assert_called_once()

            window.close()


if __name__ == "__main__":
    unittest.main()

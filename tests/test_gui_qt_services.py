from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openlrc.gui_qt.config_store import load_config, save_config
from openlrc.gui_qt.models import AppConfig
from openlrc.gui_qt.services.orchestrator import build_summary_items, scan_root_directory
from openlrc.gui_qt.services.validation import validate_before_processing
from openlrc.gui_qt.translation.replan import build_replan_text


class TestGuiQtServices(unittest.TestCase):
    def test_config_round_trip_preserves_core_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "gui.json"
            config = AppConfig(
                scan_root_dir="D:/demo",
                translation_backend="中转 API",
                endpoint_mode="中转平台",
                relay_model_name="gpt-5.4",
            )

            save_config(config, config_path)
            loaded = load_config(config_path)

            self.assertEqual(loaded.scan_root_dir, "D:/demo")
            self.assertEqual(loaded.translation_backend, "中转 API")
            self.assertEqual(loaded.endpoint_mode, "中转平台")
            self.assertEqual(loaded.relay_model_name, "gpt-5.4")

    def test_scan_root_directory_returns_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "song.mp3"
            audio.write_bytes(b"audio")

            result = scan_root_directory(str(root))

            self.assertEqual(result.audio_count, 1)
            self.assertEqual(result.relative_paths, ["song.mp3"])

    def test_validate_before_processing_requires_translation_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "song.mp3"
            audio.write_bytes(b"audio")
            scan_result = scan_root_directory(str(root))
            config = AppConfig(
                scan_root_dir=str(root),
                translation_backend="官方 API",
                endpoint_mode="官方 API",
                skip_trans=False,
            )

            errors = validate_before_processing(config, scan_result)

            self.assertTrue(any("API Key" in message for message in errors))

    def test_inactive_modes_do_not_participate_in_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "song.mp3"
            audio.write_bytes(b"audio")
            scan_result = scan_root_directory(str(root))
            config = AppConfig(
                scan_root_dir=str(root),
                translation_backend="本地 HY-MT",
                endpoint_mode="官方 API",
                local_mt_model_id="tencent/HY-MT1.5-1.8B",
                skip_trans=True,
            )

            errors = validate_before_processing(config, scan_result)

            self.assertEqual(errors, [])

    def test_build_summary_items_contains_root_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "song.mp3"
            audio.write_bytes(b"audio")
            scan_result = scan_root_directory(str(root))
            config = AppConfig(scan_root_dir=str(root))

            items = build_summary_items(config, scan_result)

            by_label = {item.label: item.value for item in items}
            self.assertIn("根目录", by_label)
            self.assertEqual(by_label["根目录"], str(root.resolve()))

    def test_build_replan_text_contains_selected_module(self):
        config = AppConfig(translation_backend="中转 API", relay_model_name="gpt-5.4")

        replan_text = build_replan_text(config)

        self.assertIn("当前模块：中转 API", replan_text)
        self.assertIn("模块文件：", replan_text)


if __name__ == "__main__":
    unittest.main()

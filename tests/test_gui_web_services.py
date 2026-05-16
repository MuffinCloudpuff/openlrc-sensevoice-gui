from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from openlrc.gui_qt.models import AppConfig, ScanResult
from openlrc.gui_common import native_dialogs
from openlrc.gui_web.app import app
from openlrc.gui_web.core.directory_watch import DirectoryWatchService, _directory_signature, _is_relevant_watch_path
from openlrc.gui_web.core.event_broker import EventBroker
from openlrc.gui_web.core.job_manager import JobManager
from openlrc.gui_web.services.file_service import list_output_files
from openlrc.gui_web.services.provider_service import list_provider_payloads
from openlrc.gui_web.services.scan_service import build_scan_payload, scan_directory_for_web


class TestGuiWebServices(unittest.TestCase):
    def test_scan_payload_contains_audio_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "demo.mp3"
            audio.write_bytes(b"audio")

            scan_result = scan_directory_for_web(str(root))
            payload = build_scan_payload(AppConfig(scan_root_dir=str(root)), scan_result)

            self.assertEqual(payload["audio_count"], 1)
            self.assertEqual(payload["tasks"][0]["relative_path"], "demo.mp3")

    def test_provider_catalog_includes_local_hymt(self):
        config = AppConfig(translation_backend="本地 HY-MT")
        providers = list_provider_payloads(config)
        labels = {item["label"] for item in providers}

        self.assertIn("本地 HY-MT", labels)

    def test_output_listing_ignores_cache_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "song.lrc").write_text("demo", encoding="utf-8")
            cache_dir = root / ".openlrc_cache"
            cache_dir.mkdir()
            (cache_dir / "hidden.json").write_text("{}", encoding="utf-8")

            payload = list_output_files(str(root))

            self.assertEqual(len(payload["files"]), 1)
            self.assertEqual(payload["files"][0]["relative_path"], "song.lrc")

    def test_job_record_persists_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = JobManager(state_dir=Path(tmp))
            record = manager.create_job(tmp, {"scan_root_dir": tmp})
            manager.record_event(record.id, "stage", {"message": "准备中"})
            manager.record_event(record.id, "progress", {"progress": 42, "message": "处理中"})

            snapshot = manager.snapshot(record.id)

            self.assertEqual(snapshot["progress"], 42)
            self.assertEqual(snapshot["stage"], "处理中")

    def test_job_events_are_broadcast_to_multiple_subscribers(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = JobManager(state_dir=Path(tmp))
            record = manager.create_job(tmp, {"scan_root_dir": tmp})
            first = manager.subscribe(record.id)
            second = manager.subscribe(record.id)

            manager.record_event(record.id, "selection", {"selected_relative_paths": ["demo.mp3"]})

            self.assertEqual(first.get_nowait()["type"], "selection")
            self.assertEqual(second.get_nowait()["type"], "selection")
            self.assertEqual(manager.snapshot(record.id)["selected_relative_paths"], ["demo.mp3"])

    def test_app_config_replaces_stale_local_hymt_paths_with_detected_paths(self):
        config = AppConfig.from_dict(
            {
                "translation_backend": "本地 HY-MT",
                "local_mt_tokenizer_dir": "D:/missing-tokenizer",
                "local_mt_gguf_path": "D:/missing-model.gguf",
            }
        )

        if Path("models/hy-mt/HY-MT1.5-1.8B-GPTQ-Int4/tokenizer_config.json").exists():
            self.assertIn("models", config.local_mt_tokenizer_dir)
        if Path("models/hy-mt-gguf/HY-MT1.5-1.8B-Q4_K_M.gguf").exists():
            self.assertTrue(config.local_mt_gguf_path.endswith("HY-MT1.5-1.8B-Q4_K_M.gguf"))

    def test_folder_dialog_endpoint_returns_selected_path(self):
        with patch("openlrc.gui_web.app.choose_folder", return_value={"selected": True, "path": "D:\\demo"}):
            response = TestClient(app).post("/api/dialogs/folder", json={"initial_dir": "D:\\"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"selected": True, "path": "D:\\demo"})

    def test_windows_folder_dialog_does_not_fallback_to_tkinter(self):
        with (
            patch.object(native_dialogs.os, "name", "nt"),
            patch.object(native_dialogs, "_choose_folder_native_windows", side_effect=RuntimeError("native failed")),
            patch.object(native_dialogs, "_choose_folder_tkinter") as tkinter_dialog,
        ):
            with self.assertRaises(RuntimeError):
                native_dialogs.choose_folder("D:\\")

        tkinter_dialog.assert_not_called()

    def test_event_broker_broadcasts_dashboard_events(self):
        broker = EventBroker()
        first = broker.subscribe()
        second = broker.subscribe()

        broker.publish("scan_changed", {"audio_count": 2})

        self.assertEqual(first.get_nowait()["type"], "scan_changed")
        self.assertEqual(second.get_nowait()["payload"], {"audio_count": 2})

    def test_scan_endpoint_repeated_same_root_still_scans_and_watches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scan_result = ScanResult(root_dir=root)
            with (
                patch("openlrc.gui_web.app.scan_directory_for_web", return_value=scan_result) as scan_mock,
                patch("openlrc.gui_web.app.directory_watcher") as watcher_mock,
            ):
                watcher_mock.snapshot.return_value = {"root_dir": str(root), "mode": "mock"}
                client = TestClient(app)
                payload = AppConfig(scan_root_dir=str(root)).to_dict()

                first = client.post("/api/scan", json=payload)
                second = client.post("/api/scan", json=payload)

            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            self.assertEqual(scan_mock.call_count, 2)
            self.assertEqual(watcher_mock.set_root.call_count, 2)

    def test_directory_watch_service_debounces_change_events(self):
        events = []

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = DirectoryWatchService(
                lambda changed_root, reason: events.append((changed_root, reason)),
                debounce_seconds=0.05,
                poll_interval_seconds=60,
                prefer_watchdog=False,
            )
            try:
                service.set_root(root)
                service.notify_change("created")
                service.notify_change("modified")
                time.sleep(0.2)
            finally:
                service.stop()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0], (root.resolve(), "modified"))

    def test_directory_watch_ignores_runtime_artifacts_for_scan_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_audio = root / "song.mp3"
            source_audio.write_bytes(b"audio")
            preprocessed_audio = root / "preprocessed" / "song_preprocessed.wav"
            preprocessed_audio.parent.mkdir()
            preprocessed_audio.write_bytes(b"generated")
            cache_file = root / ".openlrc_cache" / "song" / "meta.json"
            cache_file.parent.mkdir(parents=True)
            cache_file.write_text("{}", encoding="utf-8")
            output_file = root / "song.lrc"
            output_file.write_text("lyrics", encoding="utf-8")

            signature = _directory_signature(root)

            self.assertEqual(len(signature), 1)
            self.assertIn("song.mp3", signature[0][0])
            self.assertFalse(
                _is_relevant_watch_path(root, preprocessed_audio, event_type="modified", is_directory=False)
            )
            self.assertFalse(_is_relevant_watch_path(root, cache_file, event_type="modified", is_directory=False))
            self.assertFalse(_is_relevant_watch_path(root, output_file, event_type="modified", is_directory=False))
            self.assertFalse(_is_relevant_watch_path(root, root, event_type="created", is_directory=True))
            self.assertFalse(_is_relevant_watch_path(root, "", event_type="created", is_directory=True))
            self.assertTrue(_is_relevant_watch_path(root, source_audio, event_type="modified", is_directory=False))
            self.assertTrue(_is_relevant_watch_path(root, root / "new_album", event_type="created", is_directory=True))

    def test_bootstrap_endpoint_is_removed(self):
        response = TestClient(app).get("/api/bootstrap")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()

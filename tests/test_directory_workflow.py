import json
import tempfile
import unittest
from pathlib import Path

from openlrc.directory_workflow import (
    CACHE_DIR_NAME,
    STATUS_TRANSLATION_PENDING,
    cache_dir_for_audio,
    expected_transcription_paths,
    has_valid_asr_cache,
    make_task,
    materialize_asr_cache,
    scan_directory,
    store_asr_cache,
    store_translation_estimate_cache,
)


class TestDirectoryWorkflow(unittest.TestCase):
    def test_cache_dir_maps_relative_audio_path_without_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "sub" / "song.mp3"
            audio.parent.mkdir()
            audio.write_bytes(b"audio")

            cache_dir = cache_dir_for_audio(root, audio)

            self.assertEqual(cache_dir, root / CACHE_DIR_NAME / "sub" / "song")

    def test_scan_directory_ignores_cache_dir_and_reports_cache_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "a.mp3"
            ignored = root / CACHE_DIR_NAME / "ghost.mp3"
            audio.write_bytes(b"audio")
            ignored.parent.mkdir()
            ignored.write_bytes(b"not a source")

            tasks = scan_directory(root)

            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].relative_path, Path("a.mp3"))
            self.assertFalse(tasks[0].cache_valid)

    def test_store_asr_cache_writes_meta_and_validates_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "a.mp3"
            raw = root / "a_preprocessed_transcribed.json"
            optimized = root / "a_preprocessed_transcribed_optimized.json"
            audio.write_bytes(b"audio")
            raw.write_text(json.dumps({"language": "en", "segments": []}), encoding="utf-8")
            optimized.write_text(json.dumps({"language": "en", "segments": []}), encoding="utf-8")

            task = make_task(root, audio)
            store_asr_cache(task, raw, optimized, target_lang="zh-cn", status=STATUS_TRANSLATION_PENDING)
            cached_task = make_task(root, audio)

            self.assertTrue(cached_task.cache_valid)
            self.assertTrue(has_valid_asr_cache(cached_task))
            self.assertEqual(cached_task.meta["source_relative_path"], "a.mp3")
            self.assertEqual(cached_task.meta["target_lang"], "zh-cn")

            audio.write_bytes(b"changed")
            stale_task = make_task(root, audio)
            self.assertFalse(stale_task.cache_valid)

    def test_materialize_asr_cache_restores_expected_working_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "sub" / "song.mp3"
            raw = root / "raw.json"
            optimized = root / "optimized.json"
            audio.parent.mkdir()
            audio.write_bytes(b"audio")
            raw.write_text(json.dumps({"language": "en", "segments": []}), encoding="utf-8")
            optimized.write_text(json.dumps({"language": "en", "segments": []}), encoding="utf-8")

            task = make_task(root, audio)
            store_asr_cache(task, raw, optimized, target_lang="zh-cn", status=STATUS_TRANSLATION_PENDING)
            cached_task = make_task(root, audio)
            materialized_raw, materialized_optimized = materialize_asr_cache(cached_task)
            expected_raw, expected_optimized = expected_transcription_paths(cached_task)

            self.assertEqual(materialized_raw, expected_raw)
            self.assertEqual(materialized_optimized, expected_optimized)
            self.assertTrue(expected_raw.exists())
            self.assertTrue(expected_optimized.exists())

    def test_store_translation_estimate_cache_writes_estimate_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "song.mp3"
            audio.write_bytes(b"audio")
            task = make_task(root, audio)

            estimate_path = store_translation_estimate_cache(
                task,
                {"line_count": 10, "chunk_count": 2, "total_floor_fee": 0.12, "total_likely_fee": 0.18},
            )

            self.assertTrue(estimate_path.exists())
            payload = json.loads(estimate_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["line_count"], 10)
            self.assertEqual(payload["chunk_count"], 2)


if __name__ == "__main__":
    unittest.main()

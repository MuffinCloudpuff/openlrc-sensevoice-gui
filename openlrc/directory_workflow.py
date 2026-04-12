from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SUPPORTED_AUDIO_EXTENSIONS = (".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma")
CACHE_DIR_NAME = ".openlrc_cache"

ASR_RAW_FILENAME = "asr_raw.json"
ASR_OPTIMIZED_FILENAME = "asr_optimized.json"
TRANSLATED_FILENAME = "translated.json"
TRANSLATION_ESTIMATE_FILENAME = "translation_estimate.json"
META_FILENAME = "meta.json"

STATUS_NOT_STARTED = "not_started"
STATUS_ASR_DONE = "asr_done"
STATUS_TRANSLATION_PENDING = "translation_pending"
STATUS_TRANSLATED = "translated"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class DirectoryTask:
    root_dir: Path
    audio_path: Path
    relative_path: Path
    cache_dir: Path
    lrc_path: Path
    status: str = STATUS_NOT_STARTED
    cache_valid: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def asr_raw_path(self) -> Path:
        return self.cache_dir / ASR_RAW_FILENAME

    @property
    def asr_optimized_path(self) -> Path:
        return self.cache_dir / ASR_OPTIMIZED_FILENAME

    @property
    def translated_path(self) -> Path:
        return self.cache_dir / TRANSLATED_FILENAME

    @property
    def translation_estimate_path(self) -> Path:
        return self.cache_dir / TRANSLATION_ESTIMATE_FILENAME

    @property
    def meta_path(self) -> Path:
        return self.cache_dir / META_FILENAME


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_root(root_dir: str | Path) -> Path:
    return Path(root_dir).expanduser().resolve()


def is_supported_audio(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS


def is_inside_cache(root_dir: Path, path: Path) -> bool:
    try:
        path.relative_to(root_dir / CACHE_DIR_NAME)
        return True
    except ValueError:
        return False


def audio_relative_path(root_dir: Path, audio_path: Path) -> Path:
    return audio_path.resolve().relative_to(root_dir.resolve())


def cache_dir_for_audio(root_dir: str | Path, audio_path: str | Path) -> Path:
    root = normalize_root(root_dir)
    audio = Path(audio_path).expanduser().resolve()
    relative = audio_relative_path(root, audio)
    return root / CACHE_DIR_NAME / relative.with_suffix("")


def lrc_path_for_audio(audio_path: str | Path) -> Path:
    return Path(audio_path).expanduser().resolve().with_suffix(".lrc")


def read_meta(cache_dir: str | Path) -> dict[str, Any]:
    meta_path = Path(cache_dir) / META_FILENAME
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_meta(cache_dir: str | Path, meta: dict[str, Any]) -> Path:
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    meta_path = cache / META_FILENAME
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta_path


def audio_fingerprint(root_dir: str | Path, audio_path: str | Path) -> dict[str, Any]:
    root = normalize_root(root_dir)
    audio = Path(audio_path).expanduser().resolve()
    stat = audio.stat()
    return {
        "source_relative_path": str(audio_relative_path(root, audio)),
        "source_absolute_path": str(audio),
        "source_size": stat.st_size,
        "source_mtime": stat.st_mtime,
        "source_mtime_ns": stat.st_mtime_ns,
    }


def build_meta(
    task: DirectoryTask,
    *,
    status: str,
    target_lang: str | None = None,
    asr_status: str | None = None,
    translation_status: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    inferred_asr_status = asr_status or (STATUS_ASR_DONE if status != STATUS_NOT_STARTED else STATUS_NOT_STARTED)
    inferred_translation_status = translation_status or (
        STATUS_TRANSLATED
        if status == STATUS_TRANSLATED
        else STATUS_NOT_STARTED
        if target_lang is None
        else STATUS_TRANSLATION_PENDING
    )
    meta = {
        **audio_fingerprint(task.root_dir, task.audio_path),
        "asr_status": inferred_asr_status,
        "translation_status": inferred_translation_status,
        "status": status,
        "target_lang": target_lang,
        "updated_at": utc_now_iso(),
        "lrc_exists": task.lrc_path.exists(),
    }
    if error:
        meta["error"] = error
    return meta


def meta_matches_audio(meta: dict[str, Any], root_dir: str | Path, audio_path: str | Path) -> bool:
    if not meta:
        return False
    audio = Path(audio_path).expanduser().resolve()
    if not audio.exists():
        return False
    current = audio_fingerprint(root_dir, audio)
    return (
        meta.get("source_relative_path") == current["source_relative_path"]
        and meta.get("source_size") == current["source_size"]
        and meta.get("source_mtime_ns") == current["source_mtime_ns"]
    )


def has_valid_asr_cache(task: DirectoryTask) -> bool:
    return (
        meta_matches_audio(task.meta, task.root_dir, task.audio_path)
        and task.asr_raw_path.exists()
        and task.asr_optimized_path.exists()
    )


def task_status_from_cache(task: DirectoryTask) -> tuple[str, bool]:
    valid_asr = has_valid_asr_cache(task)
    if not valid_asr:
        return STATUS_NOT_STARTED, False
    if task.translated_path.exists() and task.lrc_path.exists():
        return STATUS_TRANSLATED, True
    return task.meta.get("status") or STATUS_TRANSLATION_PENDING, True


def make_task(root_dir: str | Path, audio_path: str | Path) -> DirectoryTask:
    root = normalize_root(root_dir)
    audio = Path(audio_path).expanduser().resolve()
    relative = audio_relative_path(root, audio)
    cache_dir = cache_dir_for_audio(root, audio)
    meta = read_meta(cache_dir)
    task = DirectoryTask(
        root_dir=root,
        audio_path=audio,
        relative_path=relative,
        cache_dir=cache_dir,
        lrc_path=lrc_path_for_audio(audio),
        meta=meta,
    )
    status, cache_valid = task_status_from_cache(task)
    return DirectoryTask(
        root_dir=task.root_dir,
        audio_path=task.audio_path,
        relative_path=task.relative_path,
        cache_dir=task.cache_dir,
        lrc_path=task.lrc_path,
        status=status,
        cache_valid=cache_valid,
        meta=task.meta,
    )


def scan_directory(root_dir: str | Path) -> list[DirectoryTask]:
    root = normalize_root(root_dir)
    if not root.is_dir():
        raise NotADirectoryError(root)

    audio_paths = sorted(
        path.resolve()
        for path in root.rglob("*")
        if is_supported_audio(path) and not is_inside_cache(root, path.resolve())
    )
    return [make_task(root, path) for path in audio_paths]


def expected_transcription_paths(task: DirectoryTask) -> tuple[Path, Path]:
    preprocessed_dir = task.audio_path.parent / "preprocessed"
    base = f"{task.audio_path.stem}_preprocessed_transcribed"
    return preprocessed_dir / f"{base}.json", preprocessed_dir / f"{base}_optimized.json"


def materialize_asr_cache(task: DirectoryTask) -> tuple[Path, Path]:
    if not has_valid_asr_cache(task):
        raise ValueError(f"ASR cache is missing or stale: {task.relative_path}")

    raw_path, optimized_path = expected_transcription_paths(task)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(task.asr_raw_path, raw_path)
    shutil.copy2(task.asr_optimized_path, optimized_path)
    return raw_path, optimized_path


def store_asr_cache(
    task: DirectoryTask,
    raw_path: str | Path,
    optimized_path: str | Path,
    *,
    target_lang: str | None = None,
    status: str = STATUS_TRANSLATION_PENDING,
) -> dict[str, Any]:
    task.cache_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(raw_path, task.asr_raw_path)
    shutil.copy2(optimized_path, task.asr_optimized_path)
    meta = build_meta(task, status=status, target_lang=target_lang, asr_status=STATUS_ASR_DONE)
    write_meta(task.cache_dir, meta)
    return meta


def store_translated_cache(task: DirectoryTask, translated_json_path: str | Path, *, target_lang: str) -> dict[str, Any]:
    task.cache_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(translated_json_path, task.translated_path)
    meta = build_meta(
        task,
        status=STATUS_TRANSLATED,
        target_lang=target_lang,
        asr_status=STATUS_ASR_DONE,
        translation_status=STATUS_TRANSLATED,
    )
    write_meta(task.cache_dir, meta)
    return meta


def store_translation_estimate_cache(task: DirectoryTask, estimate: dict[str, Any]) -> Path:
    task.cache_dir.mkdir(parents=True, exist_ok=True)
    task.translation_estimate_path.write_text(json.dumps(estimate, ensure_ascii=False, indent=2), encoding="utf-8")
    return task.translation_estimate_path


def mark_task_failed(task: DirectoryTask, error: str, *, target_lang: str | None = None) -> dict[str, Any]:
    meta = build_meta(
        task,
        status=STATUS_FAILED,
        target_lang=target_lang,
        asr_status=task.meta.get("asr_status", STATUS_NOT_STARTED),
        translation_status=task.meta.get("translation_status", STATUS_NOT_STARTED),
        error=error,
    )
    write_meta(task.cache_dir, meta)
    return meta

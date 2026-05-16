from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from ...directory_workflow import (
    CACHE_DIR_NAME,
    GENERATED_AUDIO_STEM_SUFFIXES,
    PREPROCESSED_DIR_NAME,
    SUPPORTED_AUDIO_EXTENSIONS,
    VIDEO_SOURCE_EXTENSIONS,
)

logger = logging.getLogger(__name__)

DirectoryChangedCallback = Callable[[Path, str], None]


def _is_inside_internal_dir(root: Path, path: Path) -> bool:
    try:
        relative_path = path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return CACHE_DIR_NAME in relative_path.parts or PREPROCESSED_DIR_NAME in relative_path.parts


def _is_generated_audio_path(path: Path) -> bool:
    if path.stem.endswith(GENERATED_AUDIO_STEM_SUFFIXES):
        return True
    if path.suffix.lower() == ".wav":
        source_stem = path.with_suffix("")
        return any(source_stem.with_suffix(ext).exists() for ext in VIDEO_SOURCE_EXTENSIONS)
    return False


def _is_source_audio_path(root: Path, path: Path) -> bool:
    if path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
        return False
    if _is_inside_internal_dir(root, path):
        return False
    return not _is_generated_audio_path(path)


def _is_relevant_watch_path(root: Path, path: str | Path | None, *, event_type: str, is_directory: bool) -> bool:
    if path is None:
        return False
    if not str(path).strip():
        return False

    candidate = Path(path)
    try:
        if candidate.resolve() == root.resolve():
            return False
    except OSError:
        pass
    if _is_inside_internal_dir(root, candidate):
        return False

    if is_directory:
        return event_type in {"created", "deleted", "moved"}

    if not _is_source_audio_path(root, candidate):
        return False

    return event_type in {"created", "deleted", "modified", "moved"}


def _directory_signature(root: Path) -> tuple[tuple[str, int, int], ...]:
    entries: list[tuple[str, int, int]] = []
    try:
        iterator = root.rglob("*")
    except OSError:
        return ()

    for path in iterator:
        if not _is_source_audio_path(root, path):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if not path.is_file():
            continue
        try:
            relative_path = str(path.resolve().relative_to(root.resolve()))
        except ValueError:
            relative_path = str(path.resolve())
        entries.append((relative_path, stat.st_mtime_ns, stat.st_size))
    return tuple(sorted(entries))


class DirectoryWatchService:
    def __init__(
        self,
        on_change: DirectoryChangedCallback,
        *,
        debounce_seconds: float = 1.0,
        poll_interval_seconds: float = 2.0,
        prefer_watchdog: bool = True,
    ) -> None:
        self._on_change = on_change
        self._debounce_seconds = debounce_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._prefer_watchdog = prefer_watchdog
        self._root: Path | None = None
        self._observer = None
        self._poll_stop: threading.Event | None = None
        self._poll_thread: threading.Thread | None = None
        self._debounce_timer: threading.Timer | None = None
        self._emit_lock = threading.Lock()
        self._lock = threading.RLock()
        self._mode = "stopped"

    def set_root(self, root_dir: str | Path) -> None:
        root = Path(root_dir).expanduser().resolve()
        if not root.is_dir():
            self.stop()
            return

        with self._lock:
            if self._root == root and self._mode != "stopped":
                return
            self._stop_locked()
            self._root = root
            if self._prefer_watchdog and self._start_watchdog_locked(root):
                self._mode = "watchdog"
                return
            self._start_polling_locked(root)
            self._mode = "polling"

    def notify_change(self, reason: str = "changed") -> None:
        with self._lock:
            if self._root is None:
                return
            root = self._root
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            timer = threading.Timer(self._debounce_seconds, self._emit_change, args=(root, reason))
            timer.daemon = True
            self._debounce_timer = timer
            timer.start()

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return {"root_dir": str(self._root) if self._root else "", "mode": self._mode}

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()
            self._root = None
            self._mode = "stopped"

    def _emit_change(self, root: Path, reason: str) -> None:
        with self._lock:
            if root != self._root:
                return
        if not self._emit_lock.acquire(blocking=False):
            self.notify_change("coalesced")
            return
        try:
            self._on_change(root, reason)
        except Exception:
            logger.exception("Failed to handle directory change for %s", root)
        finally:
            self._emit_lock.release()

    def _start_watchdog_locked(self, root: Path) -> bool:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except Exception:
            return False

        service = self

        class Handler(FileSystemEventHandler):
            def on_any_event(self, event) -> None:  # type: ignore[no-untyped-def]
                event_type = str(getattr(event, "event_type", "") or "changed")
                if event_type in {"opened", "closed", "closed_no_write"}:
                    return
                src_path = getattr(event, "src_path", None)
                dest_path = getattr(event, "dest_path", None)
                is_directory = bool(getattr(event, "is_directory", False))
                if not (
                    _is_relevant_watch_path(root, src_path, event_type=event_type, is_directory=is_directory)
                    or _is_relevant_watch_path(root, dest_path, event_type=event_type, is_directory=is_directory)
                ):
                    return
                service.notify_change(event_type)

        observer = Observer()
        observer.daemon = True
        observer.schedule(Handler(), str(root), recursive=True)
        try:
            observer.start()
        except Exception:
            logger.exception("Failed to start watchdog observer for %s", root)
            return False
        self._observer = observer
        return True

    def _start_polling_locked(self, root: Path) -> None:
        stop_event = threading.Event()
        self._poll_stop = stop_event

        def worker() -> None:
            previous = _directory_signature(root)
            while not stop_event.wait(self._poll_interval_seconds):
                with self._lock:
                    if self._root != root:
                        return
                current = _directory_signature(root)
                if current != previous:
                    previous = current
                    self.notify_change("poll")

        thread = threading.Thread(target=worker, name="OpenLRCDirectoryWatch", daemon=True)
        self._poll_thread = thread
        thread.start()

    def _stop_locked(self) -> None:
        if self._debounce_timer is not None:
            self._debounce_timer.cancel()
            self._debounce_timer = None

        if self._observer is not None:
            observer = self._observer
            self._observer = None
            try:
                observer.stop()
                observer.join(timeout=2)
            except Exception:
                logger.exception("Failed to stop watchdog observer")

        if self._poll_stop is not None:
            self._poll_stop.set()
            self._poll_stop = None
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=2)
            self._poll_thread = None

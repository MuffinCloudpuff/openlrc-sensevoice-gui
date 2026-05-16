from __future__ import annotations

import json
import queue
import threading
import traceback
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...gui_qt.models import PROJECT_ROOT
from ..core.path_policy import normalize_user_path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


@dataclass(slots=True)
class JobRecord:
    id: str
    root_dir: str
    status: str = "created"
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    generated_files: list[str] = field(default_factory=list)
    confirmation_state: dict[str, Any] | None = None
    selected_relative_paths: list[str] = field(default_factory=list)
    progress: int = 0
    stage: str = ""
    current_file: str = ""
    estimate: str = ""
    log_excerpt: list[str] = field(default_factory=list)
    log_path: str = ""
    canceled: bool = False

    @classmethod
    def create(cls, root_dir: str, config_snapshot: dict[str, Any]) -> JobRecord:
        return cls(
            id=uuid.uuid4().hex[:12],
            root_dir=str(normalize_user_path(root_dir)),
            config_snapshot=config_snapshot,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> JobRecord:
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class JobRunResult:
    status: str
    generated_files: list[str] = field(default_factory=list)
    confirmation_state: dict[str, Any] | None = None
    log_path: str = ""
    error: str | None = None


class JobCancelled(RuntimeError):
    pass


class JobManager:
    def __init__(self, state_dir: Path | None = None) -> None:
        self.state_dir = (state_dir or (PROJECT_ROOT / ".openlrc_web")).expanduser().resolve()
        self.jobs_dir = self.state_dir / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, JobRecord] = {}
        self._subscribers: dict[str, list[queue.Queue[dict[str, Any]]]] = {}
        self._cancel_flags: dict[str, threading.Event] = {}
        self._event_listener: Callable[[dict[str, Any]], None] | None = None
        self._lock = threading.RLock()
        self._load_records()

    def set_event_listener(self, listener: Callable[[dict[str, Any]], None] | None) -> None:
        with self._lock:
            self._event_listener = listener

    def _load_records(self) -> None:
        for path in sorted(self.jobs_dir.glob("*.json")):
            try:
                record = JobRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
            self._records[record.id] = record
            self._subscribers[record.id] = []
            self._cancel_flags[record.id] = threading.Event()

    def _record_path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.json"

    def _persist(self, record: JobRecord) -> None:
        record.updated_at = utc_now_iso()
        self._record_path(record.id).write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def create_job(self, root_dir: str, config_snapshot: dict[str, Any]) -> JobRecord:
        record = JobRecord.create(root_dir, config_snapshot)
        with self._lock:
            self._records[record.id] = record
            self._subscribers[record.id] = []
            self._cancel_flags[record.id] = threading.Event()
            self._persist(record)
        return record

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._records.get(job_id)

    def list_jobs(self) -> list[JobRecord]:
        with self._lock:
            return sorted(self._records.values(), key=lambda item: item.updated_at, reverse=True)

    def snapshot(self, job_id: str) -> dict[str, Any]:
        record = self.get_job(job_id)
        if record is None:
            raise KeyError(job_id)
        return record.to_dict()

    def is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            flag = self._cancel_flags.get(job_id)
            return bool(flag and flag.is_set())

    def cancel_job(self, job_id: str) -> JobRecord:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                raise KeyError(job_id)
            self._cancel_flags[job_id].set()
            if record.status not in TERMINAL_STATUSES:
                record.status = "cancel_requested"
                if record.started_at is None:
                    record.started_at = utc_now_iso()
                self._persist(record)
        self.record_event(job_id, "status", {"status": "cancel_requested"})
        return self.get_job(job_id)  # type: ignore[return-value]

    def delete_job(self, job_id: str) -> JobRecord:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                raise KeyError(job_id)
            if record.status not in TERMINAL_STATUSES:
                raise ValueError("running job cannot be deleted")
            deleted = self._records.pop(job_id)
            self._subscribers.pop(job_id, None)
            self._cancel_flags.pop(job_id, None)
            path = self._record_path(job_id)
            if path.exists():
                path.unlink()
        return deleted

    def record_event(self, job_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            record = self._records[job_id]
            if event_type == "progress":
                record.progress = int(payload.get("progress", record.progress))
                if payload.get("message"):
                    record.stage = str(payload["message"])
                if payload.get("current_file"):
                    record.current_file = str(payload["current_file"])
            elif event_type == "stage":
                record.stage = str(payload.get("message", record.stage))
            elif event_type == "current_file":
                record.current_file = str(payload.get("message", record.current_file))
            elif event_type == "estimate":
                record.estimate = str(payload.get("message", record.estimate))
            elif event_type == "confirmation_required":
                state = payload.get("state")
                if isinstance(state, dict):
                    record.confirmation_state = state
                record.status = str(payload.get("status", "waiting_confirmation"))
            elif event_type == "completed":
                record.status = "completed"
                record.finished_at = utc_now_iso()
                record.progress = 100
                record.generated_files = list(payload.get("generated_files", record.generated_files))
                record.confirmation_state = payload.get("remaining_confirmation_state")
            elif event_type == "failed":
                record.status = "failed"
                record.finished_at = utc_now_iso()
                record.error = str(payload.get("message") or payload.get("error") or "")
            elif event_type == "cancelled":
                record.status = "cancelled"
                record.finished_at = utc_now_iso()
            elif event_type == "log":
                message = str(payload.get("message", "")).strip()
                if message:
                    record.log_excerpt.append(message)
                    record.log_excerpt = record.log_excerpt[-200:]
            elif event_type == "job_started":
                record.status = str(payload.get("status", record.status))
                if record.started_at is None:
                    record.started_at = utc_now_iso()
            elif event_type == "status":
                record.status = str(payload.get("status", record.status))
            elif event_type == "selection":
                record.selected_relative_paths = list(payload.get("selected_relative_paths", record.selected_relative_paths))
            record.updated_at = utc_now_iso()
            self._persist(record)

        event = {
            "type": event_type,
            "payload": payload,
            "job_id": job_id,
            "timestamp": utc_now_iso(),
        }
        with self._lock:
            subscribers = list(self._subscribers.get(job_id, []))
            event_listener = self._event_listener
        for subscriber in subscribers:
            subscriber.put(event)
        if event_listener:
            try:
                event_listener(event)
            except Exception:
                pass
        return event

    def _run_background(
        self,
        job_id: str,
        runner: Callable[[Callable[[str, dict[str, Any]], None], Callable[[], bool]], dict[str, Any]],
    ) -> None:
        def emit(event_type: str, payload: dict[str, Any]) -> None:
            self.record_event(job_id, event_type, payload)

        try:
            result = runner(emit, lambda: self.is_cancelled(job_id))
            status = str(result.get("status", "completed"))
            if status == "waiting_confirmation":
                if result.get("generated_files"):
                    self._update_generated_files(job_id, [str(item) for item in result["generated_files"]])
                self.record_event(
                    job_id,
                    "confirmation_required",
                    {
                        "state": result.get("confirmation_state"),
                        "status": "waiting_confirmation",
                    },
                )
                if result.get("log_path"):
                    self._update_job_log_path(job_id, str(result["log_path"]))
                return
            payload = {
                "generated_files": result.get("generated_files", []),
                "remaining_confirmation_state": result.get("remaining_confirmation_state"),
            }
            if result.get("log_path"):
                payload["log_path"] = result["log_path"]
                self._update_job_log_path(job_id, str(result["log_path"]))
            self.record_event(job_id, "completed", payload)
        except JobCancelled:
            self.record_event(job_id, "cancelled", {})
        except Exception as exc:
            self.record_event(
                job_id,
                "failed",
                {
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )

    def _update_job_log_path(self, job_id: str, log_path: str) -> None:
        with self._lock:
            record = self._records[job_id]
            record.log_path = log_path
            self._persist(record)

    def _update_generated_files(self, job_id: str, generated_files: list[str]) -> None:
        with self._lock:
            record = self._records[job_id]
            record.generated_files = generated_files
            self._persist(record)

    def start_background_job(
        self,
        job_id: str,
        runner: Callable[[Callable[[str, dict[str, Any]], None], Callable[[], bool]], dict[str, Any]],
        *,
        running_status: str,
    ) -> None:
        with self._lock:
            record = self._records[job_id]
            record.status = running_status
            if record.started_at is None:
                record.started_at = utc_now_iso()
            self._persist(record)

        thread = threading.Thread(target=self._run_background, args=(job_id, runner), daemon=True)
        thread.start()

    def subscribe(self, job_id: str) -> queue.Queue[dict[str, Any]]:
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue()
        with self._lock:
            if job_id not in self._records:
                raise KeyError(job_id)
            self._subscribers.setdefault(job_id, []).append(subscriber)
        return subscriber

    def unsubscribe(self, job_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            subscribers = self._subscribers.get(job_id)
            if not subscribers:
                return
            try:
                subscribers.remove(subscriber)
            except ValueError:
                return

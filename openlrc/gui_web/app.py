from __future__ import annotations

import argparse
import asyncio
import json
import queue
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..gui_qt.models import AppConfig
from .core.event_broker import EventBroker
from .core.job_manager import JobManager
from .services.config_service import load_web_config, save_web_config, serialize_config
from .services.dialog_service import choose_folder
from .services.file_service import clear_cache, list_output_files, open_folder
from .services.processing_service import run_prepare_job, run_translation_job
from .services.provider_service import list_provider_payloads, test_local_hymt_translation, validate_provider_selection
from .services.scan_service import build_scan_payload, scan_directory_for_web

app = FastAPI(title="OpenLRC Web", version="1.0.0")
job_manager = JobManager()
dashboard_events = EventBroker()
frontend_dir = Path(__file__).resolve().parent / "frontend"
if frontend_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dir / "static")), name="assets")

_LAST_SCAN: dict | None = None


def _empty_scan() -> dict:
    return {"root_dir": "", "audio_count": 0, "relative_paths": [], "tasks": [], "summary": [], "error": ""}


def _read_index_html() -> str:
    index_path = frontend_dir / "index.html"
    return index_path.read_text(encoding="utf-8")


def _config_from_payload(payload: dict) -> AppConfig:
    return AppConfig.from_dict(payload)


def _dashboard_snapshot() -> dict:
    config = load_web_config()
    return {
        "config": serialize_config(config),
        "scan": _LAST_SCAN or _empty_scan(),
        "jobs": [record.to_dict() for record in job_manager.list_jobs()],
        "providers": list_provider_payloads(config),
    }


def _publish_dashboard_event(event_type: str, payload: dict | None = None) -> None:
    dashboard_events.publish(event_type, payload or {})


def _publish_job_event(event: dict) -> None:
    payload = {
        "event": event,
        "job_id": event.get("job_id"),
        "jobs": [record.to_dict() for record in job_manager.list_jobs()],
    }
    if event.get("type") in {"completed", "failed", "cancelled"}:
        payload["outputs_changed"] = True
    _publish_dashboard_event("job_event", payload)


job_manager.set_event_listener(_publish_job_event)


def _sse(event_type: str, payload: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _next_sse_event(event_queue: queue.Queue, *, ping_interval: float, request: Request) -> dict | None:
    last_ping = time.monotonic()
    while True:
        if await request.is_disconnected():
            return None
        try:
            return event_queue.get_nowait()
        except queue.Empty:
            now = time.monotonic()
            if now - last_ping >= ping_interval:
                return {"type": "ping", "payload": {}}
            await asyncio.sleep(0.25)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _read_index_html()


@app.get("/api/config")
def api_get_config() -> dict:
    config = load_web_config()
    return serialize_config(config)


@app.put("/api/config")
def api_save_config(payload: dict) -> dict:
    config = save_web_config(payload)
    data = serialize_config(config)
    _publish_dashboard_event("config_changed", {"config": data, "providers": list_provider_payloads(config)})
    return data


@app.post("/api/config/validate")
def api_validate_config(payload: dict) -> dict:
    config = _config_from_payload(payload)
    errors = validate_provider_selection(config)
    return {"ok": not errors, "errors": errors}


@app.get("/api/scan/last")
def api_last_scan() -> dict:
    return _LAST_SCAN or _empty_scan()


@app.post("/api/scan")
def api_scan(payload: dict) -> dict:
    config = _config_from_payload(payload)
    scan_result = scan_directory_for_web(config.scan_root_dir)
    data = build_scan_payload(config, scan_result)
    global _LAST_SCAN
    _LAST_SCAN = data
    _publish_dashboard_event("scan_changed", {"scan": data})
    return data


@app.get("/api/providers")
def api_providers() -> dict:
    config = load_web_config()
    return {"providers": list_provider_payloads(config)}


@app.post("/api/providers/validate")
def api_validate_provider(payload: dict) -> dict:
    config = _config_from_payload(payload)
    errors = validate_provider_selection(config)
    return {"ok": not errors, "errors": errors}


@app.post("/api/providers/preview")
def api_preview_providers(payload: dict) -> dict:
    config = _config_from_payload(payload)
    return {"providers": list_provider_payloads(config)}


@app.post("/api/providers/local-hymt/test")
def api_local_hymt_test(payload: dict) -> dict:
    config = _config_from_payload(payload)
    sample_text = str(payload.get("sample_text") or "Hello, this is a test.")
    try:
        return test_local_hymt_translation(config, sample_text)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/dialogs/folder")
def api_choose_folder(payload: dict) -> dict:
    initial_dir = str(payload.get("initial_dir") or "").strip()
    try:
        return choose_folder(initial_dir)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/jobs")
def api_list_jobs() -> dict:
    return {"jobs": [record.to_dict() for record in job_manager.list_jobs()]}


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: str) -> dict:
    record = job_manager.get_job(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    return record.to_dict()


@app.post("/api/jobs")
def api_create_job(payload: dict) -> dict:
    config = _config_from_payload(payload)
    if not config.scan_root_dir.strip():
        raise HTTPException(status_code=400, detail="请先填写根目录。")
    errors = validate_provider_selection(config)
    if errors:
        raise HTTPException(status_code=400, detail="配置校验失败：" + "；".join(errors))
    record = job_manager.create_job(config.scan_root_dir, config.to_dict())

    def runner(emit, is_cancelled):
        return run_prepare_job(config, emit, is_cancelled)

    job_manager.start_background_job(record.id, runner, running_status="preparing")
    _publish_dashboard_event("job_changed", {"job_id": record.id, "jobs": [item.to_dict() for item in job_manager.list_jobs()]})
    return {"job": record.to_dict()}


@app.post("/api/jobs/{job_id}/confirm")
def api_confirm_job(job_id: str, payload: dict) -> dict:
    record = job_manager.get_job(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    if not record.confirmation_state:
        raise HTTPException(status_code=400, detail="当前任务没有待确认的翻译状态。")

    selected_paths = [str(item) for item in payload.get("selected_relative_paths", []) if str(item).strip()]
    if not selected_paths:
        raise HTTPException(status_code=400, detail="请选择至少一个文件。")

    config = AppConfig.from_dict(record.config_snapshot)
    errors = validate_provider_selection(config)
    if errors:
        raise HTTPException(status_code=400, detail="配置校验失败：" + "；".join(errors))

    def runner(emit, is_cancelled):
        return run_translation_job(config, record.confirmation_state or {}, selected_paths, emit, is_cancelled)

    job_manager.record_event(job_id, "selection", {"selected_relative_paths": selected_paths})
    job_manager.record_event(job_id, "status", {"status": "translating"})
    job_manager.start_background_job(job_id, runner, running_status="translating")
    _publish_dashboard_event("job_changed", {"job_id": job_id, "jobs": [item.to_dict() for item in job_manager.list_jobs()]})
    return {"ok": True, "job": job_manager.snapshot(job_id)}


@app.post("/api/jobs/{job_id}/cancel")
def api_cancel_job(job_id: str) -> dict:
    try:
        record = job_manager.cancel_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    _publish_dashboard_event("job_changed", {"job_id": job_id, "jobs": [item.to_dict() for item in job_manager.list_jobs()]})
    return {"ok": True, "job": record.to_dict()}


@app.post("/api/jobs/{job_id}/retry")
def api_retry_job(job_id: str) -> dict:
    record = job_manager.get_job(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    if record.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=400, detail="只有失败或取消的任务可以重试。")
    config = AppConfig.from_dict(record.config_snapshot)
    new_record = job_manager.create_job(record.root_dir, config.to_dict())

    def runner(emit, is_cancelled):
        return run_prepare_job(config, emit, is_cancelled)

    job_manager.start_background_job(new_record.id, runner, running_status="preparing")
    _publish_dashboard_event("job_changed", {"job_id": new_record.id, "jobs": [item.to_dict() for item in job_manager.list_jobs()]})
    return {"ok": True, "job": new_record.to_dict()}


@app.get("/api/jobs/{job_id}/events")
def api_job_events(job_id: str, request: Request) -> StreamingResponse:
    record = job_manager.get_job(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    event_queue = job_manager.subscribe(job_id)

    async def event_stream():
        yield _sse("hello", {})
        try:
            while True:
                event = await _next_sse_event(event_queue, ping_interval=15, request=request)
                if event is None:
                    break
                yield _sse(event["type"], event)
                if event["type"] in {"completed", "failed", "cancelled"}:
                    break
        except asyncio.CancelledError:
            return
        finally:
            job_manager.unsubscribe(job_id, event_queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/events/dashboard")
def api_dashboard_events(request: Request) -> StreamingResponse:
    event_queue = dashboard_events.subscribe()

    async def event_stream():
        snapshot = {"type": "dashboard_snapshot", "payload": _dashboard_snapshot()}
        yield _sse("dashboard_snapshot", snapshot)
        try:
            while True:
                event = await _next_sse_event(event_queue, ping_interval=20, request=request)
                if event is None:
                    break
                yield _sse(event["type"], event)
        except asyncio.CancelledError:
            return
        finally:
            dashboard_events.unsubscribe(event_queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/files/outputs")
def api_outputs(root_dir: str) -> dict:
    return list_output_files(root_dir)


@app.post("/api/files/open-folder")
def api_open_folder(payload: dict) -> dict:
    path = str(payload.get("path") or "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="path is required")
    try:
        return open_folder(path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/files/clear-cache")
def api_clear_cache(payload: dict) -> dict:
    root_dir = str(payload.get("root_dir") or "").strip()
    if not root_dir:
        raise HTTPException(status_code=400, detail="root_dir is required")
    try:
        result = clear_cache(root_dir)
        _publish_dashboard_event("cache_changed", {"root_dir": root_dir, "outputs_changed": True})
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/files/logs/{job_id}")
def api_job_log(job_id: str) -> PlainTextResponse:
    record = job_manager.get_job(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    if not record.log_path:
        raise HTTPException(status_code=404, detail="log not available")
    log_path = Path(record.log_path)
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="log not found")
    return PlainTextResponse(log_path.read_text(encoding="utf-8", errors="ignore"))


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    parser = argparse.ArgumentParser(description="OpenLRC Web")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8502)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    try:
        uvicorn.run(
            "openlrc.gui_web.app:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            factory=False,
            lifespan="off",
        )
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

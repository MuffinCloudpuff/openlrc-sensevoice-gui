from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from ...gui_qt.models import PROJECT_ROOT
from ..core.path_policy import ensure_existing_directory


def list_output_files(root_dir_text: str) -> dict:
    root = ensure_existing_directory(root_dir_text, field_name="root_dir")
    files: list[dict] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix not in {".lrc", ".srt", ".json", ".log"}:
            continue
        if ".openlrc_cache" in path.parts:
            continue
        files.append(
            {
                "path": str(path),
                "relative_path": str(path.relative_to(root)),
                "name": path.name,
                "suffix": suffix,
                "size": path.stat().st_size,
            }
        )
    return {"root_dir": str(root), "files": files}


def open_folder(path_text: str) -> dict:
    path = Path(path_text).expanduser().resolve()
    if sys.platform.startswith("win"):
        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])
    return {"ok": True, "path": str(path)}


def clear_cache(root_dir_text: str) -> dict:
    root = ensure_existing_directory(root_dir_text, field_name="root_dir")
    removed: list[str] = []
    candidates = [
        root / ".openlrc_cache",
        root / "preprocessed",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            shutil.rmtree(candidate)
            removed.append(str(candidate))
    return {"ok": True, "removed": removed}


def get_job_log_path(job_log_path: str) -> Path:
    path = Path(job_log_path).expanduser().resolve()
    path.relative_to(PROJECT_ROOT)
    return path

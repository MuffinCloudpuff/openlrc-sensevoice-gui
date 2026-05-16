from __future__ import annotations

from pathlib import Path


def normalize_user_path(path_text: str | Path) -> Path:
    return Path(path_text).expanduser().resolve()


def ensure_existing_directory(path_text: str | Path, *, field_name: str = "path") -> Path:
    path = normalize_user_path(path_text)
    if not path.exists() or not path.is_dir():
        raise ValueError(f"{field_name} 不是有效目录：{path}")
    return path


def ensure_existing_file(path_text: str | Path, *, field_name: str = "path") -> Path:
    path = normalize_user_path(path_text)
    if not path.exists() or not path.is_file():
        raise ValueError(f"{field_name} 不是有效文件：{path}")
    return path


def ensure_child_path(root: Path, candidate: Path) -> Path:
    root = root.expanduser().resolve()
    candidate = candidate.expanduser().resolve()
    candidate.relative_to(root)
    return candidate

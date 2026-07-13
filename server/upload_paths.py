"""插件资源上传路径校验。"""

from __future__ import annotations

import re
from os import PathLike
from pathlib import Path

from core.config import PROJECT_ROOT


def sanitize_upload_path_segment(value: str | PathLike[str] | None, fallback: str = "file") -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip()).strip("._")
    return sanitized or fallback


def resolve_project_relative_dir(value: str | None, default: str = "uploads") -> Path:
    raw_value = str(value or default).strip().replace("\\", "/").strip("/")
    relative_dir = Path(raw_value or default)
    if relative_dir.is_absolute() or any(part == ".." for part in relative_dir.parts):
        raise ValueError("上传目录必须是项目根目录下的相对路径")
    resolved_dir = (PROJECT_ROOT / relative_dir).resolve()
    project_root = PROJECT_ROOT.resolve()
    if resolved_dir != project_root and project_root not in resolved_dir.parents:
        raise ValueError("上传目录超出项目根目录范围")
    return resolved_dir

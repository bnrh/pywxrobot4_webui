"""通用字段规范化工具。"""

from __future__ import annotations

from typing import Any


def normalize_text(value: Any) -> str:
    return "" if value in (None, "") else str(value).strip()


def normalize_wxpid(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped, 16) if stripped.lower().startswith("0x") else int(stripped)
        except ValueError:
            return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

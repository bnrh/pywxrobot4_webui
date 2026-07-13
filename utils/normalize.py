"""通用字段规范化工具。"""

from __future__ import annotations

import re
from typing import Any

TRUTHY_VALUES = frozenset({"1", "true", "yes", "on", "y", "是"})
FALSY_VALUES = frozenset({"", "0", "false", "no", "off", "n", "否"})


def normalize_text(value: Any) -> str:
    """去掉首尾空白；None/空串返回空字符串。"""
    return "" if value in (None, "") else str(value).strip()


def collapse_whitespace(value: Any) -> str:
    """折叠连续空白为一格，并去掉首尾空白。插件侧文本归一化优先用此函数。"""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_wxpid(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
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


def is_truthy(value: Any, default: bool = False) -> bool:
    """解析常见真值表达；None/空串返回 default。"""
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in TRUTHY_VALUES:
        return True
    if text in FALSY_VALUES:
        return False
    return default

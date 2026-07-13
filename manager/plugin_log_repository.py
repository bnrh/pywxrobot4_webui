"""插件日志仓储：SQLite 为权威数据源，内存 deque 仅作计数与最近缓存。"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from itertools import count
from pathlib import Path
from typing import Any

from manager.plugin_log_store import PluginLogStore


class PluginLogRepository:
    """统一插件日志读写，避免 runtime 层手动双写漂移。"""

    def __init__(self, *, limit: int = 1000, db_path: str | Path | None = None):
        self.limit = max(1, int(limit))
        self._store = PluginLogStore(db_path=db_path, limit=self.limit)
        self._cache: deque[dict[str, Any]] = deque()
        self._id_sequence = count(1)
        self._reload_cache_from_store()

    @property
    def store(self) -> PluginLogStore:
        return self._store

    @property
    def cached_logs(self) -> deque[dict[str, Any]]:
        """最新日志在左侧。"""
        return self._cache

    def __len__(self) -> int:
        return len(self._cache)

    def next_internal_id(self) -> int:
        return next(self._id_sequence)

    def _reload_cache_from_store(self) -> None:
        stored_logs, _ = self._store.load_recent(self.limit)
        self._cache.clear()
        # store 返回 internal_id DESC（最新在前）；append 后左侧为最新。
        for item in stored_logs:
            self._cache.append(deepcopy(item))
        if stored_logs:
            max_internal_id = max(int(item.get("internal_id") or 0) for item in stored_logs)
            self._id_sequence = count(max_internal_id + 1)

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        stored = deepcopy(record)
        self._store.append_log(stored)
        cached = deepcopy(stored)
        while len(self._cache) >= self.limit:
            self._cache.pop()
        self._cache.appendleft(cached)
        return cached

    def load_recent(
        self,
        limit: int,
        *,
        module_name: str | None = None,
        level: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        # 带筛选的查询仍以 SQLite 为准，保证过滤语义一致。
        return self._store.load_recent(
            limit,
            module_name=module_name,
            level=level,
            keyword=keyword,
        )

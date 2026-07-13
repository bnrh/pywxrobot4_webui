"""最近消息仓储：SQLite 为权威数据源，内存 deque 仅作有序缓存。"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from itertools import count
from pathlib import Path
from typing import Any

from messaging.store import RecentMessageStore


class MessageRepository:
    """统一消息读写，避免 runtime 层手动双写漂移。"""

    def __init__(self, *, limit: int = 200, db_path: str | Path | None = None):
        self.limit = max(1, int(limit))
        self._store = RecentMessageStore(db_path=db_path, limit=self.limit)
        self._cache: deque[dict[str, Any]] = deque()
        self._by_id: dict[int, dict[str, Any]] = {}
        self._id_sequence = count(1)
        self._reload_cache_from_store()

    @property
    def store(self) -> RecentMessageStore:
        return self._store

    @property
    def cached_messages(self) -> deque[dict[str, Any]]:
        """最新消息在左侧，与历史 API 的 recent_messages 语义一致。"""
        return self._cache

    def __len__(self) -> int:
        return len(self._cache)

    def next_internal_id(self) -> int:
        return next(self._id_sequence)

    def _reload_cache_from_store(self) -> None:
        stored_messages = self._store.load_recent(self.limit)
        self._cache.clear()
        self._by_id.clear()
        # store 返回 internal_id DESC（最新在前）；append 后左侧为最新。
        for item in stored_messages:
            record = deepcopy(item)
            self._cache.append(record)
            self._by_id[int(record["internal_id"])] = record
        if stored_messages:
            max_internal_id = max(int(item.get("internal_id") or 0) for item in stored_messages)
            self._id_sequence = count(max_internal_id + 1)

    def _remember_in_cache(self, record: dict[str, Any]) -> None:
        internal_id = int(record["internal_id"])
        existing = self._by_id.get(internal_id)
        if existing is not None:
            existing.clear()
            existing.update(record)
            return
        while len(self._cache) >= self.limit:
            evicted = self._cache.pop()
            self._by_id.pop(int(evicted.get("internal_id") or 0), None)
        self._cache.appendleft(record)
        self._by_id[internal_id] = record

    def upsert(self, record: dict[str, Any]) -> dict[str, Any]:
        stored = deepcopy(record)
        self._store.upsert_message(stored)
        cached = deepcopy(stored)
        self._remember_in_cache(cached)
        return cached

    def patch(self, internal_id: int, **updates: Any) -> dict[str, Any] | None:
        if not updates:
            return self.get(internal_id)
        self._store.patch_message(internal_id, **updates)
        cached = self._by_id.get(int(internal_id))
        if cached is not None:
            cached.update(updates)
            return cached
        # 缓存未命中时（理论上刚写入应在缓存内），从 DB 回填，避免读路径漂移。
        refreshed = self._load_one_from_store(int(internal_id))
        if refreshed is None:
            return None
        self._remember_in_cache(refreshed)
        return refreshed

    def _load_one_from_store(self, internal_id: int) -> dict[str, Any] | None:
        for item in self._store.load_recent(self.limit):
            if int(item.get("internal_id") or 0) == internal_id:
                return deepcopy(item)
        return None

    def get(self, internal_id: int) -> dict[str, Any] | None:
        cached = self._by_id.get(int(internal_id))
        if cached is not None:
            return cached
        return self._load_one_from_store(int(internal_id))

    def list_recent(self, limit: int | None = None) -> list[dict[str, Any]]:
        effective_limit = self.limit if limit is None else max(1, int(limit))
        return [dict(item) for item in list(self._cache)[:effective_limit]]

    def record_queue_rejection(self, internal_id: int, reason: str) -> None:
        self._store.record_queue_rejection(internal_id, reason)

    def count_queue_rejections(self) -> int:
        return self._store.count_queue_rejections()

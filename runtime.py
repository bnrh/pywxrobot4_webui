"""插件运行时：消息队列、心跳、手动执行与持久化。"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from loguru import logger

from client import WxRobotApiClient
from config import PluginServiceSettings, normalize_plugin_module_name
from contact_directory_cache import ContactDirectoryCache
from manager import PluginManager
from message import MessageEvent
from message_repository import MessageRepository
from plugin_base import PluginContext, PluginLogger
from plugin_log_repository import PluginLogRepository
from runtime_events import RuntimeEventHub

RECENT_MESSAGE_LIMIT = 200
PLUGIN_LOG_LIMIT = 1000
MANUAL_PLUGIN_EXECUTION_TERMINAL_STATUSES = {"completed", "failed", "stopped"}
MANUAL_PLUGIN_EXECUTION_ACTIVE_STATUSES = {"queued", "running", "stopping"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class PluginRuntime:
    def __init__(self, settings: PluginServiceSettings):
        self.settings = settings
        self.api_client = WxRobotApiClient(settings.wxrobot_api_base_url, settings.request_timeout)
        self.directory_cache = ContactDirectoryCache(self.api_client)
        self.context = PluginContext(
            settings=settings,
            api_client=self.api_client,
            login_account_cache_getter=self.get_cached_login_accounts,
            login_account_cache_refresher=self.refresh_login_account_cache,
            login_account_serializer=self._serialize_login_accounts,
        )
        self.manager = PluginManager(
            self.context,
            settings.plugins,
            settings.plugin_settings,
            plugin_log_sink=self._remember_plugin_log,
        )
        self.queue: asyncio.Queue[tuple[int, MessageEvent] | None] = asyncio.Queue(maxsize=settings.queue_size)
        self._workers: list[asyncio.Task] = []
        self.message_repository = MessageRepository(limit=RECENT_MESSAGE_LIMIT)
        self.plugin_log_repository = PluginLogRepository(limit=PLUGIN_LOG_LIMIT)
        # 兼容旧读路径：recent_* 指向仓储缓存；message_store/plugin_log_store 指向底层 SQLite。
        self.recent_messages = self.message_repository.cached_messages
        self.recent_plugin_logs = self.plugin_log_repository.cached_logs
        self.message_store = self.message_repository.store
        self.plugin_log_store = self.plugin_log_repository.store
        self.started_at: datetime | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._manual_plugin_execution_lock = asyncio.Lock()
        self._manual_plugin_executions: dict[str, dict[str, Any]] = {}
        self._manual_plugin_execution_tasks: dict[str, asyncio.Task[Any]] = {}
        self.heartbeat_accounts: list[dict[str, Any]] = []
        self.heartbeat_last_checked_at: datetime | None = None
        self.heartbeat_error = ""
        self.heartbeat_healthy: bool | None = None
        self._plugin_targets_cache_at = 0.0
        self._plugin_targets_cache: dict[str, Any] | None = None
        self.event_hub = RuntimeEventHub()
        self.wxrobot_api_reachable: bool | None = None

    async def publish_runtime_event(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        await self.event_hub.publish(event_type, payload)

    async def apply_light_settings(self, configured_settings: PluginServiceSettings, fields: list[str]) -> None:
        if not fields:
            return
        updates = {field: getattr(configured_settings, field) for field in fields}
        next_settings = self.settings.model_copy(update=updates)
        if {"wxrobot_api_base_url", "request_timeout"} & set(fields):
            await self.api_client.aclose()
            self.api_client = WxRobotApiClient(next_settings.wxrobot_api_base_url, next_settings.request_timeout)
            self.directory_cache = ContactDirectoryCache(self.api_client)
            self.context = PluginContext(
                settings=next_settings,
                api_client=self.api_client,
                login_account_cache_getter=self.get_cached_login_accounts,
                login_account_cache_refresher=self.refresh_login_account_cache,
                login_account_serializer=self._serialize_login_accounts,
            )
        else:
            self.context.settings = next_settings
        self.settings = next_settings
        self.manager.context = self.context

    @staticmethod
    def _serialize_login_accounts(users: list[dict[str, Any]]) -> list[dict[str, Any]]:
        accounts: list[dict[str, Any]] = []
        for item in users or []:
            wxid = str(item.get("wxid") or "").strip()
            wxh = str(item.get("wxh") or item.get("alias") or "").strip()
            nickname = str(item.get("nickname") or "").strip()
            wxpid = item.get("wxpid")
            if wxpid in (None, ""):
                wxpid = item.get("pid")
            display_name = nickname or wxh or wxid or "未命名账号"
            accounts.append(
                {
                    "display_name": display_name,
                    "nickname": nickname,
                    "wxid": wxid,
                    "wxh": wxh,
                    "wxpid": wxpid,
                }
            )
        return accounts

    def _clear_heartbeat_state(self) -> None:
        self.heartbeat_accounts = []
        self.heartbeat_last_checked_at = None
        self.heartbeat_error = ""
        self.heartbeat_healthy = None

    def _resolve_plugin_log_identity(self, module_name: str) -> tuple[str, str]:
        normalized_module_name = normalize_plugin_module_name(module_name)
        for plugin in self.manager.plugins:
            if normalize_plugin_module_name(getattr(plugin, "module_name", "")) != normalized_module_name:
                continue
            plugin_name = str(getattr(plugin, "name", "") or "").strip()
            if plugin_name:
                return normalized_module_name, plugin_name

        metadata_list = PluginManager.describe_modules([normalized_module_name])
        if metadata_list:
            plugin_name = str(metadata_list[0].get("name") or "").strip()
            if plugin_name:
                return normalized_module_name, plugin_name

        fallback_name = normalized_module_name.rsplit(".", 1)[-1] if normalized_module_name else "plugin"
        return normalized_module_name, fallback_name

    @staticmethod
    def _should_log_manual_plugin_execution_transition(previous_payload: dict[str, Any], current_payload: dict[str, Any]) -> bool:
        previous_status = str(previous_payload.get("status") or "idle").strip().lower()
        current_status = str(current_payload.get("status") or "idle").strip().lower()
        if current_status == "idle":
            return False
        return (
            previous_status != current_status
            or str(previous_payload.get("detail") or "").strip() != str(current_payload.get("detail") or "").strip()
            or str(previous_payload.get("error") or "").strip() != str(current_payload.get("error") or "").strip()
        )

    @staticmethod
    def _build_manual_plugin_execution_log_message(payload: dict[str, Any]) -> tuple[str, str]:
        status = str(payload.get("status") or "idle").strip().lower()
        detail = str(payload.get("detail") or "").strip()
        error = str(payload.get("error") or "").strip()

        if status == "completed":
            return "INFO", f"执行完成：{detail}" if detail else "执行完成"
        if status == "failed":
            return "ERROR", detail or error or "执行失败"
        if status == "stopped":
            return "INFO", detail or "插件已停止"
        if status == "stopping":
            return "INFO", detail or "正在停止插件..."
        if status == "running":
            return "INFO", detail or "插件正在执行..."
        if status == "queued":
            return "INFO", detail or "插件已开始执行"
        return "INFO", detail or "插件状态已更新"

    def _log_manual_plugin_execution_transition(self, module_name: str, payload: dict[str, Any]) -> None:
        normalized_module_name, plugin_name = self._resolve_plugin_log_identity(module_name)
        level, message = self._build_manual_plugin_execution_log_message(payload)
        logger_instance = PluginLogger(
            normalized_module_name,
            plugin_name,
            self._remember_plugin_log,
            scope="manual-execution",
        )
        log_data = {
            "status": str(payload.get("status") or "idle").strip().lower(),
            "detail": str(payload.get("detail") or "").strip(),
            "error": str(payload.get("error") or "").strip(),
            "started_at": str(payload.get("started_at") or "").strip(),
            "updated_at": str(payload.get("updated_at") or "").strip(),
        }
        result = payload.get("result")
        if isinstance(result, dict):
            result_detail = str(result.get("detail") or "").strip()
            if result_detail:
                log_data["result_detail"] = result_detail
            if "handled" in result:
                log_data["handled"] = bool(result.get("handled"))
            if "stop_processing" in result:
                log_data["stop_processing"] = bool(result.get("stop_processing"))

        if level == "ERROR":
            logger_instance.error(message, log_data)
            return
        logger_instance.info(message, log_data)

    def get_cached_login_accounts(self) -> list[dict[str, Any]]:
        return list(self.heartbeat_accounts)

    def _normalize_manual_plugin_execution_payload(self, module_name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_module_name = normalize_plugin_module_name(module_name)
        current = deepcopy(payload if isinstance(payload, dict) else self._manual_plugin_executions.get(normalized_module_name, {}))
        status = str(current.get("status") or "idle").strip().lower()
        valid_statuses = {"idle", *MANUAL_PLUGIN_EXECUTION_ACTIVE_STATUSES, *MANUAL_PLUGIN_EXECUTION_TERMINAL_STATUSES}
        if status not in valid_statuses:
            status = "idle"
        if status == "idle":
            return {
                "module": normalized_module_name,
                "status": "idle",
                "active": False,
                "detail": "",
                "error": "",
                "started_at": "",
                "updated_at": "",
                "result": None,
            }
        return {
            "module": normalized_module_name,
            "status": status,
            "active": status in MANUAL_PLUGIN_EXECUTION_ACTIVE_STATUSES,
            "detail": str(current.get("detail") or "").strip(),
            "error": str(current.get("error") or "").strip(),
            "started_at": str(current.get("started_at") or "").strip(),
            "updated_at": str(current.get("updated_at") or "").strip(),
            "result": deepcopy(current.get("result")) if isinstance(current.get("result"), dict) else current.get("result"),
        }

    async def _set_manual_plugin_execution(self, module_name: str, updates: dict[str, Any]) -> dict[str, Any]:
        normalized_module_name = normalize_plugin_module_name(module_name)
        async with self._manual_plugin_execution_lock:
            current = deepcopy(self._manual_plugin_executions.get(normalized_module_name, {}))
            previous_payload = self._normalize_manual_plugin_execution_payload(normalized_module_name, current)
            next_payload = {
                **current,
                **deepcopy(updates),
                "module": normalized_module_name,
                "updated_at": now_iso(),
            }
            if not str(next_payload.get("started_at") or "").strip() and str(next_payload.get("status") or "").strip().lower() != "idle":
                next_payload["started_at"] = now_iso()
            normalized_payload = self._normalize_manual_plugin_execution_payload(normalized_module_name, next_payload)
            self._manual_plugin_executions[normalized_module_name] = normalized_payload
        if self._should_log_manual_plugin_execution_transition(previous_payload, normalized_payload):
            self._log_manual_plugin_execution_transition(normalized_module_name, normalized_payload)
        return deepcopy(normalized_payload)

    async def _set_manual_plugin_execution_task(self, module_name: str, task: asyncio.Task[Any]) -> None:
        normalized_module_name = normalize_plugin_module_name(module_name)
        async with self._manual_plugin_execution_lock:
            self._manual_plugin_execution_tasks[normalized_module_name] = task

    async def _get_manual_plugin_execution_task(self, module_name: str) -> asyncio.Task[Any] | None:
        normalized_module_name = normalize_plugin_module_name(module_name)
        async with self._manual_plugin_execution_lock:
            return self._manual_plugin_execution_tasks.get(normalized_module_name)

    async def _pop_manual_plugin_execution_task(self, module_name: str) -> asyncio.Task[Any] | None:
        normalized_module_name = normalize_plugin_module_name(module_name)
        async with self._manual_plugin_execution_lock:
            return self._manual_plugin_execution_tasks.pop(normalized_module_name, None)

    async def get_manual_plugin_execution(self, module_name: str) -> dict[str, Any]:
        normalized_module_name = normalize_plugin_module_name(module_name)
        async with self._manual_plugin_execution_lock:
            payload = deepcopy(self._manual_plugin_executions.get(normalized_module_name, {}))
        return self._normalize_manual_plugin_execution_payload(normalized_module_name, payload)

    def get_manual_plugin_execution_snapshot(self, module_name: str) -> dict[str, Any]:
        normalized_module_name = normalize_plugin_module_name(module_name)
        return self._normalize_manual_plugin_execution_payload(
            normalized_module_name,
            deepcopy(self._manual_plugin_executions.get(normalized_module_name, {})),
        )

    async def _run_manual_plugin_execution(self, module_name: str, config_override: dict[str, Any] | None = None) -> None:
        normalized_module_name = normalize_plugin_module_name(module_name)
        await self._set_manual_plugin_execution(
            normalized_module_name,
            {
                "status": "running",
                "detail": "插件正在执行...",
                "error": "",
                "result": None,
            },
        )
        try:
            result = await self.manager.execute_plugin(normalized_module_name, dict(config_override or {}))
        except asyncio.CancelledError:
            await self._set_manual_plugin_execution(
                normalized_module_name,
                {
                    "status": "stopped",
                    "detail": "插件已停止",
                    "error": "",
                    "result": None,
                },
            )
            raise
        except ValueError as exc:
            await self._set_manual_plugin_execution(
                normalized_module_name,
                {
                    "status": "failed",
                    "detail": str(exc),
                    "error": str(exc),
                    "result": None,
                },
            )
        except Exception as exc:
            logger.exception("手动执行插件失败: {}", normalized_module_name)
            await self._set_manual_plugin_execution(
                normalized_module_name,
                {
                    "status": "failed",
                    "detail": f"执行插件失败: {exc}",
                    "error": str(exc),
                    "result": None,
                },
            )
        else:
            await self._set_manual_plugin_execution(
                normalized_module_name,
                {
                    "status": "completed",
                    "detail": str(result.get("detail") or "").strip() or "执行完成",
                    "error": "",
                    "result": result,
                },
            )
        finally:
            await self._pop_manual_plugin_execution_task(normalized_module_name)

    async def start_manual_plugin_execution(self, module_name: str, config_override: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_module_name = normalize_plugin_module_name(module_name)
        current = await self.get_manual_plugin_execution(normalized_module_name)
        if current.get("active"):
            raise ValueError("插件正在执行中")

        await self._set_manual_plugin_execution(
            normalized_module_name,
            {
                "status": "queued",
                "detail": "插件已开始执行",
                "error": "",
                "result": None,
            },
        )
        task = asyncio.create_task(
            self._run_manual_plugin_execution(normalized_module_name, dict(config_override or {})),
            name=f"manual-plugin-{normalized_module_name.rsplit('.', 1)[-1]}",
        )
        await self._set_manual_plugin_execution_task(normalized_module_name, task)
        return await self.get_manual_plugin_execution(normalized_module_name)

    async def stop_manual_plugin_execution(self, module_name: str) -> dict[str, Any]:
        normalized_module_name = normalize_plugin_module_name(module_name)
        current = await self.get_manual_plugin_execution(normalized_module_name)
        if not current.get("active"):
            raise ValueError("当前没有正在执行的插件")
        task = await self._get_manual_plugin_execution_task(normalized_module_name)
        if task is None:
            raise ValueError("当前没有正在执行的插件")

        await self._set_manual_plugin_execution(
            normalized_module_name,
            {
                "status": "stopping",
                "detail": "正在停止插件...",
                "error": "",
            },
        )
        task.cancel()
        return await self.get_manual_plugin_execution(normalized_module_name)

    async def _cancel_manual_plugin_executions(self) -> None:
        async with self._manual_plugin_execution_lock:
            tasks = list(self._manual_plugin_execution_tasks.items())
        for module_name, task in tasks:
            if task.done():
                continue
            await self._set_manual_plugin_execution(
                module_name,
                {
                    "status": "stopping",
                    "detail": "正在停止插件...",
                    "error": "",
                },
            )
            task.cancel()
        if tasks:
            await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)

    async def refresh_login_account_cache(self, users: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        self.heartbeat_last_checked_at = datetime.now().astimezone()
        login_users = users if isinstance(users, list) else None
        try:
            if login_users is None:
                login_users = await self.api_client.get_logged_in_users()
            await self.api_client.get_wx_pids()
            self.wxrobot_api_reachable = True
        except Exception as exc:
            self.heartbeat_error = str(exc)
            self.heartbeat_healthy = False
            self.wxrobot_api_reachable = False
            return list(self.heartbeat_accounts)

        self.heartbeat_accounts = self._serialize_login_accounts(login_users if isinstance(login_users, list) else [])
        self.heartbeat_error = ""
        self.heartbeat_healthy = True
        self.wxrobot_api_reachable = True
        return list(self.heartbeat_accounts)

    async def _run_heartbeat_check(self) -> None:
        await self.refresh_login_account_cache()

    async def _heartbeat_loop(self) -> None:
        while True:
            interval_seconds = max(0, int(getattr(self.settings, "heartbeat_interval_seconds", 0) or 0))
            if interval_seconds <= 0:
                self._clear_heartbeat_state()
                await asyncio.sleep(1)
                continue

            await self._run_heartbeat_check()
            await asyncio.sleep(interval_seconds)

    async def start(self) -> None:
        if self.started_at is None:
            self.started_at = datetime.now().astimezone()
        await self.manager.load_plugins()
        await self.directory_cache.warmup()
        if self.settings.heartbeat_interval_seconds > 0:
            await self._run_heartbeat_check()
        else:
            self._clear_heartbeat_state()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(), name="plugin-heartbeat")
        self._workers = [
            asyncio.create_task(self._worker(index), name=f"plugin-worker-{index}")
            for index in range(self.settings.worker_count)
        ]
        logger.info("插件服务已启动，消息回调地址: {}", self.settings.callback_url)

    async def reload(self, settings: PluginServiceSettings | None = None) -> None:
        await self._cancel_manual_plugin_executions()
        next_settings = settings or PluginServiceSettings.from_storage()
        next_api_client = WxRobotApiClient(next_settings.wxrobot_api_base_url, next_settings.request_timeout)
        next_directory_cache = ContactDirectoryCache(next_api_client)
        next_context = PluginContext(
            settings=next_settings,
            api_client=next_api_client,
            login_account_cache_getter=self.get_cached_login_accounts,
            login_account_cache_refresher=self.refresh_login_account_cache,
            login_account_serializer=self._serialize_login_accounts,
        )
        next_manager = PluginManager(
            next_context,
            next_settings.plugins,
            next_settings.plugin_settings,
            plugin_log_sink=self._remember_plugin_log,
        )
        await next_manager.load_plugins()
        await next_directory_cache.warmup()

        old_manager = self.manager
        old_api_client = self.api_client
        self.settings = next_settings
        self.api_client = next_api_client
        self.directory_cache = next_directory_cache
        self.context = next_context
        self.manager = next_manager
        await self.invalidate_plugin_targets_cache()
        await old_manager.shutdown()
        await old_api_client.aclose()
        logger.info("插件配置已重载，当前启用插件: {}", [plugin.name for plugin in self.manager.plugins])

    async def stop(self) -> None:
        await self._cancel_manual_plugin_executions()
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            await asyncio.gather(self._heartbeat_task, return_exceptions=True)
            self._heartbeat_task = None
        for _ in self._workers:
            await self.queue.put(None)
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        await self.manager.shutdown()
        await self.api_client.aclose()

    async def enqueue(self, event: MessageEvent) -> int:
        internal_id = self._remember_message(event)
        await self.publish_runtime_event(
            "message_queued",
            {
                "internal_id": internal_id,
                "msgid": event.normalized_msgid,
                "conversation_wxid": event.conversation_wxid,
            },
        )
        try:
            self.queue.put_nowait((internal_id, event))
        except asyncio.QueueFull:
            wait_seconds = max(0.0, float(self.settings.queue_enqueue_wait_seconds))
            rejection_error = "插件消息队列已满"
            if wait_seconds <= 0:
                await self._reject_queue_enqueue(internal_id, rejection_error)
                raise HTTPException(status_code=503, detail=rejection_error)
            try:
                await asyncio.wait_for(self.queue.put((internal_id, event)), timeout=wait_seconds)
            except asyncio.TimeoutError as exc:
                await self._reject_queue_enqueue(internal_id, rejection_error)
                raise HTTPException(status_code=503, detail=rejection_error) from exc
        return internal_id

    def _remember_message(self, event: MessageEvent) -> int:
        internal_id = self.message_repository.next_internal_id()
        record = {
            "internal_id": internal_id,
            "received_at": self._now_iso(),
            "processed_at": None,
            "status": "queued",
            "error": "",
            "msgid": event.normalized_msgid,
            "conversation_wxid": event.conversation_wxid,
            "sender_wxid": event.sender_wxid,
            "msg_type": event.normalized_msg_type,
            "local_type": event.normalized_local_type,
            "wxpid": event.normalized_wxpid,
            "is_group_message": event.is_group_message,
            "content": event.normalized_content,
            "plugin_results": [],
            "payload": event.raw_payload,
        }
        self.message_repository.upsert(record)
        return internal_id

    def _patch_message(self, internal_id: int, **updates: Any) -> None:
        self.message_repository.patch(internal_id, **updates)

    def _now_iso(self) -> str:
        return now_iso()

    async def _reject_queue_enqueue(self, internal_id: int, rejection_error: str) -> None:
        self._patch_message(
            internal_id,
            status="rejected",
            processed_at=self._now_iso(),
            error=rejection_error,
        )
        self.message_repository.record_queue_rejection(internal_id, rejection_error)
        await self.publish_runtime_event(
            "message_failed",
            {"internal_id": internal_id, "error": rejection_error, "reason": "queue_full"},
        )

    def _remember_plugin_log(self, entry: dict[str, Any]) -> None:
        record = {
            "internal_id": self.plugin_log_repository.next_internal_id(),
            "recorded_at": self._now_iso(),
            "module": str(entry.get("module") or ""),
            "plugin": str(entry.get("plugin") or entry.get("module") or ""),
            "level": str(entry.get("level") or "INFO"),
            "scope": str(entry.get("scope") or ""),
            "message": str(entry.get("message") or ""),
            "data": entry.get("data"),
        }
        self.plugin_log_repository.append(record)

    def get_plugin_logs(self, limit: int, module_name: str | None = None, level: str | None = None, keyword: str | None = None) -> tuple[list[dict[str, Any]], int]:
        return self.plugin_log_repository.load_recent(
            limit,
            module_name=module_name,
            level=level,
            keyword=keyword,
        )

    async def get_message_views(self, limit: int) -> list[dict[str, Any]]:
        messages = self.message_repository.list_recent(limit)
        if not messages:
            return []
        return await asyncio.gather(*(self.directory_cache.enrich_message(item) for item in messages))

    async def invalidate_plugin_targets_cache(self) -> None:
        self._plugin_targets_cache = None
        self._plugin_targets_cache_at = 0.0

    async def _worker(self, index: int) -> None:
        while True:
            queued_item = await self.queue.get()
            try:
                if queued_item is None:
                    return

                internal_id, event = queued_item
                results = await self.manager.dispatch(event)
                self._patch_message(
                    internal_id,
                    status="processed",
                    processed_at=self._now_iso(),
                    plugin_results=results,
                )
                await self.publish_runtime_event(
                    "message_processed",
                    {
                        "internal_id": internal_id,
                        "msgid": event.normalized_msgid,
                        "plugin_result_count": len(results),
                    },
                )
                if results:
                    logger.debug(
                        "worker={} msgid={} plugins={}",
                        index,
                        event.normalized_msgid,
                        results,
                    )
            except Exception as exc:
                if queued_item is not None:
                    internal_id = queued_item[0]
                    self._patch_message(
                        internal_id,
                        status="failed",
                        processed_at=self._now_iso(),
                        error=str(exc),
                    )
                    await self.publish_runtime_event(
                        "message_failed",
                        {"internal_id": internal_id, "error": str(exc)},
                    )
                logger.exception("插件 worker 处理消息失败")
            finally:
                self.queue.task_done()


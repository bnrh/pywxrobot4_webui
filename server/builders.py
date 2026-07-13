"""控制台 API 响应组装。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from time import monotonic
from typing import Any

from fastapi import HTTPException

from server.app_config import (
    RESTART_REQUIRED_FIELDS,
    SECRET_SETTINGS_PLACEHOLDER,
    SYSTEM_SETTINGS_FIELDS,
)
from core.config import SETTINGS_DB_PATH, PluginServiceSettings, normalize_plugin_module_name
from runtime.contact_directory_cache import PLUGIN_TARGETS_CACHE_TTL_SECONDS
from server.log_reader import format_local_datetime
from manager import PluginManager
from manager.plugin_config_payload import normalize_plugin_config_for_payload
from runtime.engine import PLUGIN_LOG_LIMIT, PluginRuntime
from server.security import is_api_auth_enabled, is_callback_auth_enabled
from utils.normalize import normalize_wxpid


class AppBuilders:
    def __init__(self, runtime: PluginRuntime):
        self.runtime = runtime

    @staticmethod
    def sort_option_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(items, key=lambda item: (str(item.get("label") or "").lower(), str(item.get("value") or "").lower()))

    @staticmethod
    def build_room_member_options(room_members_payload: Any) -> list[dict[str, Any]]:
        member_options: list[dict[str, Any]] = []
        seen_member_wxids: set[str] = set()
        for item in room_members_payload if isinstance(room_members_payload, list) else []:
            if not isinstance(item, dict):
                continue
            member_wxid = str(item.get("username") or item.get("wxid") or "").strip()
            if not member_wxid or member_wxid in seen_member_wxids:
                continue
            seen_member_wxids.add(member_wxid)
            nick_name = str(item.get("nick_name") or "").strip()
            room_nick_name = str(item.get("room_nick_name") or "").strip()
            display_name = room_nick_name or nick_name or member_wxid
            member_options.append(
                {
                    "label": display_name,
                    "value": member_wxid,
                    "wxid": member_wxid,
                    "display_name": display_name,
                    "nick_name": nick_name,
                    "room_nick_name": room_nick_name,
                    "avatar_url": str(item.get("small_head_url") or item.get("big_head_url") or "").strip(),
                    "search_text": " ".join(part for part in [display_name, room_nick_name, nick_name, member_wxid] if part),
                }
            )
        return AppBuilders.sort_option_items(member_options)

    def build_plugin_payload(self) -> list[dict]:
        module_names = list(dict.fromkeys(PluginManager.discover_plugin_modules() + self.runtime.settings.plugins))
        plugin_descriptions = PluginManager.describe_modules(module_names)
        loaded_plugins = {
            getattr(plugin, "module_name", plugin.__class__.__module__): plugin
            for plugin in self.runtime.manager.plugins
        }
        payload: list[dict] = []
        for item in plugin_descriptions:
            loaded_plugin = loaded_plugins.get(item["module"])
            config = self.runtime.settings.plugin_settings.get(item["module"], {})
            if not config and loaded_plugin is not None:
                config = loaded_plugin.config
            config = normalize_plugin_config_for_payload(item["module"], config)
            payload.append(
                {
                    **item,
                    "enabled": item["module"] in self.runtime.settings.plugins,
                    "loaded": loaded_plugin is not None,
                    "config": config,
                    "config_schema": item.get("config_schema") or [],
                    "scope_targets": item.get("scope_targets") or [],
                    "direct_execute": bool(item.get("direct_execute", False)),
                    "message_summary": bool(item.get("message_summary", False)),
                    "manual_execution": self.runtime.get_manual_plugin_execution_snapshot(item["module"]),
                }
            )
        return payload

    def resolve_plugin_model_options_field(self, module_name: str, field_key: str = "", parent_field_key: str = "") -> dict[str, Any]:
        normalized_module_name = normalize_plugin_module_name(module_name)
        if not normalized_module_name:
            raise HTTPException(status_code=400, detail="插件模块不能为空")

        available_modules = set(PluginManager.discover_plugin_modules()) | set(self.runtime.settings.plugins)
        if normalized_module_name not in available_modules:
            raise HTTPException(status_code=404, detail="未找到指定插件模块")

        metadata_list = PluginManager.describe_modules([normalized_module_name])
        metadata = metadata_list[0] if metadata_list else None
        if not isinstance(metadata, dict):
            raise HTTPException(status_code=404, detail="未找到指定插件模块")
        if not metadata.get("loadable", True):
            raise HTTPException(status_code=400, detail=f"插件无法加载: {metadata.get('error') or '未知错误'}")

        normalized_field_key = str(field_key or "").strip().lower()
        normalized_parent_field_key = str(parent_field_key or "").strip().lower()
        config_schema = metadata.get("config_schema") if isinstance(metadata.get("config_schema"), list) else []

        def match_candidate(candidate_key: Any, candidate_parent_key: Any = "") -> bool:
            normalized_candidate_key = str(candidate_key or "").strip().lower()
            normalized_candidate_parent_key = str(candidate_parent_key or "").strip().lower()
            if normalized_field_key and normalized_candidate_key != normalized_field_key:
                return False
            if normalized_parent_field_key and normalized_candidate_parent_key != normalized_parent_field_key:
                return False
            return True

        model_field = None
        for field in config_schema:
            if not isinstance(field, dict):
                continue
            if str(field.get("options_source") or "").strip().lower() == "model_options" and match_candidate(field.get("key")):
                model_field = field
                break
            for column in field.get("columns") if isinstance(field.get("columns"), list) else []:
                if not isinstance(column, dict):
                    continue
                if str(column.get("options_source") or "").strip().lower() != "model_options":
                    continue
                if not match_candidate(column.get("key"), field.get("key")):
                    continue
                model_field = {
                    **column,
                    "__parent_field_key": field.get("key"),
                }
                break
            if isinstance(model_field, dict):
                break

        if not isinstance(model_field, dict):
            raise HTTPException(status_code=400, detail="当前插件未声明模型列表选项")
        return model_field

    async def build_plugin_target_payload(self) -> dict:
        now = monotonic()
        if (
            self.runtime._plugin_targets_cache is not None
            and now - self.runtime._plugin_targets_cache_at <= PLUGIN_TARGETS_CACHE_TTL_SECONDS
        ):
            return dict(self.runtime._plugin_targets_cache)

        users_payload = await self.runtime.api_client.get_logged_in_users()
        users = users_payload if isinstance(users_payload, list) else []
        wxpids: list[int] = []
        wxpid_options: list[dict[str, Any]] = []
        seen_wxpids: set[int] = set()
        for item in users:
            wxpid = normalize_wxpid(item.get("wxpid"))
            if wxpid is None or wxpid in seen_wxpids:
                continue
            seen_wxpids.add(wxpid)
            wxpids.append(wxpid)
            wxid = str(item.get("wxid") or "").strip()
            wxh = str(item.get("wxh") or item.get("alias") or "").strip()
            nickname = str(item.get("nickname") or item.get("remarks") or wxh or wxid or f"微信进程 {wxpid}").strip()
            search_parts = [nickname, wxh, wxid, str(wxpid)]
            wxpid_options.append(
                {
                    "label": f"{nickname}({wxpid})",
                    "search_text": " ".join(part for part in search_parts if part),
                    "value": wxpid,
                }
            )

        room_options: list[dict[str, Any]] = []
        label_options: list[dict[str, Any]] = []
        seen_rooms: set[str] = set()
        seen_labels: set[str] = set()

        async def _fetch_rooms_and_labels(wxpid: int) -> tuple[Any, Any]:
            return await asyncio.gather(
                self.runtime.api_client.get_room_list(wxpid=wxpid),
                self.runtime.api_client.get_labels(wxpid=wxpid),
                return_exceptions=True,
            )

        per_wxpid_payloads = await asyncio.gather(*(_fetch_rooms_and_labels(wxpid) for wxpid in wxpids))
        for wxpid, (room_payload, label_payload) in zip(wxpids, per_wxpid_payloads):
            if not isinstance(room_payload, Exception) and isinstance(room_payload, list):
                for room in room_payload:
                    roomid = str(room.get("wxid") or room.get("roomid") or "").strip()
                    if not roomid or roomid in seen_rooms:
                        continue
                    room_name = str(room.get("nickname") or room.get("remarks") or "").strip()
                    if room_name == "":
                        continue
                    seen_rooms.add(roomid)
                    room_options.append(
                        {
                            "label": f"{room_name}({roomid})",
                            "search_text": room_name,
                            "value": roomid,
                            "wxpid": wxpid,
                        }
                    )

            if not isinstance(label_payload, Exception) and isinstance(label_payload, dict):
                for label_name in label_payload:
                    normalized_name = str(label_name or "").strip()
                    if not normalized_name or normalized_name in seen_labels:
                        continue
                    seen_labels.add(normalized_name)
                    label_options.append(
                        {
                            "label": normalized_name,
                            "search_text": normalized_name,
                            "value": normalized_name,
                        }
                    )

        payload = {
            "default_wxpid": wxpids[0] if wxpids else None,
            "wxpid_options": AppBuilders.sort_option_items(wxpid_options),
            "room_options": AppBuilders.sort_option_items(room_options),
            "label_options": AppBuilders.sort_option_items(label_options),
        }
        self.runtime._plugin_targets_cache = payload
        self.runtime._plugin_targets_cache_at = monotonic()
        return dict(payload)

    def build_user_payload(self) -> dict:
        heartbeat_interval_seconds = max(0, int(getattr(self.runtime.settings, "heartbeat_interval_seconds", 0) or 0))
        return {
            "enabled": heartbeat_interval_seconds > 0,
            "interval_seconds": heartbeat_interval_seconds,
            "healthy": self.runtime.heartbeat_healthy,
            "last_checked_at": format_local_datetime(self.runtime.heartbeat_last_checked_at),
            "total": len(self.runtime.heartbeat_accounts),
            "users": list(self.runtime.heartbeat_accounts),
            "error": self.runtime.heartbeat_error,
        }

    def build_overview(self) -> dict:
        settings_payload = self.build_settings_payload()
        uptime_seconds = int((datetime.now().astimezone() - self.runtime.started_at).total_seconds()) if self.runtime.started_at else 0
        user_payload = self.build_user_payload()
        active_workers = sum(1 for task in self.runtime._workers if not task.done())
        rejected_count = self.runtime.message_store.count_queue_rejections()
        return {
            "name": "wxrobot_api webui plugin server",
            "settings_storage_path": str(SETTINGS_DB_PATH),
            "callback_url": self.runtime.settings.callback_url,
            "wxrobot_api_base_url": self.runtime.settings.wxrobot_api_base_url,
            "listen_host": self.runtime.settings.host,
            "listen_port": self.runtime.settings.port,
            "plugins": [plugin.name for plugin in self.runtime.manager.plugins],
            "queue_size": self.runtime.settings.queue_size,
            "queued_messages": self.runtime.queue.qsize(),
            "worker_count": self.runtime.settings.worker_count,
            "enabled_plugin_count": len(self.runtime.settings.plugins),
            "loaded_plugin_count": len(self.runtime.manager.plugins),
            "pending_restart_fields": settings_payload["restart_required_fields"],
            "runtime_started_at": format_local_datetime(self.runtime.started_at),
            "uptime_seconds": uptime_seconds,
            "runtime_metrics": {
                "workers_active": active_workers,
                "workers_configured": self.runtime.settings.worker_count,
                "queue_rejections": rejected_count,
                "recent_messages": len(self.runtime.recent_messages),
                "recent_plugin_logs": len(self.runtime.recent_plugin_logs),
                "queue_capacity": self.runtime.settings.queue_size,
                "queue_enqueue_wait_seconds": self.runtime.settings.queue_enqueue_wait_seconds,
            },
            "heartbeat": {
                "enabled": user_payload["enabled"],
                "interval_seconds": user_payload["interval_seconds"],
                "healthy": user_payload["healthy"],
                "last_checked_at": user_payload["last_checked_at"],
                "account_count": user_payload["total"],
                "error": user_payload["error"],
                "wxrobot_api_reachable": self.runtime.wxrobot_api_reachable,
            },
        }

    @staticmethod
    def serialize_system_settings(settings_obj: PluginServiceSettings, *, mask_secrets: bool = True) -> dict[str, Any]:
        payload = {field: getattr(settings_obj, field) for field in SYSTEM_SETTINGS_FIELDS if field != "wxrobot_api_base_url"}
        payload["api_base_url"] = settings_obj.wxrobot_api_base_url
        if mask_secrets:
            payload["api_token"] = SECRET_SETTINGS_PLACEHOLDER if str(payload.get("api_token") or "").strip() else ""
            payload["callback_secret"] = SECRET_SETTINGS_PLACEHOLDER if str(payload.get("callback_secret") or "").strip() else ""
            payload["api_token_configured"] = bool(str(getattr(settings_obj, "api_token", "") or "").strip())
            payload["callback_secret_configured"] = bool(str(getattr(settings_obj, "callback_secret", "") or "").strip())
        return payload

    @staticmethod
    def merge_secret_settings_updates(
        configured_settings: PluginServiceSettings,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        merged_updates = dict(updates)
        for field_name in ("api_token", "callback_secret"):
            incoming_value = str(merged_updates.get(field_name) or "").strip()
            if not incoming_value or incoming_value == SECRET_SETTINGS_PLACEHOLDER:
                merged_updates[field_name] = getattr(configured_settings, field_name, "")
        return merged_updates

    def build_settings_payload(self) -> dict:
        configured_settings = PluginServiceSettings.from_storage()
        runtime_payload = self.serialize_system_settings(self.runtime.settings)
        configured_payload = self.serialize_system_settings(configured_settings)
        restart_required_fields = [
            field
            for field in RESTART_REQUIRED_FIELDS
            if getattr(self.runtime.settings, field) != getattr(configured_settings, field)
        ]
        return {
            "runtime": runtime_payload,
            "config": configured_payload,
            "restart_required": bool(restart_required_fields),
            "restart_required_fields": restart_required_fields,
            "api_auth_enabled": is_api_auth_enabled(configured_settings),
            "callback_auth_enabled": is_callback_auth_enabled(configured_settings),
        }

    def build_plugin_log_payload(self, module_name: str | None = None, level: str = "", keyword: str = "", limit: int = 200) -> dict:
        limit = max(1, min(limit, PLUGIN_LOG_LIMIT))
        normalized_level = str(level or "").strip().upper()
        normalized_keyword = str(keyword or "").strip()
        logs, filtered_total = self.runtime.get_plugin_logs(limit, module_name, normalized_level, normalized_keyword)
        plugin_options = [
            {"module": item["module"], "name": item["name"]}
            for item in self.build_plugin_payload()
        ]
        available_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        return {
            "logs": logs,
            "total": len(self.runtime.recent_plugin_logs),
            "filtered_total": filtered_total,
            "module_name": module_name or "",
            "level": normalized_level,
            "keyword": normalized_keyword,
            "available_plugins": plugin_options,
            "available_levels": available_levels,
            "updated_at": logs[0]["recorded_at"] if logs else None,
        }

    def plan_runtime_reload(self, configured_settings: PluginServiceSettings) -> tuple[PluginServiceSettings, list[str], list[str], list[str]]:
        changed_fields = [
            field
            for field in configured_settings.model_fields
            if getattr(self.runtime.settings, field) != getattr(configured_settings, field)
        ]
        hot_reload_fields = [field for field in changed_fields if field not in RESTART_REQUIRED_FIELDS]
        restart_required_fields = [field for field in changed_fields if field in RESTART_REQUIRED_FIELDS]
        effective_settings = self.runtime.settings
        if hot_reload_fields:
            effective_settings = self.runtime.settings.model_copy(
                update={field: getattr(configured_settings, field) for field in hot_reload_fields}
            )
        return effective_settings, changed_fields, hot_reload_fields, restart_required_fields


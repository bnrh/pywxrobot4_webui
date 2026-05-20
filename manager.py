import asyncio
import importlib
import inspect
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from types import ModuleType
from typing import Any, Callable

from loguru import logger

from config import PLUGIN_PACKAGE, normalize_plugin_module_name
from message import MessageEvent
from plugin_base import PluginContext, PluginExecutionContext, PluginLogger, PluginResult, PluginStateStore
from plugins._global_blacklist import (
    BLACKLIST_MEMBERS_NAMESPACE,
    BLACKLIST_PLUGIN_MODULE,
    BLACKLIST_PLUGIN_NAME,
    resolve_blacklist_subject_wxid,
)


PLUGIN_DIR = Path(__file__).with_name("plugins")
PYTHON_SDK_VERSION = "2.0.0"
MESSAGE_FILTER_ALIASES = {
    "text": 1,
    "image": 3,
    "voice": 34,
    "friend_request": 37,
    "card": 42,
    "video": 43,
    "emoji": 47,
    "location": 48,
    "xml": 49,
    "notice": 10000,
    "sysmsg": 10002,
    "file": 25769803825,
}
PLUGIN_SCOPE_ROOM_MODE = "_scope_room_mode"
PLUGIN_SCOPE_ROOM_IDS = "_scope_room_ids"
PLUGIN_SCOPE_FRIEND_MODE = "_scope_friend_mode"
PLUGIN_SCOPE_FRIEND_LABELS = "_scope_friend_labels"
PLUGIN_SCOPE_BIZ_MODE = "_scope_biz_mode"
FRIEND_LABEL_CACHE_TTL_SECONDS = 60.0
SCOPE_TARGET_ALIASES = {
    "room": "rooms",
    "rooms": "rooms",
    "group": "rooms",
    "groups": "rooms",
    "friend_label": "friend_labels",
    "friend_labels": "friend_labels",
    "friend-labels": "friend_labels",
    "friends": "friend_labels",
    "biz": "biz",
    "official_account": "biz",
    "official_accounts": "biz",
}


@dataclass(slots=True)
class PluginSpec:
    module_name: str
    path: Path
    stem: str


def _normalize_event_filters(value: Any) -> tuple[str, ...]:
    raw_items = value if isinstance(value, list) else ([value] if value else [])
    normalized_items: list[str] = []
    for item in raw_items:
        normalized = str(item or "").strip().lower()
        if normalized and normalized not in normalized_items:
            normalized_items.append(normalized)
    return tuple(normalized_items)


def _normalize_config_schema(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [deepcopy(item) for item in value if isinstance(item, dict)]


def _normalize_scope_targets(value: Any) -> tuple[str, ...]:
    raw_items = value if isinstance(value, (list, tuple, set)) else ([value] if value else [])
    normalized_items: list[str] = []
    for item in raw_items:
        normalized = SCOPE_TARGET_ALIASES.get(str(item or "").strip().lower(), "")
        if normalized and normalized not in normalized_items:
            normalized_items.append(normalized)
    return tuple(normalized_items)


def _normalize_scope_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple, set)):
        raw_items = value
    elif isinstance(value, str):
        raw_items = value.split(",")
    elif value in (None, ""):
        raw_items = []
    else:
        raw_items = [value]

    normalized_items: list[str] = []
    for item in raw_items:
        normalized = str(item or "").strip()
        if normalized and normalized not in normalized_items:
            normalized_items.append(normalized)
    return tuple(normalized_items)


def _normalize_scope_mode(value: Any, *, allow_selected: bool = True, default: str = "all") -> str:
    normalized = str(value or "").strip().lower()
    allowed = {"all", "none"}
    if allow_selected:
        allowed.add("selected")
    return normalized if normalized in allowed else default


def _is_biz_conversation_wxid(wxid: str) -> bool:
    normalized = str(wxid or "").strip().lower()
    return bool(normalized) and normalized.startswith("gh_")


def _normalize_text(value: Any) -> str:
    return "" if value in (None, "") else str(value).strip()


def _normalize_wxpid(value: Any) -> int | None:
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


def _resolve_login_account_wxid(accounts: list[dict[str, Any]] | None, wxpid: int | None) -> str:
    if wxpid is None:
        return ""
    for item in accounts if isinstance(accounts, list) else []:
        if not isinstance(item, dict):
            continue
        if _normalize_wxpid(item.get("wxpid") or item.get("pid")) != wxpid:
            continue
        wxid = _normalize_text(item.get("wxid"))
        if wxid:
            return wxid
    return ""


def _resolve_module_attr(module: ModuleType, *names: str, default: Any = None) -> Any:
    for name in names:
        if hasattr(module, name):
            return getattr(module, name)
    return default


def _resolve_schedule(module: ModuleType, capabilities: dict[str, Any]) -> dict[str, Any]:
    if not capabilities.get("tick_hook"):
        return {}

    raw_schedule = _resolve_module_attr(module, "schedule", default={})
    schedule = dict(raw_schedule) if isinstance(raw_schedule, dict) else {}
    interval_field = str(
        schedule.get("interval_field")
        or _resolve_module_attr(module, "tick_interval_field", "tickIntervalField", default="interval_seconds")
        or "interval_seconds"
    ).strip() or "interval_seconds"
    default_interval_value = schedule.get(
        "default_interval_seconds",
        _resolve_module_attr(module, "tick_interval_seconds", "tickIntervalSeconds", default=None),
    )
    try:
        default_interval_seconds = float(default_interval_value) if default_interval_value is not None else None
    except (TypeError, ValueError):
        default_interval_seconds = None
    return {
        "interval_field": interval_field,
        "default_interval_seconds": default_interval_seconds,
    }


def _describe_python_module(module: ModuleType, spec: PluginSpec) -> dict[str, Any]:
    declared_category = str(_resolve_module_attr(module, "category", default="") or "").strip().lower()
    raw_message_dependent = _resolve_module_attr(module, "message_dependent", "messageDependent", default=None)
    if isinstance(raw_message_dependent, bool):
        message_dependent = raw_message_dependent
    else:
        message_dependent = declared_category not in {"functional", "utility"}
    category = "message" if message_dependent else "functional"
    event_filters = _normalize_event_filters(_resolve_module_attr(module, "event_filters", "eventFilters", "eventFilter", default=[]))
    config_schema = _normalize_config_schema(_resolve_module_attr(module, "config_schema", "configSchema", default=[]))
    scope_targets = _normalize_scope_targets(
        _resolve_module_attr(module, "scope_targets", "scopeTargets", "supported_scopes", "supportedScopes", default=[])
    )
    capabilities = {
        "logger": True,
        "persistent_state": True,
        "hot_reload": True,
        "message_hook": callable(_resolve_module_attr(module, "handle_message", "handleMessage", default=None)),
        "execute_hook": callable(_resolve_module_attr(module, "execute", default=None)),
        "startup_hook": callable(_resolve_module_attr(module, "startup", default=None)),
        "shutdown_hook": callable(_resolve_module_attr(module, "shutdown", default=None)),
        "hot_reload_hook": callable(_resolve_module_attr(module, "on_hot_reload", "onHotReload", default=None)),
        "tick_hook": callable(_resolve_module_attr(module, "tick", default=None)),
    }
    return {
        "name": str(_resolve_module_attr(module, "name", default=spec.stem) or spec.stem),
        "description": str(_resolve_module_attr(module, "description", default="") or ""),
        "runtime": "python",
        "sdk_version": str(_resolve_module_attr(module, "sdk_version", "sdkVersion", default=PYTHON_SDK_VERSION) or PYTHON_SDK_VERSION),
        "category": category,
        "message_dependent": message_dependent,
        "event_filters": list(event_filters),
        "capabilities": capabilities,
        "config_schema": config_schema,
        "scope_targets": list(scope_targets),
        "schedule": _resolve_schedule(module, capabilities),
    }


async def _await_if_needed(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class PythonPlugin:
    runtime = "python"

    def __init__(
        self,
        spec: PluginSpec,
        config: dict[str, Any] | None,
        module: ModuleType,
        metadata: dict[str, Any],
        plugin_log_sink: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.spec = spec
        self.module_name = spec.module_name
        self.config = dict(config or {})
        self._module = module
        self._plugin_log_sink = plugin_log_sink
        self._state = PluginStateStore(self.module_name)
        self.name = spec.stem
        self.description = ""
        self.sdk_version = PYTHON_SDK_VERSION
        self.capabilities: dict[str, Any] = {}
        self.category = "message"
        self.message_dependent = True
        self.event_filters: tuple[str, ...] = ()
        self.config_schema: list[dict[str, Any]] = []
        self.scope_targets: tuple[str, ...] = ()
        self.schedule: dict[str, Any] = {}
        self._logger = PluginLogger(self.module_name, self.name, self._plugin_log_sink)
        self._apply_metadata(metadata)
        self._loaded_revision = self._current_revision()

    def _current_revision(self) -> int:
        if not self.spec.path.exists():
            raise FileNotFoundError(f"未找到 Python 插件文件: {self.spec.path}")
        return self.spec.path.stat().st_mtime_ns

    def _apply_metadata(self, metadata: dict[str, Any]) -> None:
        self.name = str(metadata.get("name") or self.spec.stem or self.module_name)
        self.description = str(metadata.get("description") or "")
        self.sdk_version = str(metadata.get("sdk_version") or PYTHON_SDK_VERSION)
        self.category = str(metadata.get("category") or "message").strip().lower() or "message"
        self.message_dependent = bool(metadata.get("message_dependent", True))
        self.event_filters = tuple(_normalize_event_filters(metadata.get("event_filters") or []))
        self.capabilities = dict(metadata.get("capabilities") or {})
        self.config_schema = _normalize_config_schema(metadata.get("config_schema") or [])
        self.scope_targets = _normalize_scope_targets(metadata.get("scope_targets") or [])
        self.schedule = dict(metadata.get("schedule") or {})
        self._logger = PluginLogger(self.module_name, self.name, self._plugin_log_sink)

    def _matches_event_filter(self, event: MessageEvent, event_filter: str) -> bool:
        normalized_filter = str(event_filter or "").strip().lower()
        if not normalized_filter:
            return True
        if normalized_filter == "group":
            return event.is_group_message
        if normalized_filter in {"direct", "private", "single"}:
            return not event.is_group_message
        if normalized_filter == "image":
            return event.is_image
        if normalized_filter in MESSAGE_FILTER_ALIASES:
            expected_type = MESSAGE_FILTER_ALIASES[normalized_filter]
            return event.normalized_msg_type == expected_type or event.normalized_local_type == expected_type
        try:
            expected_type = int(normalized_filter, 16) if normalized_filter.startswith("0x") else int(normalized_filter)
        except ValueError:
            return False
        return event.normalized_msg_type == expected_type or event.normalized_local_type == expected_type

    def should_handle_message(self, event: MessageEvent) -> bool:
        if not self.message_dependent:
            return False
        if not self.event_filters:
            return True
        return any(self._matches_event_filter(event, event_filter) for event_filter in self.event_filters)

    def _build_hot_reload_info(
        self,
        *,
        changed: bool,
        reason: str,
        current_revision: int,
        previous_revision: int | None,
    ) -> dict[str, Any]:
        return {
            "enabled": True,
            "changed": changed,
            "reason": reason,
            "current_revision": current_revision,
            "previous_revision": previous_revision,
        }

    def _build_execution_context(self, context: PluginContext, hot_reload: dict[str, Any] | None = None) -> PluginExecutionContext:
        return PluginExecutionContext(
            settings=context.settings,
            api=context.api_client,
            config=dict(self.config),
            logger=self._logger,
            state=self._state,
            plugin_name=self.name,
            plugin_module=self.module_name,
            hot_reload=deepcopy(hot_reload) if hot_reload else None,
            login_account_cache_getter=context.login_account_cache_getter,
            login_account_cache_refresher=context.login_account_cache_refresher,
            login_account_serializer=context.login_account_serializer,
        )

    def _resolve_hook(self, *names: str) -> Callable[..., Any] | None:
        for name in names:
            candidate = getattr(self._module, name, None)
            if callable(candidate):
                return candidate
        return None

    async def _call_hook(
        self,
        hook_names: tuple[str, ...],
        context: PluginContext,
        *args: Any,
        hot_reload: dict[str, Any] | None = None,
    ) -> Any:
        hook = self._resolve_hook(*hook_names)
        if hook is None:
            return None
        execution_context = self._build_execution_context(context, hot_reload)
        return await _await_if_needed(hook(*args, execution_context))

    async def startup(self, context: PluginContext) -> None:
        await self._call_hook(
            ("startup",),
            context,
            hot_reload=self._build_hot_reload_info(
                changed=False,
                reason="startup",
                current_revision=self._loaded_revision,
                previous_revision=self._loaded_revision,
            ),
        )

    async def shutdown(self, context: PluginContext) -> None:
        await self._call_hook(
            ("shutdown",),
            context,
            hot_reload=self._build_hot_reload_info(
                changed=False,
                reason="shutdown",
                current_revision=self._loaded_revision,
                previous_revision=self._loaded_revision,
            ),
        )

    async def _refresh_if_needed(self, context: PluginContext) -> dict[str, Any]:
        current_revision = self._current_revision()
        hot_reload = self._build_hot_reload_info(
            changed=current_revision != self._loaded_revision,
            reason="file-changed" if current_revision != self._loaded_revision else "steady",
            current_revision=current_revision,
            previous_revision=self._loaded_revision,
        )
        if current_revision == self._loaded_revision:
            return hot_reload

        previous_name = self.name
        previous_description = self.description
        self._module = PluginManager._load_python_module(self.spec, force_reload=True)
        metadata = _describe_python_module(self._module, self.spec)
        self._apply_metadata(metadata)
        hot_reload.update(
            {
                "previous_name": previous_name,
                "previous_description": previous_description,
            }
        )
        await self._call_hook(("on_hot_reload", "onHotReload"), context, hot_reload, hot_reload=hot_reload)
        logger.info("Python 插件已热重载: {}", self.module_name)
        self._loaded_revision = current_revision
        return hot_reload

    @staticmethod
    def _normalize_result(result: Any) -> PluginResult:
        if isinstance(result, PluginResult):
            return result
        if result is None:
            return PluginResult.skipped("")
        if isinstance(result, dict):
            return PluginResult(
                handled=bool(result.get("handled")),
                stop_processing=bool(result.get("stop_processing") or result.get("stopProcessing")),
                detail=str(result.get("detail") or ""),
                data=result.get("data") if isinstance(result.get("data"), dict) else {},
            )
        return PluginResult.skipped(str(result))

    async def handle_message(self, event: MessageEvent, context: PluginContext) -> PluginResult:
        hot_reload = await self._refresh_if_needed(context)
        result = await self._call_hook(("handle_message", "handleMessage"), context, event, hot_reload=hot_reload)
        return self._normalize_result(result)

    @property
    def supports_tick(self) -> bool:
        return bool(self.capabilities.get("tick_hook"))

    def get_tick_interval_seconds(self) -> float:
        interval_field = str(self.schedule.get("interval_field") or "interval_seconds").strip() or "interval_seconds"
        configured_value = self.config.get(interval_field)
        if configured_value not in (None, ""):
            try:
                return max(0.0, float(configured_value))
            except (TypeError, ValueError):
                return 0.0
        default_value = self.schedule.get("default_interval_seconds")
        try:
            return max(0.0, float(default_value)) if default_value is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    async def tick(self, context: PluginContext) -> PluginResult:
        hot_reload = await self._refresh_if_needed(context)
        result = await self._call_hook(("tick",), context, hot_reload=hot_reload)
        return self._normalize_result(result)

    async def execute(self, context: PluginContext) -> PluginResult:
        hot_reload = self._build_hot_reload_info(
            changed=False,
            reason="manual-execute",
            current_revision=self._loaded_revision,
            previous_revision=self._loaded_revision,
        )
        if self.capabilities.get("execute_hook"):
            result = await self._call_hook(("execute",), context, hot_reload=hot_reload)
            return self._normalize_result(result)
        if self.capabilities.get("startup_hook"):
            await self._call_hook(("startup",), context, hot_reload=hot_reload)
            return PluginResult.handled_result("插件执行完成")
        if self.supports_tick:
            return await self.tick(context)
        return PluginResult.skipped("插件未提供可执行入口")


class PluginManager:
    def __init__(
        self,
        context: PluginContext,
        module_names: list[str],
        plugin_settings: dict[str, dict],
        plugin_log_sink: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.context = context
        self.module_names = module_names
        self.plugin_settings = plugin_settings
        self.plugin_log_sink = plugin_log_sink
        self._plugins: list[PythonPlugin] = []
        self._periodic_tasks: list[asyncio.Task] = []
        self._friend_label_cache: dict[int, tuple[float, dict[str, set[str]]]] = {}
        self._friend_label_locks: dict[int, asyncio.Lock] = {}
        self._blacklist_state = PluginStateStore(BLACKLIST_PLUGIN_MODULE, namespace=BLACKLIST_MEMBERS_NAMESPACE)

    @property
    def plugins(self) -> tuple[PythonPlugin, ...]:
        return tuple(self._plugins)

    @staticmethod
    def discover_plugin_modules() -> list[str]:
        specs = PluginManager._discover_plugin_specs()
        if not specs:
            return []
        return sorted(specs)

    @staticmethod
    def _discover_plugin_specs() -> dict[str, PluginSpec]:
        if not PLUGIN_DIR.exists():
            return {}
        specs: dict[str, PluginSpec] = {}
        for path in sorted(PLUGIN_DIR.glob("*.py")):
            if not path.is_file() or path.stem == "__init__" or path.stem.startswith("_"):
                continue
            module_name = f"{PLUGIN_PACKAGE}.{path.stem}"
            specs[module_name] = PluginSpec(module_name=module_name, path=path, stem=path.stem)
        return specs

    @classmethod
    def _resolve_plugin_spec(cls, module_name: str) -> PluginSpec:
        discovered = cls._discover_plugin_specs()
        normalized_module_name = normalize_plugin_module_name(module_name)
        spec = discovered.get(normalized_module_name)
        if spec is None:
            raise FileNotFoundError(f"未找到 Python 插件文件: {module_name}")
        return spec

    @staticmethod
    def _load_python_module(spec: PluginSpec, force_reload: bool = False) -> ModuleType:
        importlib.invalidate_caches()
        if force_reload and spec.module_name in sys.modules:
            return importlib.reload(sys.modules[spec.module_name])
        if spec.module_name in sys.modules:
            return sys.modules[spec.module_name]
        return importlib.import_module(spec.module_name)

    @classmethod
    def describe_plugin(cls, spec: PluginSpec) -> dict[str, Any]:
        module = cls._load_python_module(spec, force_reload=True)
        return _describe_python_module(module, spec)

    @classmethod
    def _describe_python_plugin(cls, spec: PluginSpec) -> dict[str, Any]:
        return cls.describe_plugin(spec)

    def _resolve_plugin_config(self, module_name: str, plugin_name: str | None = None) -> dict[str, Any]:
        plugin_config = self.plugin_settings.get(module_name, {})
        if not plugin_config and plugin_name:
            plugin_config = self.plugin_settings.get(plugin_name, {})
        return plugin_config

    @classmethod
    def describe_modules(cls, module_names: list[str]) -> list[dict[str, Any]]:
        descriptions: list[dict[str, Any]] = []
        for module_name in module_names:
            try:
                spec = cls._resolve_plugin_spec(module_name)
                metadata = cls._describe_python_plugin(spec)
                descriptions.append(
                    {
                        "module": module_name,
                        "name": metadata.get("name", module_name),
                        "description": metadata.get("description", ""),
                        "runtime": "python",
                        "sdk_version": metadata.get("sdk_version", PYTHON_SDK_VERSION),
                        "category": str(metadata.get("category") or "message"),
                        "message_dependent": bool(metadata.get("message_dependent", True)),
                        "event_filters": metadata.get("event_filters") if isinstance(metadata.get("event_filters"), list) else [],
                        "capabilities": metadata.get("capabilities") if isinstance(metadata.get("capabilities"), dict) else {},
                        "config_schema": metadata.get("config_schema") if isinstance(metadata.get("config_schema"), list) else [],
                        "scope_targets": metadata.get("scope_targets") if isinstance(metadata.get("scope_targets"), list) else [],
                        "loadable": True,
                        "error": "",
                    }
                )
            except Exception as exc:
                descriptions.append(
                    {
                        "module": module_name,
                        "name": module_name.rsplit(".", 1)[-1],
                        "description": "",
                        "runtime": "python",
                        "sdk_version": PYTHON_SDK_VERSION,
                        "category": "message",
                        "message_dependent": True,
                        "event_filters": [],
                        "capabilities": {},
                        "config_schema": [],
                        "scope_targets": [],
                        "loadable": False,
                        "error": str(exc),
                    }
                )
        return descriptions

    @staticmethod
    def _wxpid_cache_key(wxpid: int | None) -> int:
        if wxpid in (None, ""):
            return -1
        try:
            return int(wxpid)
        except (TypeError, ValueError):
            return -1

    def _get_friend_label_lock(self, wxpid: int | None) -> asyncio.Lock:
        key = self._wxpid_cache_key(wxpid)
        lock = self._friend_label_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._friend_label_locks[key] = lock
        return lock

    async def _get_friend_labels_by_user(self, wxpid: int | None) -> dict[str, set[str]]:
        key = self._wxpid_cache_key(wxpid)
        cached_entry = self._friend_label_cache.get(key)
        if cached_entry is not None and monotonic() - cached_entry[0] < FRIEND_LABEL_CACHE_TTL_SECONDS:
            return cached_entry[1]

        lock = self._get_friend_label_lock(wxpid)
        async with lock:
            cached_entry = self._friend_label_cache.get(key)
            if cached_entry is not None and monotonic() - cached_entry[0] < FRIEND_LABEL_CACHE_TTL_SECONDS:
                return cached_entry[1]

            label_payload = await self.context.api_client.get_labels(wxpid=wxpid)
            label_id_to_name: dict[str, str] = {}
            if isinstance(label_payload, dict):
                for label_name, label_id in label_payload.items():
                    normalized_name = str(label_name or "").strip()
                    normalized_id = str(label_id or "").strip()
                    if normalized_name and normalized_id:
                        label_id_to_name[normalized_id] = normalized_name

            user_payload = await self.context.api_client.get_user_list(wxpid=wxpid)
            next_cache: dict[str, set[str]] = {}
            if isinstance(user_payload, list):
                for item in user_payload:
                    wxid = str(item.get("wxid") or "").strip()
                    if not wxid:
                        continue
                    raw_label_ids = item.get("labels") or item.get("label_ids") or item.get("labelIds") or []
                    label_ids = _normalize_scope_values(raw_label_ids)
                    next_cache[wxid] = {
                        label_id_to_name[label_id]
                        for label_id in label_ids
                        if label_id in label_id_to_name
                    }

            self._friend_label_cache[key] = (monotonic(), next_cache)
            return next_cache

    async def _matches_plugin_scope(self, plugin: PythonPlugin, event: MessageEvent) -> bool:
        if not plugin.scope_targets:
            return True

        config = plugin.config if isinstance(plugin.config, dict) else {}

        if event.is_group_message:
            if "rooms" not in plugin.scope_targets:
                return True
            room_mode = _normalize_scope_mode(config.get(PLUGIN_SCOPE_ROOM_MODE), default="all")
            if room_mode == "all":
                return True
            if room_mode == "none":
                return False
            allowed_room_ids = set(_normalize_scope_values(config.get(PLUGIN_SCOPE_ROOM_IDS)))
            return bool(event.conversation_wxid) and event.conversation_wxid in allowed_room_ids

        if _is_biz_conversation_wxid(event.conversation_wxid):
            if "biz" not in plugin.scope_targets:
                return True
            biz_mode = _normalize_scope_mode(config.get(PLUGIN_SCOPE_BIZ_MODE), allow_selected=False, default="all")
            return biz_mode == "all"

        if "friend_labels" not in plugin.scope_targets:
            return True

        friend_mode = _normalize_scope_mode(config.get(PLUGIN_SCOPE_FRIEND_MODE), default="all")
        if friend_mode == "all":
            return True
        if friend_mode == "none":
            return False

        selected_labels = set(_normalize_scope_values(config.get(PLUGIN_SCOPE_FRIEND_LABELS)))
        if not selected_labels:
            return False

        target_wxid = str(event.conversation_wxid or event.sender_wxid or "").strip()
        if not target_wxid:
            return False

        try:
            user_labels = (await self._get_friend_labels_by_user(event.normalized_wxpid)).get(target_wxid, set())
        except Exception:
            logger.exception("读取插件 {} 的好友标签白名单失败", plugin.name)
            return False
        return bool(user_labels & selected_labels)

    async def _resolve_event_self_wxid(self, event: MessageEvent) -> str:
        current_account_wxid = _normalize_text(event.current_account_wxid)
        if current_account_wxid:
            return current_account_wxid

        wxpid = event.normalized_wxpid
        if wxpid is None:
            return ""

        cached_accounts = self.context.get_cached_login_accounts()
        resolved_wxid = _resolve_login_account_wxid(cached_accounts, wxpid)
        if resolved_wxid:
            return resolved_wxid

        refreshed_accounts = await self.context.refresh_cached_login_accounts()
        return _resolve_login_account_wxid(refreshed_accounts, wxpid)

    async def _is_self_sent_message(self, event: MessageEvent) -> bool:
        if event.is_self_message:
            return True

        sender_wxid = _normalize_text(event.sender_wxid)
        if not sender_wxid:
            return False

        self_wxid = await self._resolve_event_self_wxid(event)
        return bool(self_wxid) and sender_wxid == self_wxid

    def _build_blacklist_block_result(self, subject_wxid: str) -> list[dict[str, Any]]:
        blacklist_record = self._blacklist_state.get(subject_wxid, {})
        display_name = _normalize_text(blacklist_record.get("display_name")) if isinstance(blacklist_record, dict) else ""
        resolved_name = display_name or subject_wxid
        return [
            {
                "plugin": BLACKLIST_PLUGIN_NAME,
                "handled": True,
                "stop_processing": True,
                "detail": f"黑名单成员消息已忽略: {resolved_name}",
                "data": {
                    "wxid": subject_wxid,
                    "display_name": resolved_name,
                },
            }
        ]

    async def load_plugins(self) -> None:
        self._plugins.clear()
        for module_name in self.module_names:
            plugin = self._load_plugin(module_name)
            await plugin.startup(self.context)
            self._plugins.append(plugin)
            if plugin.supports_tick and plugin.get_tick_interval_seconds() > 0:
                self._periodic_tasks.append(
                    asyncio.create_task(self._periodic_tick_loop(plugin), name=f"plugin-tick-{plugin.module_name}")
                )
            logger.info("已加载插件: {}", plugin.name)

    async def shutdown(self) -> None:
        for task in self._periodic_tasks:
            task.cancel()
        if self._periodic_tasks:
            await asyncio.gather(*self._periodic_tasks, return_exceptions=True)
        self._periodic_tasks.clear()
        for plugin in reversed(self._plugins):
            try:
                await plugin.shutdown(self.context)
            except Exception:
                logger.exception("关闭插件 {} 失败", plugin.name)
        self._plugins.clear()

    async def _periodic_tick_loop(self, plugin: PythonPlugin) -> None:
        interval_seconds = plugin.get_tick_interval_seconds()
        if interval_seconds <= 0:
            return
        try:
            while True:
                await asyncio.sleep(interval_seconds)
                result = await plugin.tick(self.context)
                if result.handled or result.detail:
                    logger.info("周期插件执行完成: {} | {}", plugin.name, result.detail or "已执行")
                interval_seconds = plugin.get_tick_interval_seconds()
                if interval_seconds <= 0:
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("周期插件 {} 执行失败", plugin.name)

    async def dispatch(self, event: MessageEvent) -> list[dict[str, Any]]:
        if await self._is_self_sent_message(event):
            return []

        blacklist_subject_wxid = resolve_blacklist_subject_wxid(event)
        if blacklist_subject_wxid and self._blacklist_state.has(blacklist_subject_wxid):
            return self._build_blacklist_block_result(blacklist_subject_wxid)

        results: list[dict[str, Any]] = []
        for plugin in self._plugins:
            if not plugin.should_handle_message(event):
                continue
            if not await self._matches_plugin_scope(plugin, event):
                continue
            try:
                result = await plugin.handle_message(event, self.context)
            except Exception as exc:
                logger.exception("插件 {} 处理消息失败", plugin.name)
                result = PluginResult.skipped(str(exc))

            if result.handled or result.stop_processing or result.detail or result.data:
                results.append(
                    {
                        "plugin": plugin.name,
                        "handled": result.handled,
                        "stop_processing": result.stop_processing,
                        "detail": result.detail,
                        "data": result.data,
                    }
                )
            if result.stop_processing:
                break
        return results

    async def execute_plugin(self, module_name: str, config_override: dict[str, Any] | None = None) -> dict[str, Any]:
        plugin = self._load_plugin(module_name, config_override)
        if plugin.message_dependent:
            raise ValueError("消息插件不支持手动执行")

        try:
            result = await plugin.execute(self.context)
        finally:
            try:
                await plugin.shutdown(self.context)
            except Exception:
                logger.exception("手动执行插件 {} 后清理资源失败", plugin.name)

        return {
            "module": plugin.module_name,
            "plugin": plugin.name,
            "handled": result.handled,
            "stop_processing": result.stop_processing,
            "detail": result.detail,
            "data": result.data,
        }

    def _load_plugin(self, module_name: str, config_override: dict[str, Any] | None = None) -> PythonPlugin:
        spec = self._resolve_plugin_spec(module_name)
        module = self._load_python_module(spec, force_reload=True)
        metadata = _describe_python_module(module, spec)
        resolved_config = self._resolve_plugin_config(module_name, str(metadata.get("name") or spec.stem))
        if config_override:
            resolved_config = {
                **resolved_config,
                **dict(config_override),
            }
        return PythonPlugin(
            spec,
            resolved_config,
            module,
            metadata,
            self.plugin_log_sink,
        )
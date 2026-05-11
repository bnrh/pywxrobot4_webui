import asyncio
import ast
import inspect
import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib import error, request

from client import WxRobotApiClient


AI_ASSISTANT_SETTINGS_KEY = "ai_assistant_settings"
MAX_CONVERSATION_MESSAGES = 16
MAX_TOOL_RESULT_ITEMS = 40
MAX_TOOL_RESULT_STRING_LENGTH = 1600

DEFAULT_SYSTEM_PROMPT = (
    "你是 wxrobot_api 的智能插件助手。"
    "当用户提出微信自动化或查询需求时，优先使用提供给你的 wxrobot_api 工具完成任务。"
    "如果信息不足以安全执行写操作（例如发送消息、修改标签、邀请进群、删除成员），先向用户索取必要参数，"
    "不要臆造 wxid、roomid、wxpid、文件路径或消息内容。"
    "对于只读查询，尽量先调用工具获取事实，再给出简洁结论。"
    "当工具执行失败时，明确说明失败原因并给出下一步建议。"
)

PROVIDER_CATALOG = {
    "zhipu": {
        "key": "zhipu",
        "label": "智谱",
        "description": "GLM 系列，接口参数固定内置在代码中。",
        "default_model": "glm-4-plus",
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "chat_path": "/chat/completions",
        "models_path": "/models",
        "allow_custom_base_url": False,
        "custom_headers": {},
        "extra_body": {},
    },
    "deepseek": {
        "key": "deepseek",
        "label": "DeepSeek",
        "description": "DeepSeek Chat，接口参数固定内置在代码中。",
        "default_model": "deepseek-chat",
        "default_base_url": "https://api.deepseek.com/v1",
        "chat_path": "/chat/completions",
        "models_path": "/models",
        "allow_custom_base_url": False,
        "custom_headers": {},
        "extra_body": {},
    },
    "minimax": {
        "key": "minimax",
        "label": "MiniMax",
        "description": "MiniMax，接口参数固定内置在代码中。",
        "default_model": "MiniMax-Text-01",
        "default_base_url": "https://api.minimax.chat/v1",
        "chat_path": "/chat/completions",
        "models_path": "/models",
        "allow_custom_base_url": False,
        "custom_headers": {},
        "extra_body": {},
    },
    "openai": {
        "key": "openai",
        "label": "通用 OpenAI",
        "description": "适配任意 OpenAI-compatible 网关，支持自定义 Base URL。",
        "default_model": "gpt-4o-mini",
        "default_base_url": "https://api.openai.com/v1",
        "chat_path": "/chat/completions",
        "models_path": "/models",
        "allow_custom_base_url": True,
        "custom_headers": {},
        "extra_body": {},
    },
}

DEFAULT_AI_ASSISTANT_SETTINGS = {
    "active_provider": "zhipu",
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
    "temperature": 0.2,
    "max_tool_rounds": 6,
    "providers": {
        key: {
            "configs": [],
        }
        for key, provider in PROVIDER_CATALOG.items()
    },
}

_JSON_OBJECT_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": True,
}

MCP_SERVER_SOURCE_CANDIDATES = (
    Path(__file__).resolve().parent.parent / "wxrobot_api" / "api" / "mcp_server.py",
    Path(__file__).resolve().parent / "wxrobot_api" / "api" / "mcp_server.py",
)


def _build_tool_schema(
    name: str,
    description: str,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
    *,
    read_only: bool = True,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "read_only": read_only,
        "schema": {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties or {},
                    "required": required or [],
                    "additionalProperties": False,
                },
            },
        },
    }


TOOL_REGISTRY = {
    "introduction": _build_tool_schema(
        "introduction",
        "获取 wxrobot_api 服务简介。",
    ),
    "get_users": _build_tool_schema(
        "get_users",
        "获取当前已登录的所有微信账号信息列表。",
    ),
    "get_wx_pids": _build_tool_schema(
        "get_wx_pids",
        "获取当前所有微信进程 wxpid 列表。",
    ),
    "hook": _build_tool_schema(
        "hook",
        "刷新并重新 hook 所有微信进程。",
        read_only=False,
    ),
    "get_user_list": _build_tool_schema(
        "get_user_list",
        "获取指定微信进程的联系人列表。",
        {"wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"}},
    ),
    "get_room_list": _build_tool_schema(
        "get_room_list",
        "获取指定微信进程的群聊列表。",
        {"wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"}},
    ),
    "get_biz_list": _build_tool_schema(
        "get_biz_list",
        "获取指定微信进程的公众号列表。",
        {"wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"}},
    ),
    "get_room_members": _build_tool_schema(
        "get_room_members",
        "获取群成员列表。",
        {
            "roomid": {"type": "string", "description": "群聊 ID，例如 123456@chatroom。"},
            "wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"},
        },
        ["roomid"],
    ),
    "get_user_info": _build_tool_schema(
        "get_user_info",
        "获取指定用户详细资料。",
        {
            "wxid": {"type": "string", "description": "用户 wxid。"},
            "roomid": {"type": "string", "description": "可选，所在群聊 ID。"},
            "wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"},
        },
        ["wxid"],
    ),
    "check_user_state": _build_tool_schema(
        "check_user_state",
        "检查指定联系人当前状态。",
        {
            "wxid": {"type": "string", "description": "用户 wxid。"},
            "wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"},
        },
        ["wxid"],
    ),
    "get_chat_messages": _build_tool_schema(
        "get_chat_messages",
        "获取指定会话在时间窗口内的聊天记录。",
        {
            "wxid": {"type": "string", "description": "会话 wxid 或 roomid。"},
            "start_time": {"type": ["string", "integer"], "description": "开始时间，例如 2026-05-11 00:00:00。"},
            "end_time": {"type": ["string", "integer"], "description": "结束时间，例如 2026-05-11 23:59:59。"},
            "max_count": {"type": "integer", "minimum": 1, "maximum": 2000, "description": "最多读取条数。"},
            "wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"},
        },
        ["wxid", "start_time", "end_time"],
    ),
    "get_labels": _build_tool_schema(
        "get_labels",
        "获取指定微信进程的标签列表。",
        {"wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"}},
    ),
    "add_label": _build_tool_schema(
        "add_label",
        "新增联系人标签。",
        {
            "label_name": {"type": "string", "description": "标签名称。"},
            "wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"},
        },
        ["label_name"],
        read_only=False,
    ),
    "set_labels": _build_tool_schema(
        "set_labels",
        "为指定联系人设置标签。",
        {
            "wxid": {"type": "string", "description": "联系人 wxid。"},
            "labels": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ],
                "description": "标签字符串或字符串数组。",
            },
            "wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"},
        },
        ["wxid", "labels"],
        read_only=False,
    ),
    "delete_labels": _build_tool_schema(
        "delete_labels",
        "删除标签。",
        {
            "labels": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ],
                "description": "标签字符串或字符串数组。",
            },
            "wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"},
        },
        ["labels"],
        read_only=False,
    ),
    "send_text": _build_tool_schema(
        "send_text",
        "发送文本消息。",
        {
            "wxid": {"type": "string", "description": "用户或群聊的唯一 ID。"},
            "content": {"type": "string", "description": "文本内容。"},
            "atlist": {"type": "string", "description": "可选，群聊艾特列表，多个 wxid 用逗号分隔。"},
            "wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"},
            "wait": {"type": "boolean", "description": "是否等待消息 ID。"},
            "timeout": {"type": "integer", "minimum": 1, "maximum": 30, "description": "等待超时秒数。"},
        },
        ["wxid", "content"],
        read_only=False,
    ),
    "send_image": _build_tool_schema(
        "send_image",
        "发送图片消息。",
        {
            "wxid": {"type": "string", "description": "用户或群聊的唯一 ID。"},
            "path": {"type": "string", "description": "图片路径。"},
            "wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"},
            "wait": {"type": "boolean", "description": "是否等待消息 ID。"},
            "timeout": {"type": "integer", "minimum": 1, "maximum": 30, "description": "等待超时秒数。"},
        },
        ["wxid", "path"],
        read_only=False,
    ),
    "send_file": _build_tool_schema(
        "send_file",
        "发送文件消息。",
        {
            "wxid": {"type": "string", "description": "用户或群聊的唯一 ID。"},
            "path": {"type": "string", "description": "文件路径。"},
            "wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"},
            "wait": {"type": "boolean", "description": "是否等待消息 ID。"},
            "timeout": {"type": "integer", "minimum": 1, "maximum": 30, "description": "等待超时秒数。"},
        },
        ["wxid", "path"],
        read_only=False,
    ),
    "send_video": _build_tool_schema(
        "send_video",
        "发送视频消息。",
        {
            "wxid": {"type": "string", "description": "用户或群聊的唯一 ID。"},
            "path": {"type": "string", "description": "视频路径。"},
            "wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"},
            "wait": {"type": "boolean", "description": "是否等待消息 ID。"},
            "timeout": {"type": "integer", "minimum": 1, "maximum": 30, "description": "等待超时秒数。"},
        },
        ["wxid", "path"],
        read_only=False,
    ),
    "send_gif": _build_tool_schema(
        "send_gif",
        "发送 GIF 表情消息。",
        {
            "wxid": {"type": "string", "description": "用户或群聊的唯一 ID。"},
            "path": {"type": "string", "description": "GIF 路径。"},
            "wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"},
            "wait": {"type": "boolean", "description": "是否等待消息 ID。"},
            "timeout": {"type": "integer", "minimum": 1, "maximum": 30, "description": "等待超时秒数。"},
        },
        ["wxid", "path"],
        read_only=False,
    ),
    "set_remarks": _build_tool_schema(
        "set_remarks",
        "修改联系人备注。",
        {
            "wxid": {"type": "string", "description": "联系人 wxid。"},
            "remarks": {"type": "string", "description": "新的备注内容。"},
            "wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"},
        },
        ["wxid", "remarks"],
        read_only=False,
    ),
    "receive_notify": _build_tool_schema(
        "receive_notify",
        "开启或关闭指定联系人的消息免打扰。",
        {
            "wxid": {"type": "string", "description": "联系人 wxid。"},
            "notify": {"type": "boolean", "description": "true 表示接收提醒，false 表示免打扰。"},
            "wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"},
        },
        ["wxid", "notify"],
        read_only=False,
    ),
    "invite_room_members": _build_tool_schema(
        "invite_room_members",
        "邀请联系人进入群聊。",
        {
            "roomid": {"type": "string", "description": "群聊 ID。"},
            "wxids": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ],
                "description": "联系人 wxid 或 wxid 数组。",
            },
            "wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"},
        },
        ["roomid", "wxids"],
        read_only=False,
    ),
    "add_room_members": _build_tool_schema(
        "add_room_members",
        "直接向群聊添加成员。",
        {
            "roomid": {"type": "string", "description": "群聊 ID。"},
            "wxids": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ],
                "description": "联系人 wxid 或 wxid 数组。",
            },
            "wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"},
        },
        ["roomid", "wxids"],
        read_only=False,
    ),
    "delete_room_members": _build_tool_schema(
        "delete_room_members",
        "从群聊删除成员。",
        {
            "roomid": {"type": "string", "description": "群聊 ID。"},
            "wxids": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ],
                "description": "联系人 wxid 或 wxid 数组。",
            },
            "wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"},
        },
        ["roomid", "wxids"],
        read_only=False,
    ),
}


def _get_mcp_server_source_path() -> Path | None:
    for path in MCP_SERVER_SOURCE_CANDIDATES:
        if path.exists():
            return path
    return None


def _get_ast_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _get_ast_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Subscript):
        return _get_ast_name(node.value)
    return ""


def _merge_schema_types(*schemas: dict[str, Any]) -> dict[str, Any]:
    type_values: list[str] = []
    for schema in schemas:
        schema_type = schema.get("type")
        if isinstance(schema_type, list):
            for item in schema_type:
                if isinstance(item, str) and item not in type_values:
                    type_values.append(item)
        elif isinstance(schema_type, str) and schema_type not in type_values:
            type_values.append(schema_type)
    if not type_values:
        return dict(_JSON_OBJECT_SCHEMA)
    return {"type": type_values if len(type_values) > 1 else type_values[0]}


def _annotation_node_to_schema(node: ast.AST | None) -> dict[str, Any]:
    if node is None:
        return {"type": "string"}
    if isinstance(node, ast.Name):
        name = node.id
        if name == "str":
            return {"type": "string"}
        if name == "int":
            return {"type": "integer"}
        if name == "float":
            return {"type": "number"}
        if name == "bool":
            return {"type": "boolean"}
        return dict(_JSON_OBJECT_SCHEMA)
    if isinstance(node, ast.Constant) and node.value is None:
        return {"type": "null"}
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _merge_schema_types(_annotation_node_to_schema(node.left), _annotation_node_to_schema(node.right))
    if isinstance(node, ast.Subscript):
        base_name = _get_ast_name(node.value)
        slice_node = node.slice if not isinstance(node.slice, ast.Index) else node.slice.value
        if base_name in {"list", "tuple", "set"}:
            return {"type": "array", "items": _annotation_node_to_schema(slice_node)}
        if base_name == "dict":
            return dict(_JSON_OBJECT_SCHEMA)
        return _annotation_node_to_schema(slice_node)
    return dict(_JSON_OBJECT_SCHEMA)


def _safe_literal_eval(node: ast.AST | None) -> Any:
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def _extract_mcp_tool_meta(node: ast.AsyncFunctionDef) -> dict[str, Any] | None:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if _get_ast_name(decorator.func) != "mcp.tool":
            continue
        tool_name = ""
        description = ""
        read_only = False
        for keyword in decorator.keywords:
            if keyword.arg == "name":
                tool_name = str(_safe_literal_eval(keyword.value) or "").strip()
            elif keyword.arg == "description":
                description = str(_safe_literal_eval(keyword.value) or "").strip()
            elif keyword.arg == "annotations":
                annotations = _safe_literal_eval(keyword.value)
                if isinstance(annotations, dict):
                    read_only = bool(annotations.get("readOnlyHint"))
        return {
            "name": tool_name or node.name.removeprefix("tool_"),
            "description": description or node.name.removeprefix("tool_").replace("_", " "),
            "read_only": read_only,
        }
    return None


def _parse_mcp_tool_registry(source_text: str) -> dict[str, dict[str, Any]]:
    module = ast.parse(source_text)
    registry: dict[str, dict[str, Any]] = {}
    for node in module.body:
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        meta = _extract_mcp_tool_meta(node)
        if not meta:
            continue

        properties: dict[str, Any] = {}
        required: list[str] = []
        positional_args = list(node.args.args)
        defaults = [None] * (len(positional_args) - len(node.args.defaults)) + list(node.args.defaults)
        for argument, default_value in zip(positional_args, defaults):
            if argument.arg == "ctx":
                continue
            schema = _annotation_node_to_schema(argument.annotation)
            literal_default = _safe_literal_eval(default_value)
            if literal_default is not None:
                schema = {**schema, "default": literal_default}
            properties[argument.arg] = schema
            if default_value is None:
                required.append(argument.arg)

        registry[meta["name"]] = _build_tool_schema(
            meta["name"],
            meta["description"],
            properties,
            required,
            read_only=meta["read_only"],
        )
    return registry


@lru_cache(maxsize=1)
def get_tool_registry() -> dict[str, dict[str, Any]]:
    source_path = _get_mcp_server_source_path()
    if source_path is None:
        return TOOL_REGISTRY
    try:
        return _parse_mcp_tool_registry(source_path.read_text(encoding="utf-8")) or TOOL_REGISTRY
    except Exception:
        return TOOL_REGISTRY


def _merge_model_names(*values: Any) -> list[str]:
    items: list[str] = []
    for value in values:
        if isinstance(value, str):
            normalized = value.strip()
            if normalized and normalized not in items:
                items.append(normalized)
            continue
        for item in value if isinstance(value, list) else []:
            normalized = str(item or "").strip()
            if normalized and normalized not in items:
                items.append(normalized)
    return items


def _parse_provider_model_names(payload: Any) -> list[str]:
    container = payload if isinstance(payload, dict) else {}
    raw_items = container.get("data") if isinstance(container.get("data"), list) else container.get("models")
    items = raw_items if isinstance(raw_items, list) else []
    model_names: list[str] = []
    for item in items:
        if isinstance(item, dict):
            candidate = item.get("id") or item.get("model") or item.get("name")
        else:
            candidate = item
        normalized = str(candidate or "").strip()
        if normalized and normalized not in model_names:
            model_names.append(normalized)
    return model_names


def _request_provider_models(
    base_url: str,
    api_key: str,
    headers: dict[str, str] | None = None,
    models_path: str = "/models",
    timeout: float = 30.0,
) -> list[str]:
    url = _build_provider_url(base_url, models_path)
    req = request.Request(
        url,
        headers=dict(headers or _build_provider_request_headers("openai", api_key)),
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            response_text = response.read().decode("utf-8")
    except Exception as exc:
        raise RuntimeError(f"读取模型列表失败: {exc}") from exc
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"模型列表返回了非 JSON 响应: {response_text}") from exc
    model_names = _parse_provider_model_names(payload)
    if not model_names:
        raise RuntimeError("模型列表为空")
    return model_names


async def _load_provider_config_model_options(provider_key: str, provider_config: dict[str, Any]) -> dict[str, Any]:
    provider_meta = PROVIDER_CATALOG[provider_key]
    default_model = provider_meta["default_model"]
    model_names: list[str] = []
    error_message = ""
    if provider_config.get("api_key"):
        try:
            model_names = await asyncio.to_thread(
                _request_provider_models,
                _get_provider_runtime_base_url(provider_key, provider_config),
                str(provider_config.get("api_key") or ""),
                _build_provider_request_headers(provider_key, str(provider_config.get("api_key") or "")),
                provider_meta.get("models_path") or "/models",
            )
        except Exception as exc:
            error_message = str(exc)
    merged_names = _merge_model_names(model_names, default_model if provider_config.get("api_key") else [])
    option_items = [
        {
            "label": f"{provider_config['name']} / {model_name}",
            "value": model_name,
            "config_id": provider_config["id"],
            "config_name": provider_config["name"],
        }
        for model_name in merged_names
    ]
    return {
        "config_id": provider_config["id"],
        "config_name": provider_config["name"],
        "options": option_items,
        "error": error_message,
    }


async def _load_provider_model_options(provider_key: str, provider_settings: dict[str, Any]) -> dict[str, Any]:
    configs = provider_settings.get("configs") if isinstance(provider_settings.get("configs"), list) else []
    model_results = await asyncio.gather(
        *[_load_provider_config_model_options(provider_key, provider_config) for provider_config in configs]
    ) if configs else []

    options: list[dict[str, Any]] = []
    config_payloads: dict[str, dict[str, Any]] = {}
    error_messages: list[str] = []
    for result in model_results:
        config_id = str(result.get("config_id") or "")
        config_payloads[config_id] = {
            "options": result.get("options") if isinstance(result.get("options"), list) else [],
            "error": str(result.get("error") or "").strip(),
        }
        options.extend(config_payloads[config_id]["options"])
        if config_payloads[config_id]["error"]:
            error_messages.append(f"{result.get('config_name')}: {config_payloads[config_id]['error']}")
    return {
        "options": options,
        "error": "；".join(error_messages),
        "configs": config_payloads,
    }


def get_default_ai_assistant_settings() -> dict[str, Any]:
    return deepcopy(DEFAULT_AI_ASSISTANT_SETTINGS)


def _normalize_provider_base_url(value: Any, default: str) -> str:
    normalized = str(value or default).strip()
    return normalized.rstrip("/") or default


def _clamp_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, numeric))


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, numeric))


def _build_default_provider_config(provider_key: str, provider_meta: dict[str, Any], index: int = 1) -> dict[str, Any]:
    return {
        "id": f"{provider_key}-config-{index}",
        "name": f"{provider_meta['label']} 配置 {index}",
        "enabled": False,
        "api_key": "",
        "base_url": provider_meta["default_base_url"],
    }


def _normalize_provider_config_entries(provider_key: str, provider_meta: dict[str, Any], raw_provider: dict[str, Any]) -> list[dict[str, Any]]:
    raw_configs = raw_provider.get("configs") if isinstance(raw_provider.get("configs"), list) else None
    normalized_configs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def append_config(item: dict[str, Any], index: int) -> None:
        default_item = _build_default_provider_config(provider_key, provider_meta, index)
        normalized_id = str(item.get("id") or default_item["id"]).strip() or default_item["id"]
        if normalized_id in seen_ids:
            normalized_id = f"{normalized_id}-{index}"
        seen_ids.add(normalized_id)
        api_key = str(item.get("api_key") or "").strip()
        enabled_raw = item.get("enabled")
        enabled = bool(enabled_raw) if enabled_raw is not None else bool(api_key)
        normalized_configs.append(
            {
                "id": normalized_id,
                "name": str(item.get("name") or default_item["name"]).strip() or default_item["name"],
                "enabled": enabled,
                "api_key": api_key,
                "base_url": _normalize_provider_base_url(
                    item.get("base_url"),
                    provider_meta["default_base_url"],
                ) if provider_meta.get("allow_custom_base_url") else provider_meta["default_base_url"],
            }
        )

    if raw_configs is not None:
        for index, raw_config in enumerate(raw_configs, start=1):
            if not isinstance(raw_config, dict):
                continue
            append_config(raw_config, index)
    elif any(key in raw_provider for key in {"enabled", "api_key", "base_url", "id", "name"}):
        append_config(
            {
                "id": raw_provider.get("id") or f"{provider_key}-config-1",
                "name": raw_provider.get("name") or f"{provider_meta['label']} 默认配置",
                "enabled": raw_provider.get("enabled"),
                "api_key": raw_provider.get("api_key"),
                "base_url": raw_provider.get("base_url"),
            },
            1,
        )

    return normalized_configs


def _get_provider_runtime_base_url(provider_key: str, provider_config: dict[str, Any]) -> str:
    provider_meta = PROVIDER_CATALOG[provider_key]
    if provider_meta.get("allow_custom_base_url"):
        return _normalize_provider_base_url(provider_config.get("base_url"), provider_meta["default_base_url"])
    return provider_meta["default_base_url"]


def _build_provider_request_headers(provider_key: str, api_key: str) -> dict[str, str]:
    provider_meta = PROVIDER_CATALOG[provider_key]
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    custom_headers = provider_meta.get("custom_headers") if isinstance(provider_meta.get("custom_headers"), dict) else {}
    for header_key, header_value in custom_headers.items():
        normalized_header_key = str(header_key or "").strip()
        if normalized_header_key:
            headers[normalized_header_key] = str(header_value or "")
    return headers


def _merge_provider_extra_body(provider_key: str, request_payload: dict[str, Any]) -> dict[str, Any]:
    provider_meta = PROVIDER_CATALOG[provider_key]
    extra_body = provider_meta.get("extra_body") if isinstance(provider_meta.get("extra_body"), dict) else {}
    return {**request_payload, **extra_body}


def _resolve_provider_runtime_config(settings: dict[str, Any], provider_key: str, provider_config_id: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    provider_meta = PROVIDER_CATALOG[provider_key]
    provider_settings = settings.get("providers", {}).get(provider_key) if isinstance(settings.get("providers"), dict) else {}
    configs = provider_settings.get("configs") if isinstance(provider_settings.get("configs"), list) else []
    normalized_config_id = str(provider_config_id or "").strip()
    selected_config = next((item for item in configs if str(item.get("id") or "") == normalized_config_id), None)
    if selected_config is None:
        selected_config = next((item for item in configs if item.get("enabled") and item.get("api_key")), None)
    if selected_config is None:
        selected_config = next((item for item in configs if item.get("api_key")), None)
    if selected_config is None:
        raise RuntimeError("当前 AI 厂商还没有可用的 API Key 配置")
    return provider_meta, selected_config


def normalize_ai_assistant_settings(value: Any) -> dict[str, Any]:
    defaults = get_default_ai_assistant_settings()
    raw_settings = value if isinstance(value, dict) else {}
    raw_providers = raw_settings.get("providers") if isinstance(raw_settings.get("providers"), dict) else {}
    providers: dict[str, dict[str, Any]] = {}
    for provider_key, provider_meta in PROVIDER_CATALOG.items():
        raw_provider = raw_providers.get(provider_key) if isinstance(raw_providers.get(provider_key), dict) else {}
        configs = _normalize_provider_config_entries(provider_key, provider_meta, raw_provider)
        providers[provider_key] = {
            "configured": any(bool(item.get("api_key")) for item in configs),
            "enabled": any(bool(item.get("enabled") and item.get("api_key")) for item in configs),
            "configs": configs,
        }

    active_provider = str(raw_settings.get("active_provider") or defaults["active_provider"]).strip().lower()
    if active_provider not in PROVIDER_CATALOG:
        active_provider = defaults["active_provider"]

    return {
        "active_provider": active_provider,
        "system_prompt": str(raw_settings.get("system_prompt") or defaults["system_prompt"]).strip() or defaults["system_prompt"],
        "temperature": _clamp_float(raw_settings.get("temperature"), defaults["temperature"], 0.0, 1.5),
        "max_tool_rounds": _clamp_int(raw_settings.get("max_tool_rounds"), defaults["max_tool_rounds"], 1, 8),
        "providers": providers,
    }


async def build_ai_assistant_payload(settings: dict[str, Any]) -> dict[str, Any]:
    normalized_settings = normalize_ai_assistant_settings(settings)
    provider_keys = list(PROVIDER_CATALOG.keys())
    model_option_results = await asyncio.gather(
        *[_load_provider_model_options(provider_key, normalized_settings["providers"][provider_key]) for provider_key in provider_keys]
    )
    providers = []
    for provider_index, provider_key in enumerate(provider_keys):
        provider_meta = PROVIDER_CATALOG[provider_key]
        provider_settings = normalized_settings["providers"][provider_key]
        model_options = model_option_results[provider_index]
        config_states = model_options.get("configs") if isinstance(model_options.get("configs"), dict) else {}
        config_payloads = []
        for provider_config in provider_settings["configs"]:
            config_state = config_states.get(provider_config["id"], {"options": [], "error": ""})
            config_payloads.append(
                {
                    "id": provider_config["id"],
                    "name": provider_config["name"],
                    "enabled": provider_config["enabled"],
                    "configured": bool(provider_config["api_key"]),
                    "base_url": provider_config["base_url"],
                    "base_url_editable": bool(provider_meta.get("allow_custom_base_url")),
                    "model_options": config_state.get("options") if isinstance(config_state.get("options"), list) else [],
                    "model_fetch_error": str(config_state.get("error") or "").strip(),
                }
            )
        providers.append(
            {
                **provider_meta,
                "enabled": provider_settings["enabled"],
                "configured": provider_settings["configured"],
                "default_config_id": next(
                    (
                        item["id"]
                        for item in provider_settings["configs"]
                        if item.get("enabled") and item.get("api_key")
                    ),
                    provider_settings["configs"][0]["id"] if provider_settings["configs"] else "",
                ),
                "configs": config_payloads,
                "model_options": model_options["options"],
                "model_fetch_error": model_options["error"],
            }
        )
    return {
        "settings": normalized_settings,
        "providers": providers,
        "tools": list_available_tools(),
        "notes": [
            "配置会保存在本地 SQLite 的 system_settings 表中。",
            "固定厂商的网关地址、请求路径和附加参数均写死在代码中；通用 OpenAI 仅需额外填写 Base URL。",
        ],
    }


def list_available_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": definition["name"],
            "description": definition["description"],
            "read_only": definition["read_only"],
        }
        for definition in get_tool_registry().values()
    ]


def get_tool_schemas() -> list[dict[str, Any]]:
    return [definition["schema"] for definition in get_tool_registry().values()]


def _coerce_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _coerce_text(value: Any) -> str:
    return str(value or "").strip()


def _coerce_string_sequence(value: Any) -> list[str] | str:
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return str(value or "").strip()


def _safe_trim_string(value: Any) -> str:
    text = str(value or "")
    if len(text) <= MAX_TOOL_RESULT_STRING_LENGTH:
        return text
    return f"{text[:MAX_TOOL_RESULT_STRING_LENGTH]}...<truncated>"


def _compact_tool_result(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _compact_tool_result(item) for key, item in value.items()}
    if isinstance(value, list):
        items = [_compact_tool_result(item) for item in value[:MAX_TOOL_RESULT_ITEMS]]
        if len(value) > MAX_TOOL_RESULT_ITEMS:
            items.append({"_truncated": len(value) - MAX_TOOL_RESULT_ITEMS})
        return items
    if isinstance(value, str):
        return _safe_trim_string(value)
    return value


def _clamp_limit(value: Any, default: int = 20, maximum: int = 100) -> int:
    try:
        numeric_value = int(value)
    except (TypeError, ValueError):
        return default
    if numeric_value <= 0:
        return default
    return min(numeric_value, maximum)


def _search_items(items: list[dict[str, Any]], query: str, fields: list[str], limit: int = 20) -> dict[str, Any]:
    normalized_query = str(query or "").strip().lower()
    if not normalized_query:
        raise RuntimeError("query 不能为空")
    limited = _clamp_limit(limit)
    results = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        searchable_text = "\n".join(str(item.get(field) or "") for field in fields).lower()
        if normalized_query in searchable_text:
            results.append(item)
            if len(results) >= limited:
                break
    return {
        "query": query,
        "limit": limited,
        "count": len(results),
        "items": results,
    }


def _summarize_contacts(contacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "wxid": item.get("wxid", ""),
            "wxh": item.get("wxh", ""),
            "nickname": item.get("nickname", ""),
            "remarks": item.get("remarks", ""),
        }
        for item in contacts if isinstance(item, dict)
    ]


def _summarize_room_members(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "username": item.get("username", ""),
            "alias": item.get("alias", ""),
            "nick_name": item.get("nick_name", ""),
            "room_nick_name": item.get("room_nick_name", ""),
            "remarks": item.get("remarks", ""),
        }
        for item in members if isinstance(item, dict)
    ]


def _normalize_message_content(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                if item.get("type") in {"text", "input_text", "output_text"}:
                    parts.append(str(item.get("text") or item.get("content") or "").strip())
                elif isinstance(item.get("text"), str):
                    parts.append(item["text"].strip())
            elif item not in (None, ""):
                parts.append(str(item).strip())
        return "\n".join(part for part in parts if part)
    if value in (None, ""):
        return ""
    return str(value).strip()


def _normalize_reasoning_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value in (None, ""):
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _normalize_chat_history(
    messages: list[dict[str, Any]] | None,
    *,
    include_reasoning_content: bool = False,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = _normalize_message_content(message.get("content"))
        reasoning_content = _normalize_reasoning_content(message.get("reasoning_content"))
        if not content and not reasoning_content:
            continue
        normalized_message: dict[str, Any] = {"role": role, "content": content}
        if include_reasoning_content and role == "assistant" and reasoning_content:
            normalized_message["reasoning_content"] = reasoning_content
        normalized.append(normalized_message)
    return normalized[-MAX_CONVERSATION_MESSAGES:]


def _build_provider_url(base_url: str, chat_path: str) -> str:
    normalized_path = str(chat_path or "/chat/completions").strip() or "/chat/completions"
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"
    return f"{base_url.rstrip('/')}{normalized_path}"


def _request_provider_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float = 90.0) -> dict[str, Any]:
    request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=request_body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as response:
            response_text = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"AI 接口调用失败，HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"AI 接口调用失败: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("AI 接口调用超时") from exc

    try:
        payload_json = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AI 接口返回了非 JSON 响应: {response_text}") from exc

    if isinstance(payload_json, dict) and payload_json.get("error"):
        raise RuntimeError(f"AI 接口返回错误: {payload_json['error']}")
    if not isinstance(payload_json, dict):
        raise RuntimeError("AI 接口返回格式异常")
    return payload_json


def _normalize_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    raw_tool_calls = message.get("tool_calls")
    if not isinstance(raw_tool_calls, list):
        return []
    tool_calls: list[dict[str, Any]] = []
    for item in raw_tool_calls:
        if not isinstance(item, dict):
            continue
        function_payload = item.get("function") if isinstance(item.get("function"), dict) else {}
        name = str(function_payload.get("name") or "").strip()
        if not name:
            continue
        raw_arguments = function_payload.get("arguments")
        if isinstance(raw_arguments, str):
            arguments_text = raw_arguments
        elif raw_arguments in (None, ""):
            arguments_text = "{}"
        else:
            arguments_text = json.dumps(raw_arguments, ensure_ascii=False)
        try:
            arguments = json.loads(arguments_text)
        except (TypeError, ValueError, json.JSONDecodeError):
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        tool_calls.append(
            {
                "id": str(item.get("id") or f"tool_{len(tool_calls) + 1}"),
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments, ensure_ascii=False),
                },
                "arguments": arguments,
            }
        )
    return tool_calls


async def _emit_progress(progress_callback: Any, payload: dict[str, Any]) -> None:
    if progress_callback is None:
        return
    callback_result = progress_callback(payload)
    if inspect.isawaitable(callback_result):
        await callback_result


async def _execute_tool_call(api_client: WxRobotApiClient, tool_name: str, arguments: dict[str, Any]) -> Any:
    if tool_name == "introduction":
        return await api_client.get_json("/introduction")
    if tool_name == "get_users":
        return await api_client.get_logged_in_users()
    if tool_name == "get_labels":
        return await api_client.get_labels(_coerce_optional_int(arguments.get("wxpid")))
    if tool_name == "get_wx_pids":
        return await api_client.get_wx_pids()
    if tool_name == "hook":
        return await api_client.hook()
    if tool_name == "get_user_list":
        return await api_client.get_user_list(_coerce_optional_int(arguments.get("wxpid")))
    if tool_name == "get_user_list_summary":
        return _summarize_contacts(await api_client.get_user_list(_coerce_optional_int(arguments.get("wxpid"))))
    if tool_name == "search_user_list":
        friends = await api_client.get_user_list(_coerce_optional_int(arguments.get("wxpid")))
        return _search_items(friends, _coerce_text(arguments.get("query")), ["wxid", "wxh", "nickname", "remarks", "signature", "province", "city", "labels"], _clamp_limit(arguments.get("limit")))
    if tool_name == "get_room_list":
        return await api_client.get_room_list(_coerce_optional_int(arguments.get("wxpid")))
    if tool_name == "get_room_list_summary":
        return _summarize_contacts(await api_client.get_room_list(_coerce_optional_int(arguments.get("wxpid"))))
    if tool_name == "search_room_list":
        rooms = await api_client.get_room_list(_coerce_optional_int(arguments.get("wxpid")))
        return _search_items(rooms, _coerce_text(arguments.get("query")), ["wxid", "wxh", "nickname", "remarks", "signature", "province", "city", "labels"], _clamp_limit(arguments.get("limit")))
    if tool_name == "get_biz_list":
        return await api_client.get_biz_list(_coerce_optional_int(arguments.get("wxpid")))
    if tool_name == "get_biz_list_summary":
        return _summarize_contacts(await api_client.get_biz_list(_coerce_optional_int(arguments.get("wxpid"))))
    if tool_name == "search_biz_list":
        biz_list = await api_client.get_biz_list(_coerce_optional_int(arguments.get("wxpid")))
        return _search_items(biz_list, _coerce_text(arguments.get("query")), ["wxid", "wxh", "nickname", "remarks", "signature", "province", "city", "labels"], _clamp_limit(arguments.get("limit")))
    if tool_name == "get_chat_msg":
        return await api_client.post_json(
            "/other/chatmsg",
            api_client._with_optional_wxpid(
                {"msgid": _coerce_text(arguments.get("msgid")), "wxid": _coerce_text(arguments.get("wxid"))},
                _coerce_optional_int(arguments.get("wxpid")),
            ),
        )
    if tool_name == "get_chat_msgs":
        return await api_client.get_chat_messages(
            wxid=_coerce_text(arguments.get("wxid")),
            start_time=arguments.get("start_time"),
            end_time=arguments.get("end_time"),
            max_count=_clamp_int(arguments.get("max_count"), 500, 1, 2000),
            wxpid=_coerce_optional_int(arguments.get("wxpid")),
        )
    if tool_name == "get_room_members":
        return await api_client.get_room_members(_coerce_text(arguments.get("roomid")), _coerce_optional_int(arguments.get("wxpid")))
    if tool_name == "get_room_members_summary":
        return _summarize_room_members(await api_client.get_room_members(_coerce_text(arguments.get("roomid")), _coerce_optional_int(arguments.get("wxpid"))))
    if tool_name == "search_room_members":
        members = await api_client.get_room_members(_coerce_text(arguments.get("roomid")), _coerce_optional_int(arguments.get("wxpid")))
        return _search_items(members, _coerce_text(arguments.get("query")), ["username", "alias", "nick_name", "room_nick_name", "remarks", "signature", "province", "city"], _clamp_limit(arguments.get("limit")))
    if tool_name == "get_user_info":
        return await api_client.get_user_info(
            _coerce_text(arguments.get("wxid")),
            _coerce_text(arguments.get("roomid")),
            _coerce_optional_int(arguments.get("wxpid")),
        )
    if tool_name == "get_user_sns_permission":
        return await api_client.post_json(
            "/user/snspermission",
            api_client._with_optional_wxpid(
                {"wxid": _coerce_text(arguments.get("wxid")), "roomid": _coerce_text(arguments.get("roomid"))},
                _coerce_optional_int(arguments.get("wxpid")),
            ),
        )
    if tool_name == "check_user_state":
        return await api_client.check_user_state(_coerce_text(arguments.get("wxid")), _coerce_optional_int(arguments.get("wxpid")))
    if tool_name == "get_resource_path":
        return await api_client.get_resource_path(
            _coerce_text(arguments.get("msgid")),
            _coerce_text(arguments.get("wxid")),
            _clamp_int(arguments.get("local_type"), 0, 0, 2**31 - 1),
            _coerce_optional_int(arguments.get("wxpid")),
        )
    if tool_name == "cdn_download_image":
        return await api_client.download_cdn_image(
            msgid=_coerce_text(arguments.get("msgid")),
            wxid=_coerce_text(arguments.get("wxid")),
            wxpid=_coerce_optional_int(arguments.get("wxpid")),
            flag=_clamp_int(arguments.get("flag"), 1, 1, 3),
            wait=_coerce_bool(arguments.get("wait"), False),
            timeout=_clamp_int(arguments.get("timeout"), 5, 1, 60),
        )
    if tool_name == "cdn_download_video":
        return await api_client.download_cdn_video(
            msgid=_coerce_text(arguments.get("msgid")),
            wxid=_coerce_text(arguments.get("wxid")),
            wxpid=_coerce_optional_int(arguments.get("wxpid")),
            wait=_coerce_bool(arguments.get("wait"), False),
            timeout=_clamp_int(arguments.get("timeout"), 5, 1, 60),
        )
    if tool_name == "cdn_download_file":
        return await api_client.download_cdn_file(
            msgid=_coerce_text(arguments.get("msgid")),
            wxid=_coerce_text(arguments.get("wxid")),
            wxpid=_coerce_optional_int(arguments.get("wxpid")),
            wait=_coerce_bool(arguments.get("wait"), False),
            timeout=_clamp_int(arguments.get("timeout"), 5, 1, 60),
        )
    if tool_name == "add_label":
        return await api_client.add_label(_coerce_text(arguments.get("label_name")), _coerce_optional_int(arguments.get("wxpid")))
    if tool_name in {"set_label", "set_labels"}:
        return await api_client.set_labels(
            _coerce_text(arguments.get("wxid")),
            _coerce_string_sequence(arguments.get("labels")),
            _coerce_optional_int(arguments.get("wxpid")),
        )
    if tool_name in {"delete_label", "delete_labels"}:
        return await api_client.delete_labels(_coerce_string_sequence(arguments.get("labels")), _coerce_optional_int(arguments.get("wxpid")))
    if tool_name == "send_text":
        return await api_client.send_text(
            wxid=_coerce_text(arguments.get("wxid")),
            content=_coerce_text(arguments.get("content")),
            atlist=_coerce_text(arguments.get("atlist")),
            wxpid=_coerce_optional_int(arguments.get("wxpid")),
            wait=_coerce_bool(arguments.get("wait"), False),
            timeout=_clamp_int(arguments.get("timeout"), 3, 1, 30),
        )
    if tool_name == "send_image":
        return await api_client.send_image(
            wxid=_coerce_text(arguments.get("wxid")),
            path=_coerce_text(arguments.get("path")),
            wxpid=_coerce_optional_int(arguments.get("wxpid")),
            wait=_coerce_bool(arguments.get("wait"), False),
            timeout=_clamp_int(arguments.get("timeout"), 3, 1, 30),
        )
    if tool_name == "send_file":
        return await api_client.send_file(
            wxid=_coerce_text(arguments.get("wxid")),
            path=_coerce_text(arguments.get("path")),
            wxpid=_coerce_optional_int(arguments.get("wxpid")),
            wait=_coerce_bool(arguments.get("wait"), False),
            timeout=_clamp_int(arguments.get("timeout"), 3, 1, 30),
        )
    if tool_name == "send_video":
        return await api_client.send_video(
            wxid=_coerce_text(arguments.get("wxid")),
            path=_coerce_text(arguments.get("path")),
            wxpid=_coerce_optional_int(arguments.get("wxpid")),
            wait=_coerce_bool(arguments.get("wait"), False),
            timeout=_clamp_int(arguments.get("timeout"), 3, 1, 30),
        )
    if tool_name == "send_gif":
        return await api_client.send_gif(
            wxid=_coerce_text(arguments.get("wxid")),
            path=_coerce_text(arguments.get("path")),
            wxpid=_coerce_optional_int(arguments.get("wxpid")),
            wait=_coerce_bool(arguments.get("wait"), False),
            timeout=_clamp_int(arguments.get("timeout"), 3, 1, 30),
        )
    if tool_name == "send_card":
        return await api_client.post_json(
            "/send/card",
            api_client._with_optional_wxpid(
                {
                    "wxid": _coerce_text(arguments.get("wxid")),
                    "card_wxid": _coerce_text(arguments.get("card_wxid")),
                    "nickname": _coerce_text(arguments.get("nickname")),
                    "bigheadimgurl": _coerce_text(arguments.get("bigheadimgurl")),
                    "smallheadimgurl": _coerce_text(arguments.get("smallheadimgurl")),
                    "sex": _coerce_text(arguments.get("sex")),
                    "fullpy": _coerce_text(arguments.get("fullpy")),
                    "alias": _coerce_text(arguments.get("alias")),
                    "province": _coerce_text(arguments.get("province")),
                    "city": _coerce_text(arguments.get("city")),
                    "wait": _coerce_bool(arguments.get("wait"), False),
                    "timeout": _clamp_int(arguments.get("timeout"), 3, 1, 30),
                },
                _coerce_optional_int(arguments.get("wxpid")),
            ),
        )
    if tool_name == "send_article":
        return await api_client.post_json(
            "/send/article",
            api_client._with_optional_wxpid(
                {
                    "wxid": _coerce_text(arguments.get("wxid")),
                    "title": _coerce_text(arguments.get("title")),
                    "url": _coerce_text(arguments.get("url")),
                    "cover": _coerce_text(arguments.get("cover")),
                    "ghid": _coerce_text(arguments.get("ghid")),
                    "nickname": _coerce_text(arguments.get("nickname")),
                    "desc": _coerce_text(arguments.get("desc")),
                    "wait": _coerce_bool(arguments.get("wait"), False),
                    "timeout": _clamp_int(arguments.get("timeout"), 3, 1, 30),
                },
                _coerce_optional_int(arguments.get("wxpid")),
            ),
        )
    if tool_name == "send_quote":
        return await api_client.post_json(
            "/send/quote",
            api_client._with_optional_wxpid(
                {
                    "wxid": _coerce_text(arguments.get("wxid")),
                    "msgid": _coerce_text(arguments.get("msgid")),
                    "content": _coerce_text(arguments.get("content")),
                    "atlist": _coerce_text(arguments.get("atlist")),
                    "wait": _coerce_bool(arguments.get("wait"), False),
                    "timeout": _clamp_int(arguments.get("timeout"), 3, 1, 30),
                },
                _coerce_optional_int(arguments.get("wxpid")),
            ),
        )
    if tool_name == "send_revoke":
        return await api_client.post_json(
            "/send/revoke",
            api_client._with_optional_wxpid(
                {"wxid": _coerce_text(arguments.get("wxid")), "msgid": _coerce_text(arguments.get("msgid"))},
                _coerce_optional_int(arguments.get("wxpid")),
            ),
        )
    if tool_name == "forward_msg":
        return await api_client.post_json(
            "/send/forward",
            api_client._with_optional_wxpid(
                {
                    "msgid": _coerce_text(arguments.get("msgid")),
                    "msg_wxid": _coerce_text(arguments.get("msg_wxid")),
                    "wxid": _coerce_text(arguments.get("wxid")),
                },
                _coerce_optional_int(arguments.get("wxpid")),
            ),
        )
    if tool_name == "set_remarks":
        return await api_client.set_remarks(
            _coerce_text(arguments.get("wxid")),
            _coerce_text(arguments.get("remarks")),
            _coerce_optional_int(arguments.get("wxpid")),
        )
    if tool_name in {"del_user", "delete_user"}:
        return await api_client.delete_user(_coerce_text(arguments.get("wxid")), _coerce_optional_int(arguments.get("wxpid")))
    if tool_name == "receive_notify":
        return await api_client.receive_notify(
            _coerce_text(arguments.get("wxid")),
            _coerce_bool(arguments.get("notify"), True),
            _coerce_optional_int(arguments.get("wxpid")),
        )
    if tool_name == "agree_friend_request":
        return await api_client.agree_friend_request(
            wxid=_coerce_text(arguments.get("wxid")),
            v4=_coerce_text(arguments.get("v4")),
            remarks=_coerce_text(arguments.get("remarks")),
            labels=_coerce_text(arguments.get("labels")),
            sns_permissions=_clamp_int(arguments.get("sns_permissions"), 1, 0, 10),
            add_type=_clamp_int(arguments.get("add_type"), 1, 0, 10),
            wxpid=_coerce_optional_int(arguments.get("wxpid")),
        )
    if tool_name == "create_room":
        return await api_client.post_json(
            "/room/create",
            api_client._with_optional_wxpid(
                {"wxids": _coerce_text(arguments.get("wxids"))},
                _coerce_optional_int(arguments.get("wxpid")),
            ),
        )
    if tool_name == "quit_room":
        return await api_client.post_json(
            "/room/quit",
            api_client._with_optional_wxpid(
                {"roomid": _coerce_text(arguments.get("roomid")), "keep_msg": _coerce_bool(arguments.get("keep_msg"), False)},
                _coerce_optional_int(arguments.get("wxpid")),
            ),
        )
    if tool_name == "agree_room_invite":
        return await api_client.post_json(
            "/room/agreeinvite",
            api_client._with_optional_wxpid(
                {"wxid": _coerce_text(arguments.get("wxid")), "msgid": _coerce_text(arguments.get("msgid"))},
                _coerce_optional_int(arguments.get("wxpid")),
            ),
        )
    if tool_name in {"invite_members", "invite_room_members"}:
        return await api_client.invite_room_members(
            _coerce_text(arguments.get("roomid")),
            _coerce_string_sequence(arguments.get("wxids")),
            _coerce_optional_int(arguments.get("wxpid")),
        )
    if tool_name in {"add_members", "add_room_members"}:
        return await api_client.add_room_members(
            _coerce_text(arguments.get("roomid")),
            _coerce_string_sequence(arguments.get("wxids")),
            _coerce_optional_int(arguments.get("wxpid")),
        )
    if tool_name in {"delete_members", "delete_room_members"}:
        return await api_client.delete_room_members(
            _coerce_text(arguments.get("roomid")),
            _coerce_string_sequence(arguments.get("wxids")),
            _coerce_optional_int(arguments.get("wxpid")),
        )
    if tool_name == "add_room_member":
        return await api_client.add_room_member(
            wxid=_coerce_text(arguments.get("wxid")),
            roomid=_coerce_text(arguments.get("roomid")),
            remarks=_coerce_text(arguments.get("remarks")),
            content=_coerce_text(arguments.get("content")),
            sns_permissions=_clamp_int(arguments.get("sns_permissions"), 0, 0, 10),
            wxpid=_coerce_optional_int(arguments.get("wxpid")),
        )
    if tool_name == "set_top_message":
        return await api_client.post_json(
            "/room/settopmessage",
            api_client._with_optional_wxpid(
                {"msgid": _coerce_text(arguments.get("msgid")), "roomid": _coerce_text(arguments.get("roomid"))},
                _coerce_optional_int(arguments.get("wxpid")),
            ),
        )
    if tool_name == "remove_top_message":
        return await api_client.post_json(
            "/room/removetopmessage",
            api_client._with_optional_wxpid(
                {"msgid": _coerce_text(arguments.get("msgid")), "roomid": _coerce_text(arguments.get("roomid"))},
                _coerce_optional_int(arguments.get("wxpid")),
            ),
        )
    if tool_name == "recv_transfer":
        return await api_client.post_json(
            "/other/recvtransfer",
            api_client._with_optional_wxpid(
                {"wxid": _coerce_text(arguments.get("wxid")), "msgid": _coerce_text(arguments.get("msgid"))},
                _coerce_optional_int(arguments.get("wxpid")),
            ),
        )
    if tool_name == "refund_transfer":
        return await api_client.post_json(
            "/other/refundtransfer",
            api_client._with_optional_wxpid(
                {"wxid": _coerce_text(arguments.get("wxid")), "msgid": _coerce_text(arguments.get("msgid"))},
                _coerce_optional_int(arguments.get("wxpid")),
            ),
        )
    if tool_name == "open_single_window":
        return await api_client.post_json(
            "/other/opensinglewindow",
            api_client._with_optional_wxpid(
                {"wxid": _coerce_text(arguments.get("wxid")), "nickname": _coerce_text(arguments.get("nickname"))},
                _coerce_optional_int(arguments.get("wxpid")),
            ),
        )
    if tool_name == "mm_decrypt":
        return await api_client.post_json(
            "/other/mmdecrypt",
            api_client._with_optional_wxpid(
                {"input_path": _coerce_text(arguments.get("input_path")), "output_path": _coerce_text(arguments.get("output_path"))},
                _coerce_optional_int(arguments.get("wxpid")),
            ),
        )
    if tool_name == "dont_revoke":
        return await api_client.post_json(
            "/other/dontrevoke",
            api_client._with_optional_wxpid(
                {"revoke": _coerce_bool(arguments.get("revoke"), True)},
                _coerce_optional_int(arguments.get("wxpid")),
            ),
        )
    raise RuntimeError(f"暂不支持工具 {tool_name}")


async def run_ai_assistant(
    settings: dict[str, Any],
    api_client: WxRobotApiClient,
    messages: list[dict[str, Any]] | None,
    provider_key: str | None = None,
    model_override: str | None = None,
    provider_config_id: str | None = None,
    progress_callback: Any = None,
) -> dict[str, Any]:
    normalized_settings = normalize_ai_assistant_settings(settings)
    selected_provider = str(provider_key or normalized_settings["active_provider"]).strip().lower()
    if selected_provider not in PROVIDER_CATALOG:
        raise RuntimeError("未找到可用的 AI 厂商配置")

    provider_settings = normalized_settings["providers"].get(selected_provider) or {}
    if not provider_settings.get("enabled"):
        raise RuntimeError("当前 AI 厂商未启用，请先在智能插件页启用后再使用")

    provider_meta, selected_provider_config = _resolve_provider_runtime_config(
        normalized_settings,
        selected_provider,
        provider_config_id,
    )
    if not selected_provider_config.get("enabled"):
        raise RuntimeError("当前所选 AI 配置未启用，请先在配置页启用后再使用")
    if not selected_provider_config.get("api_key"):
        raise RuntimeError("当前所选 AI 配置未填写 API Key，请先保存后再使用")

    include_reasoning_content = selected_provider == "deepseek"
    history = _normalize_chat_history(messages, include_reasoning_content=include_reasoning_content)
    if not history or history[-1]["role"] != "user":
        raise RuntimeError("请先输入要交给智能插件处理的问题")

    request_messages: list[dict[str, Any]] = [{"role": "system", "content": normalized_settings["system_prompt"]}, *history]
    tool_schemas = get_tool_schemas()
    trace_entries: list[dict[str, Any]] = []
    max_tool_rounds = normalized_settings["max_tool_rounds"]
    selected_model = str(model_override or provider_meta["default_model"] or "").strip() or provider_meta["default_model"]

    for _ in range(max_tool_rounds + 1):
        await _emit_progress(
            progress_callback,
            {
                "status": "running",
                "stage": "thinking",
                "progress_message": "模型思考中...",
                "content": "",
                "reasoning_content": "",
                "tool_traces": deepcopy(trace_entries),
            },
        )
        request_payload = {
            "model": selected_model,
            "messages": request_messages,
            "tools": tool_schemas,
            "tool_choice": "auto",
            "temperature": normalized_settings["temperature"],
        }
        request_payload = _merge_provider_extra_body(selected_provider, request_payload)

        headers = _build_provider_request_headers(selected_provider, str(selected_provider_config["api_key"]))

        response_payload = await asyncio.to_thread(
            _request_provider_json,
            _build_provider_url(
                _get_provider_runtime_base_url(selected_provider, selected_provider_config),
                provider_meta["chat_path"],
            ),
            request_payload,
            headers,
        )
        choices = response_payload.get("choices") if isinstance(response_payload, dict) else None
        if not isinstance(choices, list) or not choices:
            raise RuntimeError(f"AI 接口返回异常：{response_payload}")

        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        assistant_content = _normalize_message_content(message.get("content"))
        assistant_reasoning_content = _normalize_reasoning_content(message.get("reasoning_content"))
        tool_calls = _normalize_tool_calls(message)

        await _emit_progress(
            progress_callback,
            {
                "status": "running" if tool_calls else "completed",
                "stage": "tool-pending" if tool_calls else "completed",
                "progress_message": f"模型准备调用 {len(tool_calls)} 个工具" if tool_calls else "模型已生成最终回复",
                "content": assistant_content or "",
                "reasoning_content": assistant_reasoning_content,
                "tool_traces": deepcopy(trace_entries),
            },
        )

        if not tool_calls:
            await _emit_progress(
                progress_callback,
                {
                    "status": "completed",
                    "stage": "completed",
                    "progress_message": "已生成最终回复",
                    "content": assistant_content or "已完成，但 AI 没有返回可展示的文本。",
                    "reasoning_content": assistant_reasoning_content,
                    "tool_traces": deepcopy(trace_entries),
                },
            )
            return {
                "provider": selected_provider,
                "provider_label": provider_meta["label"],
                "provider_config_id": selected_provider_config["id"],
                "provider_config_name": selected_provider_config["name"],
                "model": selected_model,
                "reply": assistant_content or "已完成，但 AI 没有返回可展示的文本。",
                "reasoning_content": assistant_reasoning_content,
                "tool_traces": trace_entries,
                "usage": response_payload.get("usage") if isinstance(response_payload.get("usage"), dict) else {},
            }

        assistant_message_payload: dict[str, Any] = {
            "role": "assistant",
            "content": assistant_content or "",
            "tool_calls": [
                {
                    "id": item["id"],
                    "type": "function",
                    "function": item["function"],
                }
                for item in tool_calls
            ],
        }
        if include_reasoning_content and assistant_reasoning_content:
            assistant_message_payload["reasoning_content"] = assistant_reasoning_content
        request_messages.append(assistant_message_payload)

        for tool_call in tool_calls:
            tool_name = tool_call["function"]["name"]
            arguments = tool_call["arguments"]
            trace_entry = {
                "id": tool_call["id"],
                "name": tool_name,
                "arguments": arguments,
                "status": "ok",
                "error": "",
            }
            await _emit_progress(
                progress_callback,
                {
                    "status": "running",
                    "stage": "tool-running",
                    "progress_message": f"正在调用工具 {tool_name}",
                    "content": assistant_content or "",
                    "reasoning_content": assistant_reasoning_content,
                    "tool_traces": deepcopy([*trace_entries, trace_entry]),
                },
            )
            try:
                raw_result = await _execute_tool_call(api_client, tool_name, arguments)
                compact_result = _compact_tool_result(raw_result)
                tool_content = json.dumps({"ok": True, "result": compact_result}, ensure_ascii=False)
            except Exception as exc:
                trace_entry["status"] = "error"
                trace_entry["error"] = str(exc)
                tool_content = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
            trace_entries.append(trace_entry)
            await _emit_progress(
                progress_callback,
                {
                    "status": "running",
                    "stage": "tool-result",
                    "progress_message": f"工具 {tool_name} {'执行成功' if trace_entry['status'] == 'ok' else '执行失败'}",
                    "content": assistant_content or "",
                    "reasoning_content": assistant_reasoning_content,
                    "tool_traces": deepcopy(trace_entries),
                },
            )
            request_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": tool_content,
                }
            )

    raise RuntimeError("AI 工具调用轮数超过限制，请缩小问题范围后重试")
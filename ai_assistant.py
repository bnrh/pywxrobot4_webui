import asyncio
import ast
import inspect
import json
from datetime import datetime
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
    "当任务依赖当前时间、日期、星期或相对时间窗口时，不要猜测当前时刻，优先调用 current_datetime 获取精确时间。"
    "如果信息不足以安全执行写操作（例如发送消息、修改标签、邀请进群、删除成员），先向用户索取必要参数，"
    "不要臆造 wxid、roomid、wxpid、文件路径或消息内容。"
    "对于只读查询，尽量先调用工具获取事实，再给出简洁结论。"
    "当工具执行失败时，明确说明失败原因并给出下一步建议。"
)

INTERNAL_TOOL_ROUTING_PROMPT = (
    "工具选择规则："
    "当用户问题涉及现在几点、今天/昨天/明天、最近几小时、截至目前、本周、本月或其他相对时间判断时，"
    "优先调用 current_datetime 获取精确当前时间，再决定是否调用其他工具。"
    "当用户询问两个群聊是否有重复成员、共同成员、相同成员、重叠成员或群成员交集时，"
    "优先调用 count_shared_room_members 或 list_shared_room_members。"
    "对于这类问题，不要先调用 get_room_members 或 get_room_members_summary 这类全量列表工具，"
    "除非上述聚合工具不可用或执行失败。"
    "如果用户只问有没有、多少或统计结果，先用 count_shared_room_members；"
    "如果用户要名单、明细或继续翻页，优先用 list_shared_room_members。"
    "当用户询问某个群里有多少成员是其好友、某个群里哪些成员是其好友、统计群好友数量、分页列出群好友时，"
    "优先调用 count_room_friend_members 或 list_room_friend_members。"
    "对于这类问题，不要先调用 get_user_list、get_room_members、get_user_list_summary、get_room_members_summary，"
    "除非上述聚合工具不可用或执行失败。"
    "如果用户只问数量，先用 count_room_friend_members；"
    "如果用户要名单、明细或继续翻页，优先用 list_room_friend_members。"
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
    "active_prompt_plugin_id": "default-smart-plugin",
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
    "temperature": 0.2,
    "max_tool_rounds": 20,
    "prompt_plugins": [],
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


LOCAL_TOOL_REGISTRY = {
    "current_datetime": _build_tool_schema(
        "current_datetime",
        "返回当前本地日期时间、星期、时区和 Unix 时间戳。适合在涉及今天、昨天、明天、最近几小时、截至目前等时间敏感任务时先获取精确当前时间。",
    ),
    "count_shared_room_members": _build_tool_schema(
        "count_shared_room_members",
        "精确统计两个群聊之间有多少重复成员。该工具会在服务端完成群成员交集计算，避免把两份完整群成员列表交给模型。",
        {
            "first_roomid": {"type": "string", "description": "第一个群聊 ID，例如 123456@chatroom。"},
            "second_roomid": {"type": "string", "description": "第二个群聊 ID，例如 654321@chatroom。"},
            "wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"},
            "sample_limit": {"type": "integer", "minimum": 1, "maximum": 20, "description": "返回前几条重复成员样例，默认 10。"},
        },
        ["first_roomid", "second_roomid"],
    ),
    "list_shared_room_members": _build_tool_schema(
        "list_shared_room_members",
        "分页列出两个群聊之间重复出现的成员。适合人数较多时分批查看，不需要把两份完整群成员列表交给模型。",
        {
            "first_roomid": {"type": "string", "description": "第一个群聊 ID，例如 123456@chatroom。"},
            "second_roomid": {"type": "string", "description": "第二个群聊 ID，例如 654321@chatroom。"},
            "wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"},
            "offset": {"type": "integer", "minimum": 0, "description": "分页起始偏移量，默认 0。"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 40, "description": "单页返回条数，默认 20，最大 40。"},
            "query": {"type": "string", "description": "可选，按群昵称、好友昵称、备注、wxid 过滤。"},
        },
        ["first_roomid", "second_roomid"],
    ),
    "count_room_friend_members": _build_tool_schema(
        "count_room_friend_members",
        "精确统计指定群聊里有多少成员已经是你的好友。该工具会在服务端完成交集计算，避免把整份好友和群成员列表交给模型。",
        {
            "roomid": {"type": "string", "description": "群聊 ID，例如 123456@chatroom。"},
            "wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"},
            "sample_limit": {"type": "integer", "minimum": 1, "maximum": 20, "description": "返回前几条匹配样例，默认 10。"},
        },
        ["roomid"],
    ),
    "list_room_friend_members": _build_tool_schema(
        "list_room_friend_members",
        "分页列出指定群聊中已经是你的好友的成员。适合人数较多时分批查看，不需要把整份列表交给模型。",
        {
            "roomid": {"type": "string", "description": "群聊 ID，例如 123456@chatroom。"},
            "wxpid": {"type": ["integer", "null"], "description": "微信进程 ID，可选。"},
            "offset": {"type": "integer", "minimum": 0, "description": "分页起始偏移量，默认 0。"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 40, "description": "单页返回条数，默认 20，最大 40。"},
            "query": {"type": "string", "description": "可选，按群昵称、好友昵称、备注、wxid 过滤。"},
        },
        ["roomid"],
    ),
}


def _merge_tool_registry(base_registry: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {**LOCAL_TOOL_REGISTRY, **base_registry}


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
        return _merge_tool_registry(TOOL_REGISTRY)
    try:
        return _merge_tool_registry(_parse_mcp_tool_registry(source_path.read_text(encoding="utf-8")) or TOOL_REGISTRY)
    except Exception:
        return _merge_tool_registry(TOOL_REGISTRY)


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


def _build_model_option_items(model_names: list[str]) -> list[dict[str, str]]:
    return [
        {
            "label": model_name,
            "value": model_name,
            "search_text": model_name,
        }
        for model_name in model_names
    ]


async def load_openai_compatible_model_options(
    base_url: str,
    api_key: str,
    current_model: str | None = None,
) -> dict[str, Any]:
    normalized_base_url = _normalize_provider_base_url(base_url, PROVIDER_CATALOG["openai"]["default_base_url"])
    normalized_api_key = str(api_key or "").strip()
    fallback_models: list[str] = []
    normalized_current_model = str(current_model or "").strip()
    if normalized_current_model:
        fallback_models.append(normalized_current_model)
    fallback_models.append(PROVIDER_CATALOG["openai"]["default_model"])

    model_names = _merge_model_names([], fallback_models)
    error_message = ""
    if normalized_api_key:
        try:
            loaded_model_names = await asyncio.to_thread(
                _request_provider_models,
                normalized_base_url,
                normalized_api_key,
                _build_provider_request_headers("openai", normalized_api_key),
                PROVIDER_CATALOG["openai"].get("models_path") or "/models",
            )
            model_names = _merge_model_names(loaded_model_names, fallback_models)
        except Exception as exc:
            error_message = str(exc)

    return {
        "base_url": normalized_base_url,
        "options": _build_model_option_items(model_names),
        "error": error_message,
    }


async def run_openai_compatible_chat_completion(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]] | None,
    system_prompt: str = "",
    temperature: float = 0.2,
) -> dict[str, Any]:
    normalized_api_key = str(api_key or "").strip()
    if not normalized_api_key:
        raise RuntimeError("未配置 API Key")

    normalized_base_url = _normalize_provider_base_url(base_url, PROVIDER_CATALOG["openai"]["default_base_url"])
    normalized_model = str(model or "").strip() or PROVIDER_CATALOG["openai"]["default_model"]
    normalized_messages = _normalize_chat_history(messages)
    if not normalized_messages:
        raise RuntimeError("缺少可发送给模型的消息")

    request_messages: list[dict[str, Any]] = []
    normalized_system_prompt = str(system_prompt or "").strip()
    if normalized_system_prompt:
        request_messages.append({"role": "system", "content": normalized_system_prompt})
    request_messages.extend(normalized_messages)

    request_payload = {
        "model": normalized_model,
        "messages": request_messages,
        "stream": False,
        "temperature": _clamp_float(temperature, 0.2, 0.0, 1.5),
    }

    response_payload = await asyncio.to_thread(
        _request_provider_json,
        _build_provider_url(normalized_base_url, PROVIDER_CATALOG["openai"]["chat_path"]),
        request_payload,
        _build_provider_request_headers("openai", normalized_api_key),
    )
    choices = response_payload.get("choices") if isinstance(response_payload, dict) else None
    if not isinstance(choices, list) or not choices:
        raise RuntimeError(f"AI 接口返回异常：{response_payload}")

    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    assistant_content = _normalize_message_content(message.get("content"))
    assistant_reasoning_content = _normalize_reasoning_content(message.get("reasoning_content"))
    if not assistant_content:
        raise RuntimeError("模型未返回可展示的回复")

    return {
        "content": assistant_content,
        "reasoning_content": assistant_reasoning_content,
        "model": normalized_model,
        "base_url": normalized_base_url,
    }


def get_default_ai_assistant_settings() -> dict[str, Any]:
    defaults = deepcopy(DEFAULT_AI_ASSISTANT_SETTINGS)
    if not defaults.get("prompt_plugins"):
        defaults["prompt_plugins"] = [
            {
                "id": str(defaults.get("active_prompt_plugin_id") or "default-smart-plugin"),
                "name": "通用助手",
                "prompt": str(defaults.get("system_prompt") or DEFAULT_SYSTEM_PROMPT).strip() or DEFAULT_SYSTEM_PROMPT,
                "temperature": _clamp_float(defaults.get("temperature"), 0.2, 0.0, 1.5),
                "max_tool_rounds": _clamp_int(defaults.get("max_tool_rounds"), 20, 1, 500),
            }
        ]
    return defaults


def _build_default_prompt_plugin(index: int = 1) -> dict[str, Any]:
    defaults = DEFAULT_AI_ASSISTANT_SETTINGS
    return {
        "id": "default-smart-plugin" if index == 1 else f"prompt-plugin-{index}",
        "name": "通用助手" if index == 1 else f"提示词插件 {index}",
        "prompt": str(defaults.get("system_prompt") or DEFAULT_SYSTEM_PROMPT).strip() or DEFAULT_SYSTEM_PROMPT,
        "temperature": _clamp_float(defaults.get("temperature"), 0.2, 0.0, 1.5),
        "max_tool_rounds": _clamp_int(defaults.get("max_tool_rounds"), 20, 1, 500),
    }


def _normalize_prompt_plugin_entries(raw_settings: dict[str, Any], defaults: dict[str, Any]) -> list[dict[str, Any]]:
    raw_plugins = raw_settings.get("prompt_plugins") if isinstance(raw_settings.get("prompt_plugins"), list) else None
    normalized_plugins: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def append_plugin(item: dict[str, Any], index: int) -> None:
        default_plugin = _build_default_prompt_plugin(index)
        normalized_id = str(item.get("id") or default_plugin["id"]).strip() or default_plugin["id"]
        if normalized_id in seen_ids:
            normalized_id = f"{normalized_id}-{index}"
        seen_ids.add(normalized_id)
        normalized_plugins.append(
            {
                "id": normalized_id,
                "name": str(item.get("name") or item.get("plugin_name") or default_plugin["name"]).strip() or default_plugin["name"],
                "prompt": str(item.get("prompt") or item.get("system_prompt") or default_plugin["prompt"]).strip() or default_plugin["prompt"],
                "temperature": _clamp_float(item.get("temperature"), default_plugin["temperature"], 0.0, 1.5),
                "max_tool_rounds": _clamp_int(item.get("max_tool_rounds"), default_plugin["max_tool_rounds"], 1, 500),
            }
        )

    if raw_plugins is not None:
        for index, raw_plugin in enumerate(raw_plugins, start=1):
            if not isinstance(raw_plugin, dict):
                continue
            append_plugin(raw_plugin, index)

    if not normalized_plugins:
        append_plugin(
            {
                "id": raw_settings.get("active_prompt_plugin_id") or defaults.get("active_prompt_plugin_id"),
                "name": raw_settings.get("prompt_plugin_name") or "通用助手",
                "prompt": raw_settings.get("system_prompt") or defaults.get("system_prompt"),
                "temperature": raw_settings.get("temperature"),
                "max_tool_rounds": raw_settings.get("max_tool_rounds"),
            },
            1,
        )

    return normalized_plugins


def resolve_ai_assistant_prompt_plugin(settings: dict[str, Any], prompt_plugin_id: str | None = None) -> dict[str, Any]:
    prompt_plugins = settings.get("prompt_plugins") if isinstance(settings.get("prompt_plugins"), list) else []
    if not prompt_plugins:
        raise RuntimeError("当前还没有可用的提示词插件配置")

    normalized_plugin_id = str(prompt_plugin_id or settings.get("active_prompt_plugin_id") or "").strip()
    selected_plugin = next((item for item in prompt_plugins if str(item.get("id") or "") == normalized_plugin_id), None)
    if selected_plugin is None:
        selected_plugin = prompt_plugins[0]
    return selected_plugin


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
    prompt_plugins = _normalize_prompt_plugin_entries(raw_settings, defaults)
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

    active_prompt_plugin_id = str(raw_settings.get("active_prompt_plugin_id") or defaults.get("active_prompt_plugin_id") or "").strip()
    if active_prompt_plugin_id not in {str(item.get("id") or "") for item in prompt_plugins}:
        active_prompt_plugin_id = str(prompt_plugins[0].get("id") or defaults.get("active_prompt_plugin_id") or "default-smart-plugin")
    selected_prompt_plugin = resolve_ai_assistant_prompt_plugin(
        {
            "prompt_plugins": prompt_plugins,
            "active_prompt_plugin_id": active_prompt_plugin_id,
        },
        active_prompt_plugin_id,
    )

    return {
        "active_provider": active_provider,
        "active_prompt_plugin_id": active_prompt_plugin_id,
        "system_prompt": str(selected_prompt_plugin.get("prompt") or defaults["system_prompt"]).strip() or defaults["system_prompt"],
        "temperature": _clamp_float(selected_prompt_plugin.get("temperature"), defaults["temperature"], 0.0, 1.5),
        "max_tool_rounds": _clamp_int(selected_prompt_plugin.get("max_tool_rounds"), defaults["max_tool_rounds"], 1, 500),
        "prompt_plugins": prompt_plugins,
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
            "提示词插件配置和模型 API Key 配置相互独立；多个提示词插件会共享同一批模型配置。",
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


def _normalize_contact_wxid(item: dict[str, Any]) -> str:
    return str(item.get("wxid") or item.get("username") or "").strip()


def _normalize_room_member_wxid(item: dict[str, Any]) -> str:
    return str(item.get("username") or item.get("wxid") or "").strip()


def _build_room_friend_match_items(room_members: list[dict[str, Any]], friends: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
    friend_lookup = {
        wxid: item
        for item in friends if isinstance(item, dict)
        for wxid in [_normalize_contact_wxid(item)]
        if wxid
    }

    valid_room_member_count = 0
    matched_items: list[dict[str, Any]] = []
    for member in room_members if isinstance(room_members, list) else []:
        if not isinstance(member, dict):
            continue
        member_wxid = _normalize_room_member_wxid(member)
        if not member_wxid:
            continue
        valid_room_member_count += 1
        friend = friend_lookup.get(member_wxid)
        if friend is None:
            continue

        room_nick_name = str(member.get("room_nick_name") or "").strip()
        nick_name = str(member.get("nick_name") or member.get("nickname") or "").strip()
        alias = str(member.get("alias") or "").strip()
        remarks = str(member.get("remarks") or "").strip()
        friend_nickname = str(friend.get("nickname") or "").strip()
        friend_remarks = str(friend.get("remarks") or "").strip()
        matched_items.append(
            {
                "wxid": member_wxid,
                "display_name": room_nick_name or nick_name or friend_remarks or friend_nickname or member_wxid,
                "room_nick_name": room_nick_name,
                "nick_name": nick_name,
                "alias": alias,
                "remarks": remarks,
                "friend_nickname": friend_nickname,
                "friend_remarks": friend_remarks,
                "wxh": str(friend.get("wxh") or friend.get("alias") or "").strip(),
            }
        )

    return matched_items, valid_room_member_count, len(friend_lookup)


def _build_room_member_lookup(room_members: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], int]:
    room_member_lookup: dict[str, dict[str, Any]] = {}
    valid_room_member_count = 0
    for member in room_members if isinstance(room_members, list) else []:
        if not isinstance(member, dict):
            continue
        member_wxid = _normalize_room_member_wxid(member)
        if not member_wxid:
            continue
        valid_room_member_count += 1
        room_member_lookup.setdefault(member_wxid, member)
    return room_member_lookup, valid_room_member_count


def _build_shared_room_member_items(
    first_room_members: list[dict[str, Any]],
    second_room_members: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int]:
    first_lookup, total_first_room_members = _build_room_member_lookup(first_room_members)
    second_lookup, total_second_room_members = _build_room_member_lookup(second_room_members)

    shared_items: list[dict[str, Any]] = []
    for member_wxid, first_member in first_lookup.items():
        second_member = second_lookup.get(member_wxid)
        if second_member is None:
            continue

        first_room_nick_name = str(first_member.get("room_nick_name") or "").strip()
        second_room_nick_name = str(second_member.get("room_nick_name") or "").strip()
        first_nick_name = str(first_member.get("nick_name") or first_member.get("nickname") or "").strip()
        second_nick_name = str(second_member.get("nick_name") or second_member.get("nickname") or "").strip()
        first_alias = str(first_member.get("alias") or "").strip()
        second_alias = str(second_member.get("alias") or "").strip()
        first_remarks = str(first_member.get("remarks") or "").strip()
        second_remarks = str(second_member.get("remarks") or "").strip()

        shared_items.append(
            {
                "wxid": member_wxid,
                "display_name": first_room_nick_name or second_room_nick_name or first_nick_name or second_nick_name or member_wxid,
                "first_room_nick_name": first_room_nick_name,
                "second_room_nick_name": second_room_nick_name,
                "first_nick_name": first_nick_name,
                "second_nick_name": second_nick_name,
                "first_alias": first_alias,
                "second_alias": second_alias,
                "first_remarks": first_remarks,
                "second_remarks": second_remarks,
            }
        )

    return shared_items, total_first_room_members, total_second_room_members


def _filter_room_friend_match_items(items: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    normalized_query = str(query or "").strip().lower()
    if not normalized_query:
        return list(items)
    filtered_items: list[dict[str, Any]] = []
    for item in items:
        searchable_text = "\n".join(
            str(item.get(field) or "")
            for field in [
                "wxid",
                "display_name",
                "room_nick_name",
                "nick_name",
                "alias",
                "remarks",
                "friend_nickname",
                "friend_remarks",
                "wxh",
            ]
        ).lower()
        if normalized_query in searchable_text:
            filtered_items.append(item)
    return filtered_items


def _filter_shared_room_member_items(items: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    normalized_query = str(query or "").strip().lower()
    if not normalized_query:
        return list(items)
    filtered_items: list[dict[str, Any]] = []
    for item in items:
        searchable_text = "\n".join(
            str(item.get(field) or "")
            for field in [
                "wxid",
                "display_name",
                "first_room_nick_name",
                "second_room_nick_name",
                "first_nick_name",
                "second_nick_name",
                "first_alias",
                "second_alias",
                "first_remarks",
                "second_remarks",
            ]
        ).lower()
        if normalized_query in searchable_text:
            filtered_items.append(item)
    return filtered_items


async def _collect_room_friend_matches(
    tool_executor: "_McpHttpToolExecutor",
    roomid: str,
    wxpid: int | None,
) -> tuple[list[dict[str, Any]], int, int]:
    friend_arguments: dict[str, Any] = {}
    room_arguments: dict[str, Any] = {"roomid": roomid}
    if wxpid is not None:
        friend_arguments["wxpid"] = wxpid
        room_arguments["wxpid"] = wxpid

    friends, room_members = await asyncio.gather(
        tool_executor.call_tool("get_user_list", friend_arguments),
        tool_executor.call_tool("get_room_members", room_arguments),
    )
    if not isinstance(friends, list):
        raise RuntimeError("get_user_list 返回格式异常")
    if not isinstance(room_members, list):
        raise RuntimeError("get_room_members 返回格式异常")
    return _build_room_friend_match_items(room_members, friends)


async def _collect_shared_room_members(
    tool_executor: "_McpHttpToolExecutor",
    first_roomid: str,
    second_roomid: str,
    wxpid: int | None,
) -> tuple[list[dict[str, Any]], int, int]:
    first_room_arguments: dict[str, Any] = {"roomid": first_roomid}
    second_room_arguments: dict[str, Any] = {"roomid": second_roomid}
    if wxpid is not None:
        first_room_arguments["wxpid"] = wxpid
        second_room_arguments["wxpid"] = wxpid

    first_room_members, second_room_members = await asyncio.gather(
        tool_executor.call_tool("get_room_members", first_room_arguments),
        tool_executor.call_tool("get_room_members", second_room_arguments),
    )
    if not isinstance(first_room_members, list):
        raise RuntimeError("第一个群的 get_room_members 返回格式异常")
    if not isinstance(second_room_members, list):
        raise RuntimeError("第二个群的 get_room_members 返回格式异常")
    return _build_shared_room_member_items(first_room_members, second_room_members)


async def _execute_local_tool_call(
    tool_executor: "_McpHttpToolExecutor",
    tool_name: str,
    arguments: dict[str, Any],
) -> Any:
    roomid = _coerce_text(arguments.get("roomid"))
    first_roomid = _coerce_text(arguments.get("first_roomid") or arguments.get("roomid_a") or arguments.get("roomid1"))
    second_roomid = _coerce_text(arguments.get("second_roomid") or arguments.get("roomid_b") or arguments.get("roomid2"))
    wxpid = _coerce_optional_int(arguments.get("wxpid"))
    if tool_name == "current_datetime":
        return _get_current_datetime_payload()
    if tool_name in {"count_room_friend_members", "list_room_friend_members"} and not roomid:
        raise RuntimeError("roomid 不能为空")
    if tool_name in {"count_shared_room_members", "list_shared_room_members"} and (not first_roomid or not second_roomid):
        raise RuntimeError("first_roomid 和 second_roomid 不能为空")

    if tool_name == "count_shared_room_members":
        sample_limit = _clamp_int(arguments.get("sample_limit"), 10, 1, 20)
        shared_items, total_first_room_members, total_second_room_members = await _collect_shared_room_members(
            tool_executor,
            first_roomid,
            second_roomid,
            wxpid,
        )
        return {
            "first_roomid": first_roomid,
            "second_roomid": second_roomid,
            "wxpid": wxpid,
            "total_first_room_members": total_first_room_members,
            "total_second_room_members": total_second_room_members,
            "shared_member_count": len(shared_items),
            "first_room_unique_member_count": max(0, total_first_room_members - len(shared_items)),
            "second_room_unique_member_count": max(0, total_second_room_members - len(shared_items)),
            "sample_limit": sample_limit,
            "sample_items": shared_items[:sample_limit],
            "is_complete": True,
        }

    if tool_name == "list_shared_room_members":
        offset = _clamp_int(arguments.get("offset"), 0, 0, 1000000)
        limit = _clamp_int(arguments.get("limit"), 20, 1, 40)
        query = _coerce_text(arguments.get("query"))
        shared_items, total_first_room_members, total_second_room_members = await _collect_shared_room_members(
            tool_executor,
            first_roomid,
            second_roomid,
            wxpid,
        )
        filtered_items = _filter_shared_room_member_items(shared_items, query)
        page_items = filtered_items[offset:offset + limit]
        next_offset = offset + len(page_items)
        return {
            "first_roomid": first_roomid,
            "second_roomid": second_roomid,
            "wxpid": wxpid,
            "query": query,
            "offset": offset,
            "limit": limit,
            "total_first_room_members": total_first_room_members,
            "total_second_room_members": total_second_room_members,
            "total_count": len(filtered_items),
            "has_more": next_offset < len(filtered_items),
            "next_offset": next_offset if next_offset < len(filtered_items) else None,
            "items": page_items,
            "is_complete": True,
        }

    if tool_name == "count_room_friend_members":
        sample_limit = _clamp_int(arguments.get("sample_limit"), 10, 1, 20)
        matched_items, total_room_members, total_friends = await _collect_room_friend_matches(tool_executor, roomid, wxpid)
        return {
            "roomid": roomid,
            "wxpid": wxpid,
            "total_room_members": total_room_members,
            "total_friends": total_friends,
            "matched_friend_count": len(matched_items),
            "unmatched_room_member_count": max(0, total_room_members - len(matched_items)),
            "sample_limit": sample_limit,
            "sample_items": matched_items[:sample_limit],
            "is_complete": True,
        }

    if tool_name == "list_room_friend_members":
        offset = _clamp_int(arguments.get("offset"), 0, 0, 1000000)
        limit = _clamp_int(arguments.get("limit"), 20, 1, 40)
        query = _coerce_text(arguments.get("query"))
        matched_items, total_room_members, total_friends = await _collect_room_friend_matches(tool_executor, roomid, wxpid)
        filtered_items = _filter_room_friend_match_items(matched_items, query)
        page_items = filtered_items[offset:offset + limit]
        next_offset = offset + len(page_items)
        return {
            "roomid": roomid,
            "wxpid": wxpid,
            "query": query,
            "offset": offset,
            "limit": limit,
            "total_room_members": total_room_members,
            "total_friends": total_friends,
            "total_count": len(filtered_items),
            "has_more": next_offset < len(filtered_items),
            "next_offset": next_offset if next_offset < len(filtered_items) else None,
            "items": page_items,
            "is_complete": True,
        }

    raise RuntimeError(f"暂不支持本地工具 {tool_name}")


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


def _get_current_datetime_payload() -> dict[str, Any]:
    now = datetime.now().astimezone()
    weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    weekday_name = weekday_names[now.weekday()]
    timezone_name = now.tzname() or "本地时区"
    offset = now.strftime("%z")
    if len(offset) == 5:
        offset = f"{offset[:3]}:{offset[3:]}"
    return {
        "current_datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "iso_datetime": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": weekday_name,
        "timezone_name": timezone_name,
        "timezone_offset": offset,
        "unix_timestamp": int(now.timestamp()),
        "is_complete": True,
    }


def _build_current_time_prompt() -> str:
    payload = _get_current_datetime_payload()
    return (
        "时间上下文："
        f"当前本地时间为 {payload['current_datetime']}，{payload['weekday']}，"
        f"时区 {payload['timezone_name']} ({payload['timezone_offset']})。"
        f"ISO 8601 时间：{payload['iso_datetime']}。"
        "当用户提到今天、昨天、明天、最近几小时、截至目前等相对时间时，"
        "以上述当前时间为准进行理解、推理和回答。"
    )


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


def _build_contextual_tool_routing_prompt(latest_user_message: str) -> str:
    normalized_text = str(latest_user_message or "").strip().lower()
    if not normalized_text:
        return ""

    time_keywords = [
        "现在",
        "当前时间",
        "几点",
        "几号",
        "周几",
        "星期几",
        "今天",
        "昨天",
        "明天",
        "最近",
        "截至目前",
        "到目前",
        "到现在",
        "此刻",
        "本周",
        "本月",
        "小时",
        "分钟",
        "秒",
        "deadline",
        "ddl",
    ]
    if any(keyword in normalized_text for keyword in time_keywords):
        return (
            "当前问题涉及当前时间、日期或相对时间范围判断。"
            "优先先调用 current_datetime 获取精确当前时间，再决定是否调用其他工具或给出结论。"
        )

    contains_room = any(token in normalized_text for token in ["群", "群聊", "chatroom", "@chatroom", "roomid"])
    overlap_keywords = ["重复成员", "共同成员", "相同成员", "重叠成员", "交集", "重复的群成员", "重复群成员", "重合成员"]
    dual_room_keywords = ["两个群", "两群", "两个群聊", "2个群", "两个群里", "两个群聊里"]
    overlap_count_keywords = ["有没有", "是否有", "有无", "多少", "几个", "几位", "统计", "数量", "占比"]
    if contains_room and (
        any(keyword in normalized_text for keyword in overlap_keywords)
        or any(keyword in normalized_text for keyword in dual_room_keywords)
    ):
        list_keywords = ["哪些", "名单", "列出", "明细", "都有谁", "分别是", "翻页", "分页"]
        if any(keyword in normalized_text for keyword in list_keywords):
            return (
                "当前问题是在查询两个群聊之间哪些成员重复出现或查看交集名单。"
                "优先先调用 list_shared_room_members，不要先调用 get_room_members 这类全量列表工具。"
                "如果还需要总数，可再调用 count_shared_room_members。"
            )

        if any(keyword in normalized_text for keyword in overlap_count_keywords):
            return (
                "当前问题是在统计两个群聊之间是否有重复成员或有多少重复成员。"
                "优先先调用 count_shared_room_members，不要先调用 get_room_members 这类全量列表工具。"
                "如果用户后续要求查看名单，再调用 list_shared_room_members。"
            )

        return (
            "当前问题与两个群聊的成员交集分析有关。"
            "优先使用 count_shared_room_members 或 list_shared_room_members，避免先调用全量列表工具。"
        )

    contains_friend = "好友" in normalized_text
    if not (contains_room and contains_friend):
        return ""

    list_keywords = ["哪些", "名单", "列出", "明细", "都有谁", "分别是", "翻页", "分页"]
    count_keywords = ["多少", "几个", "几位", "统计", "数量", "占比"]

    if any(keyword in normalized_text for keyword in list_keywords):
        return (
            "当前问题是在查询某个群里哪些成员是好友或查看名单。"
            "优先先调用 list_room_friend_members，不要先调用 get_user_list 或 get_room_members 这类全量列表工具。"
            "如果还需要总数，可再调用 count_room_friend_members。"
        )

    if any(keyword in normalized_text for keyword in count_keywords):
        return (
            "当前问题是在统计某个群里有多少成员是好友。"
            "优先先调用 count_room_friend_members，不要先调用 get_user_list 或 get_room_members 这类全量列表工具。"
            "如果用户后续要求查看名单，再调用 list_room_friend_members。"
        )

    return (
        "当前问题与群成员好友交集分析有关。"
        "优先使用 count_room_friend_members 或 list_room_friend_members，避免先调用全量列表工具。"
    )


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


MCP_PROTOCOL_VERSION = "2025-03-26"
MCP_CLIENT_INFO = {
    "name": "wxrobot_webui_ai_assistant",
    "version": "0.0.0.1",
}


class _McpSessionExpiredError(RuntimeError):
    pass


def _build_mcp_endpoint(base_url: str) -> str:
    normalized_base = str(base_url or "").rstrip("/")
    if normalized_base.endswith("/mcp"):
        return f"{normalized_base}/"
    return f"{normalized_base}/mcp/"


def _parse_mcp_sse_messages(response_text: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    data_lines: list[str] = []

    def flush_event() -> None:
        nonlocal data_lines
        if not data_lines:
            return
        data = "\n".join(data_lines)
        data_lines = []
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return
        if isinstance(payload, list):
            messages.extend(item for item in payload if isinstance(item, dict))
        elif isinstance(payload, dict):
            messages.append(payload)

    for raw_line in response_text.splitlines():
        line = raw_line.rstrip("\r")
        if not line:
            flush_event()
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if not separator:
            continue
        if value.startswith(" "):
            value = value[1:]
        if field == "data":
            data_lines.append(value)
    flush_event()
    return messages


def _parse_mcp_http_messages(response_text: str, content_type: str) -> list[dict[str, Any]]:
    normalized_text = str(response_text or "").strip()
    if not normalized_text:
        return []
    if "text/event-stream" in str(content_type or "").lower():
        return _parse_mcp_sse_messages(normalized_text)
    try:
        payload = json.loads(normalized_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"MCP 接口返回了非 JSON 响应: {normalized_text}") from exc
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    raise RuntimeError(f"MCP 接口返回格式异常: {payload}")


def _extract_mcp_jsonrpc_result(messages: list[dict[str, Any]], request_id: int, request_name: str) -> Any:
    for message in messages:
        if not isinstance(message, dict):
            continue
        if str(message.get("id")) != str(request_id):
            continue
        error_payload = message.get("error") if isinstance(message.get("error"), dict) else None
        if error_payload is not None:
            detail = str(error_payload.get("message") or "MCP 请求失败").strip() or "MCP 请求失败"
            error_data = error_payload.get("data")
            if error_data not in (None, "", {}, []):
                detail = f"{detail}: {_safe_trim_string(json.dumps(error_data, ensure_ascii=False, default=str))}"
            raise RuntimeError(f"{request_name} 失败: {detail}")
        return message.get("result")
    raise RuntimeError(f"{request_name} 未返回结果")


def _maybe_parse_json_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    if not normalized:
        return ""
    try:
        return json.loads(normalized)
    except json.JSONDecodeError:
        return value


def _decode_mcp_content_item(item: Any) -> Any:
    if not isinstance(item, dict):
        return item
    item_type = str(item.get("type") or "").strip().lower()
    if item_type == "text":
        return _maybe_parse_json_text(item.get("text"))
    if item_type == "resource":
        resource = item.get("resource") if isinstance(item.get("resource"), dict) else {}
        if "text" not in resource:
            return resource or item
        parsed_text = _maybe_parse_json_text(resource.get("text"))
        if len(resource) == 1:
            return parsed_text
        return {**resource, "text": parsed_text}
    return item


def _decode_mcp_tool_result(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    if set(result.keys()) == {"result"}:
        return result.get("result")
    if "structuredContent" in result:
        return _decode_mcp_tool_result(result.get("structuredContent"))
    content = result.get("content")
    if not isinstance(content, list):
        return result
    items = [_decode_mcp_content_item(item) for item in content]
    if not items:
        return {}
    if len(items) == 1:
        single_item = items[0]
        if isinstance(single_item, dict) and set(single_item.keys()) == {"result"}:
            return single_item.get("result")
        return single_item
    if all(isinstance(item, str) for item in items):
        return "\n\n".join(item for item in items if item)
    return items


def _format_mcp_tool_error(result: Any) -> str:
    decoded = _decode_mcp_tool_result(result)
    if isinstance(decoded, str):
        return decoded or "MCP 工具执行失败"
    if decoded in (None, {}, []):
        return "MCP 工具执行失败"
    return _safe_trim_string(json.dumps(decoded, ensure_ascii=False, default=str))


class _McpHttpToolExecutor:
    def __init__(self, api_client: WxRobotApiClient):
        self._endpoint = _build_mcp_endpoint(api_client.base_url)
        self._base_timeout = max(float(api_client.timeout or 0) if api_client.timeout else 0.0, 1.0)
        self._session_id: str | None = None
        self._request_id = 0
        self._initialized = False

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _resolve_tool_timeout(self, arguments: dict[str, Any]) -> float:
        request_timeout = self._base_timeout
        if not _coerce_bool(arguments.get("wait"), False):
            return request_timeout
        try:
            operation_timeout = float(arguments.get("timeout"))
        except (TypeError, ValueError):
            return request_timeout
        if operation_timeout <= 0:
            return request_timeout
        return max(request_timeout, operation_timeout + 2.0)

    def _request_sync(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        effective_timeout = timeout if isinstance(timeout, (int, float)) and timeout and timeout > 0 else self._base_timeout
        headers = {
            "Accept": "application/json, text/event-stream",
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        request_body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(self._endpoint, data=request_body, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=effective_timeout) as response:
                response_text = response.read().decode("utf-8")
                response_content_type = response.headers.get("Content-Type", "")
                response_session_id = response.headers.get("Mcp-Session-Id") or response.headers.get("mcp-session-id")
        except TimeoutError as exc:
            raise RuntimeError(f"调用 MCP {self._endpoint} 超时({effective_timeout:.1f}s)") from exc
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            if exc.code == 404 and session_id:
                raise _McpSessionExpiredError() from exc
            raise RuntimeError(f"调用 MCP {self._endpoint} 失败，HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"调用 MCP {self._endpoint} 失败: {exc.reason}") from exc

        return {
            "messages": _parse_mcp_http_messages(response_text, response_content_type),
            "session_id": response_session_id,
        }

    def _reset_session(self) -> None:
        self._session_id = None
        self._initialized = False

    async def _initialize(self) -> None:
        if self._initialized:
            return
        request_id = self._next_request_id()
        response = await asyncio.to_thread(
            self._request_sync,
            "POST",
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": MCP_CLIENT_INFO,
                },
            },
            session_id=None,
            timeout=self._base_timeout,
        )
        if response.get("session_id"):
            self._session_id = str(response["session_id"])
        initialize_result = _extract_mcp_jsonrpc_result(response["messages"], request_id, "MCP initialize")
        if not isinstance(initialize_result, dict):
            raise RuntimeError("MCP initialize 返回格式异常")
        await asyncio.to_thread(
            self._request_sync,
            "POST",
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
            session_id=self._session_id,
            timeout=self._base_timeout,
        )
        self._initialized = True

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        await self._initialize()
        request_timeout = self._resolve_tool_timeout(arguments)

        async def do_call() -> Any:
            request_id = self._next_request_id()
            response = await asyncio.to_thread(
                self._request_sync,
                "POST",
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": arguments,
                    },
                },
                session_id=self._session_id,
                timeout=request_timeout,
            )
            if response.get("session_id"):
                self._session_id = str(response["session_id"])
            result = _extract_mcp_jsonrpc_result(response["messages"], request_id, f"MCP 工具 {tool_name}")
            if isinstance(result, dict) and result.get("isError"):
                raise RuntimeError(_format_mcp_tool_error(result))
            return _decode_mcp_tool_result(result)

        try:
            return await do_call()
        except _McpSessionExpiredError:
            self._reset_session()
            await self._initialize()
            return await do_call()

    async def aclose(self) -> None:
        if not self._session_id:
            return
        session_id = self._session_id
        self._reset_session()
        try:
            await asyncio.to_thread(
                self._request_sync,
                "DELETE",
                None,
                session_id=session_id,
                timeout=self._base_timeout,
            )
        except Exception:
            return


async def _execute_tool_call(tool_executor: _McpHttpToolExecutor, tool_name: str, arguments: dict[str, Any]) -> Any:
    if tool_name in LOCAL_TOOL_REGISTRY:
        return await _execute_local_tool_call(tool_executor, tool_name, arguments)
    return await tool_executor.call_tool(tool_name, arguments)


async def run_ai_assistant(
    settings: dict[str, Any],
    api_client: WxRobotApiClient,
    messages: list[dict[str, Any]] | None,
    provider_key: str | None = None,
    model_override: str | None = None,
    provider_config_id: str | None = None,
    prompt_plugin_id: str | None = None,
    progress_callback: Any = None,
) -> dict[str, Any]:
    normalized_settings = normalize_ai_assistant_settings(settings)
    selected_prompt_plugin = resolve_ai_assistant_prompt_plugin(normalized_settings, prompt_plugin_id)
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

    contextual_tool_routing_prompt = _build_contextual_tool_routing_prompt(history[-1].get("content") or "")
    current_time_prompt = _build_current_time_prompt()
    request_messages: list[dict[str, Any]] = [
        {"role": "system", "content": str(selected_prompt_plugin.get("prompt") or normalized_settings["system_prompt"])},
        {"role": "system", "content": current_time_prompt},
        {"role": "system", "content": INTERNAL_TOOL_ROUTING_PROMPT},
        *(
            [{"role": "system", "content": contextual_tool_routing_prompt}]
            if contextual_tool_routing_prompt else []
        ),
        *history,
    ]
    tool_schemas = get_tool_schemas()
    trace_entries: list[dict[str, Any]] = []
    max_tool_rounds = _clamp_int(selected_prompt_plugin.get("max_tool_rounds"), normalized_settings["max_tool_rounds"], 1, 500)
    selected_model = str(model_override or provider_meta["default_model"] or "").strip() or provider_meta["default_model"]
    tool_executor = _McpHttpToolExecutor(api_client)

    try:
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
                "stream": False,
                "temperature": _clamp_float(selected_prompt_plugin.get("temperature"), normalized_settings["temperature"], 0.0, 1.5),
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
                    "prompt_plugin_id": str(selected_prompt_plugin.get("id") or ""),
                    "prompt_plugin_name": str(selected_prompt_plugin.get("name") or ""),
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
                    raw_result = await _execute_tool_call(tool_executor, tool_name, arguments)
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
    finally:
        await tool_executor.aclose()
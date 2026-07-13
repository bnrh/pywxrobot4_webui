"""Tool schema registry and MCP AST discovery."""

from __future__ import annotations

import ast
import inspect
from functools import lru_cache
from pathlib import Path
from typing import Any

from .constants import MCP_SERVER_SOURCE_CANDIDATES, _JSON_OBJECT_SCHEMA

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

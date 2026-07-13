"""AI assistant chat loop and message normalization."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from urllib import error, request

from client import WxRobotApiClient

from copy import deepcopy

from .constants import (
    DEFAULT_SYSTEM_PROMPT,
    INTERNAL_TOOL_ROUTING_PROMPT,
    PROVIDER_CATALOG,
)
from .mcp_client import _McpHttpToolExecutor
from .openai_messages import (
    _normalize_message_content,
    _normalize_message_image_items,
    _normalize_reasoning_content,
)
from .providers import (
    _build_provider_request_headers,
    _build_provider_url,
    _clamp_float,
    _clamp_int,
    _get_provider_runtime_base_url,
    _merge_provider_extra_body,
    _request_provider_json,
    _resolve_provider_runtime_config,
)
from .settings import (
    get_tool_schemas,
    is_write_tool,
    normalize_ai_assistant_settings,
    resolve_ai_assistant_prompt_plugin,
)
from .tool_registry import LOCAL_TOOL_REGISTRY
from .tools_local import (
    _build_current_time_prompt,
    _compact_tool_result,
    _execute_local_tool_call,
    _get_current_datetime_payload,
)

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

async def _execute_tool_call(
    tool_executor: _McpHttpToolExecutor,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    allow_write_tools: bool = False,
) -> Any:
    if not allow_write_tools and is_write_tool(tool_name):
        raise RuntimeError(
            f"写操作工具 {tool_name} 已被禁用。请在智能插件设置中启用“允许写操作工具”后再试。"
        )
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
    tool_schemas = get_tool_schemas(allow_write_tools=bool(normalized_settings.get("allow_write_tools")))
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
                    raw_result = await _execute_tool_call(
                        tool_executor,
                        tool_name,
                        arguments,
                        allow_write_tools=bool(normalized_settings.get("allow_write_tools")),
                    )
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
"""MCP HTTP tool executor."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib import error, request

from client import WxRobotApiClient

from .tools_local import _coerce_bool

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

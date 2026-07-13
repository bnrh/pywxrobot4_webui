"""Shared async HTTP helpers backed by httpx."""

from __future__ import annotations

import json
from typing import Any, Mapping

import httpx

_shared_client: httpx.AsyncClient | None = None
DEFAULT_TIMEOUT_SECONDS = 30.0


def encode_json_body(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _ensure_shared_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=httpx.Timeout(DEFAULT_TIMEOUT_SECONDS),
            follow_redirects=True,
        )
    return _shared_client


async def aclose_shared_http_client() -> None:
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        await _shared_client.aclose()
    _shared_client = None


async def request(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    content: bytes | None = None,
    data: Any = None,
    params: Mapping[str, Any] | None = None,
    files: Any = None,
    timeout: float | None = None,
    follow_redirects: bool | None = None,
    client: httpx.AsyncClient | None = None,
) -> httpx.Response:
    http = client or _ensure_shared_client()
    kwargs: dict[str, Any] = {
        "method": str(method or "GET").upper(),
        "url": url,
        "headers": dict(headers or {}),
        "params": params,
        "content": content,
        "data": data,
        "files": files,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    if follow_redirects is not None:
        kwargs["follow_redirects"] = follow_redirects
    try:
        return await http.request(**kwargs)
    except httpx.TimeoutException as exc:
        raise TimeoutError(f"HTTP request timed out: {url}") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(str(exc)) from exc


async def post_json(
    url: str,
    payload: Any,
    headers: Mapping[str, str] | None = None,
    timeout: float = 10.0,
    *,
    raise_for_status: bool = True,
    client: httpx.AsyncClient | None = None,
) -> tuple[int, str]:
    request_headers = {"Content-Type": "application/json", **dict(headers or {})}
    try:
        response = await request(
            "POST",
            url,
            headers=request_headers,
            content=encode_json_body(payload),
            timeout=timeout,
            client=client,
        )
    except TimeoutError as exc:
        raise RuntimeError(str(exc)) from exc
    if raise_for_status and response.status_code >= 400:
        raise RuntimeError(response.text or f"HTTP {response.status_code}")
    return int(response.status_code), response.text


async def get_text(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
    timeout: float = 10.0,
    raise_for_status: bool = True,
    client: httpx.AsyncClient | None = None,
) -> tuple[int, str]:
    try:
        response = await request(
            "GET",
            url,
            headers=headers,
            params=params,
            timeout=timeout,
            client=client,
        )
    except TimeoutError as exc:
        raise RuntimeError(str(exc)) from exc
    if raise_for_status and response.status_code >= 400:
        raise RuntimeError(response.text or f"HTTP {response.status_code}")
    return int(response.status_code), response.text


async def get_bytes(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 30.0,
    client: httpx.AsyncClient | None = None,
) -> tuple[int, bytes, str]:
    try:
        response = await request(
            "GET",
            url,
            headers=headers,
            timeout=timeout,
            client=client,
        )
    except TimeoutError as exc:
        raise RuntimeError(str(exc)) from exc
    if response.status_code >= 400:
        raise RuntimeError(response.text or f"HTTP {response.status_code}")
    content_type = str(response.headers.get("Content-Type") or "").strip()
    return int(response.status_code), response.content, content_type

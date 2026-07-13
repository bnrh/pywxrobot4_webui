import asyncio
from unittest.mock import AsyncMock, patch

import httpx

from utils.http_client import aclose_shared_http_client, get_text, post_json, request


def test_post_json_and_get_text_use_httpx() -> None:
    responses = [
        httpx.Response(200, text='{"ok": true}', request=httpx.Request("POST", "https://example.test/hook")),
        httpx.Response(200, text="pong", request=httpx.Request("GET", "https://example.test/ping")),
    ]
    mock_request = AsyncMock(side_effect=responses)

    async def run() -> None:
        with patch("utils.http_client._ensure_shared_client") as ensure_client:
            client = AsyncMock()
            client.request = mock_request
            client.is_closed = False
            ensure_client.return_value = client

            status, body = await post_json("https://example.test/hook", {"hello": "世界"})
            assert status == 200
            assert body == '{"ok": true}'

            status, body = await get_text("https://example.test/ping")
            assert status == 200
            assert body == "pong"

            first_call = mock_request.await_args_list[0].kwargs
            assert first_call["method"] == "POST"
            assert b"\xe4\xb8\x96\xe7\x95\x8c" in first_call["content"]  # ensure_ascii=False UTF-8

        await aclose_shared_http_client()

    asyncio.run(run())


def test_request_maps_timeout_to_timeout_error() -> None:
    async def run() -> None:
        with patch("utils.http_client._ensure_shared_client") as ensure_client:
            client = AsyncMock()
            client.request = AsyncMock(side_effect=httpx.TimeoutException("boom"))
            client.is_closed = False
            ensure_client.return_value = client
            try:
                await request("GET", "https://example.test/slow", timeout=0.1)
                assert False, "expected TimeoutError"
            except TimeoutError:
                pass
        await aclose_shared_http_client()

    asyncio.run(run())

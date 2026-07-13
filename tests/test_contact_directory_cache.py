import asyncio
from typing import Any
from unittest.mock import AsyncMock

from runtime.contact_directory_cache import ContactDirectoryCache, ContactProfile


class FakeApiClient:
    def __init__(self) -> None:
        self.get_user_list = AsyncMock(return_value=[])
        self.get_room_list = AsyncMock(return_value=[])
        self.get_biz_list = AsyncMock(return_value=[])
        self.get_room_members = AsyncMock(return_value=[])
        self.get_logged_in_users = AsyncMock(return_value=[])


def test_enrich_messages_batch_prefers_cache_and_batches_room_refresh() -> None:
    api = FakeApiClient()
    cache = ContactDirectoryCache(api)  # type: ignore[arg-type]
    cache._contacts[cache._pid_key(1)] = {
        "wxid_friend": ContactProfile("wxid_friend", "好友A", "https://a/avatar.png", "好友A"),
        "room@chatroom": ContactProfile("room@chatroom", "测试群", "https://room/avatar.png", "测试群"),
    }

    async def fake_get_room_members(roomid: str, wxpid: int | None = None) -> list[dict[str, Any]]:
        assert roomid == "room@chatroom"
        return [
            {
                "username": "wxid_member",
                "nick_name": "成员B",
                "room_nick_name": "群昵称B",
                "small_head_url": "https://b/avatar.png",
            }
        ]

    api.get_room_members = AsyncMock(side_effect=fake_get_room_members)

    messages = [
        {
            "internal_id": 1,
            "wxpid": 1,
            "conversation_wxid": "wxid_friend",
            "sender_wxid": "wxid_friend",
            "is_group_message": False,
            "local_type": 1,
            "content": "wxid_friend:你好",
            "payload": {},
        },
        {
            "internal_id": 2,
            "wxpid": 1,
            "conversation_wxid": "room@chatroom",
            "sender_wxid": "wxid_member",
            "is_group_message": True,
            "local_type": 1,
            "content": "大家好",
            "payload": {},
        },
        {
            "internal_id": 3,
            "wxpid": 1,
            "conversation_wxid": "room@chatroom",
            "sender_wxid": "wxid_member",
            "is_group_message": True,
            "local_type": 1,
            "content": "第二条群消息",
            "payload": {},
        },
    ]

    enriched = asyncio.run(cache.enrich_messages_batch(messages))
    assert len(enriched) == 3
    assert enriched[0]["title_display"] == "好友A"
    assert enriched[0]["text_content"] == "你好"
    assert enriched[1]["conversation_display_name"] == "测试群"
    assert enriched[1]["room_sender_display_name"] == "群昵称B"
    assert enriched[2]["room_sender_display_name"] == "群昵称B"
    # 同一群两条消息只应触发一次群成员 API。
    assert api.get_room_members.await_count == 1
    # 联系人已在缓存中，不应再刷联系人列表。
    assert api.get_user_list.await_count == 0


def test_enrich_message_delegates_to_batch() -> None:
    api = FakeApiClient()
    cache = ContactDirectoryCache(api)  # type: ignore[arg-type]
    cache._contacts[cache._pid_key(None)] = {
        "wxid_x": ContactProfile("wxid_x", "用户X", "", "用户X"),
    }
    message = {
        "wxpid": None,
        "conversation_wxid": "wxid_x",
        "sender_wxid": "wxid_x",
        "is_group_message": False,
        "local_type": 3,
        "content": "",
        "payload": {},
    }
    enriched = asyncio.run(cache.enrich_message(message))
    assert enriched["title_display"] == "用户X"
    assert enriched["sender_display_name"] == "用户X"


def test_enrich_messages_batch_refreshes_contacts_once_per_wxpid() -> None:
    api = FakeApiClient()
    cache = ContactDirectoryCache(api)  # type: ignore[arg-type]

    async def fake_user_list(wxpid: int | None = None) -> list[dict[str, Any]]:
        return [
            {"wxid": "wxid_1", "nickname": "用户1", "small_head_url": ""},
            {"wxid": "wxid_2", "nickname": "用户2", "small_head_url": ""},
        ]

    api.get_user_list = AsyncMock(side_effect=fake_user_list)
    api.get_room_list = AsyncMock(return_value=[])
    api.get_biz_list = AsyncMock(return_value=[])

    messages = [
        {
            "wxpid": 7,
            "conversation_wxid": "wxid_1",
            "sender_wxid": "wxid_1",
            "is_group_message": False,
            "local_type": 1,
            "content": "a",
            "payload": {},
        },
        {
            "wxpid": 7,
            "conversation_wxid": "wxid_2",
            "sender_wxid": "wxid_2",
            "is_group_message": False,
            "local_type": 1,
            "content": "b",
            "payload": {},
        },
    ]
    enriched = asyncio.run(cache.enrich_messages_batch(messages))
    assert enriched[0]["sender_display_name"] == "用户1"
    assert enriched[1]["sender_display_name"] == "用户2"
    assert api.get_user_list.await_count == 1

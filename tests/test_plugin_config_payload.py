from plugin_config_payload import (
    INVITE_TO_ROOM_ALIAS_MODULE,
    INVITE_TO_ROOM_PLUGIN_MODULE,
    normalize_plugin_config_for_payload,
)


def test_normalize_invite_plugin_config_for_alias_module() -> None:
    config = {
        "keyword_rooms": [
            {"roomid": "room@chatroom", "keyword": "测试", "full_match": True},
        ],
    }
    normalized = normalize_plugin_config_for_payload(INVITE_TO_ROOM_ALIAS_MODULE, config)
    assert normalized["keyword_rooms"] == config["keyword_rooms"]


def test_normalize_invite_plugin_config_legacy_keywords() -> None:
    config = {
        "keywords": {
            "room@chatroom": "关键词1,关键词2",
        },
    }
    normalized = normalize_plugin_config_for_payload(INVITE_TO_ROOM_PLUGIN_MODULE, config)
    keywords = {item["keyword"] for item in normalized["keyword_rooms"]}
    assert keywords == {"关键词1", "关键词2"}

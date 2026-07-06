from message import MessageEvent


def test_message_event_parses_nested_payload() -> None:
    event = MessageEvent.model_validate(
        {
            "data": {
                "msgid": "123",
                "sender": "wxid_user",
                "local_type": 1,
                "content": "hello",
            }
        }
    )
    assert event.normalized_msgid == "123"
    assert event.conversation_wxid == "wxid_user"
    assert event.normalized_content == "hello"
    assert event.normalized_msg_type == 1

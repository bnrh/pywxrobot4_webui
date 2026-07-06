from message_types import MESSAGE_TYPE_LABELS, build_message_types_payload


def test_build_message_types_payload_includes_extended_labels() -> None:
    payload = build_message_types_payload()
    assert "labels" in payload
    assert "filter_aliases" in payload
    assert payload["labels"][str(0x600000031)] == MESSAGE_TYPE_LABELS[0x600000031]

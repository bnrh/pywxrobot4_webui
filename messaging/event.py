import json
from enum import IntEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from utils.normalize import is_truthy as _is_truthy


class MessageType(IntEnum):
    IMAGE = 0x3


class MessageEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    content: str = ""
    message_content: str = ""
    local_type: int | str | None = None
    msg_type: int | str | None = None
    msgid: int | str | None = None
    server_id: int | str | None = None
    msgsource: str = ""
    source: str = ""
    recipient: str = ""
    room_sender: str = ""
    s1: str = ""
    s3: str = ""
    s4: str = ""
    sender: str = ""
    create_time: str = ""
    timestamp: int | str | None = None
    voice: str = ""
    wxpid: int | str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_payload(cls, value: Any) -> Any:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return {"content": value}

        if not isinstance(value, dict):
            return value

        payload = dict(value)
        nested_payload = payload.get("data")
        if isinstance(nested_payload, str):
            try:
                nested_payload = json.loads(nested_payload)
            except json.JSONDecodeError:
                nested_payload = None

        if isinstance(nested_payload, dict):
            merged_payload = dict(nested_payload)
            for key, nested_value in payload.items():
                if key == "data" or key in merged_payload:
                    continue
                merged_payload[key] = nested_value
            payload = merged_payload

        if payload.get("content") in (None, "") and payload.get("message_content") not in (None, ""):
            payload["content"] = payload["message_content"]
        if payload.get("msgid") in (None, "") and payload.get("server_id") not in (None, ""):
            payload["msgid"] = payload["server_id"]
        if payload.get("msgsource") in (None, "") and payload.get("source") not in (None, ""):
            payload["msgsource"] = payload["source"]

        return payload

    def _normalized_int_value(self, *names: str) -> int | None:
        value = self.first_non_empty(*names)
        if value in (None, ""):
            return None
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            try:
                return int(stripped, 16) if stripped.lower().startswith("0x") else int(stripped)
            except ValueError:
                return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _extra_value(self, key: str) -> Any:
        extra = self.model_extra or {}
        return extra.get(key)

    def first_non_empty(self, *names: str) -> Any:
        for name in names:
            value = getattr(self, name, None)
            if value not in (None, ""):
                return value
            value = self._extra_value(name)
            if value not in (None, ""):
                return value
        return None

    @property
    def normalized_msgid(self) -> str:
        value = self.first_non_empty("msgid", "server_id", "id")
        return "" if value in (None, "") else str(value)

    @property
    def normalized_wxpid(self) -> int | None:
        return self._normalized_int_value("wxpid", "pid")

    @property
    def normalized_local_type(self) -> int | None:
        return self._normalized_int_value("local_type")

    @property
    def normalized_msg_type(self) -> int | None:
        return self._normalized_int_value("msg_type", "local_type")

    @property
    def normalized_content(self) -> str:
        value = self.first_non_empty("content", "message_content", "s1", "s3", "s4")
        return "" if value in (None, "") else str(value)

    @property
    def conversation_wxid(self) -> str:
        value = self.first_non_empty("sender", "wxid", "talker", "conversation_id", "recipient")
        return "" if value in (None, "") else str(value)

    @property
    def sender_wxid(self) -> str:
        value = self.first_non_empty("room_sender", "from_wxid", "from_user", "sender", "wxid")
        return "" if value in (None, "") else str(value)

    @property
    def current_account_wxid(self) -> str:
        value = self.first_non_empty("self_wxid", "current_wxid", "login_wxid", "account_wxid")
        return "" if value in (None, "") else str(value)

    @property
    def is_self_message(self) -> bool:
        for key in (
            "is_self_msg",
            "is_self",
            "isSelf",
            "is_self_message",
            "isSelfMsg",
            "isSend",
            "is_send",
            "issend",
            "from_self",
            "is_from_self",
        ):
            value = self._extra_value(key)
            if value not in (None, ""):
                return _is_truthy(value)
        return False

    @property
    def is_group_message(self) -> bool:
        return self.conversation_wxid.endswith("@chatroom")

    @property
    def is_image(self) -> bool:
        return self.normalized_msg_type == MessageType.IMAGE or self.normalized_local_type == MessageType.IMAGE

    @property
    def is_empty(self) -> bool:
        return not any(
            [
                self.normalized_msgid,
                self.normalized_msg_type is not None,
                self.normalized_local_type is not None,
                self.conversation_wxid,
                self.sender_wxid,
                self.normalized_content,
                self.raw_payload,
            ]
        )

    @property
    def raw_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude_defaults=True, exclude_none=True)
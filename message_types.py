"""消息类型常量，供后端与前端文档对齐。"""

from __future__ import annotations

MESSAGE_FILTER_ALIASES: dict[str, int] = {
    "text": 1,
    "image": 3,
    "voice": 34,
    "friend_request": 37,
    "card": 42,
    "video": 43,
    "emoji": 47,
    "location": 48,
    "xml": 49,
    "notice": 10000,
    "sysmsg": 10002,
    "file": 25769803825,
}

MESSAGE_TYPE_LABELS: dict[int, str] = {
    0x0: "朋友圈",
    0x1: "文本",
    0x3: "图片",
    0x22: "语音",
    0x25: "好友请求",
    0x2A: "名片",
    0x2B: "视频",
    0x2F: "表情",
    0x30: "位置",
    0x31: "XML消息",
    0x32: "音视频通话",
    0x33: "微信初始化",
    0x34: "通话状态通知",
    0x35: "通话邀请",
    0x3E: "小视频",
    0x42: "微信红包",
    0x2710: "通知消息",
    0x2712: "系统消息",
}

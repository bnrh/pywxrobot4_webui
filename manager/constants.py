"""Plugin manager constants."""

from __future__ import annotations

from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "plugins"
PYTHON_SDK_VERSION = "2.0.0"
PLUGIN_SCOPE_ROOM_MODE = "_scope_room_mode"
PLUGIN_SCOPE_ROOM_IDS = "_scope_room_ids"
PLUGIN_SCOPE_FRIEND_MODE = "_scope_friend_mode"
PLUGIN_SCOPE_FRIEND_LABELS = "_scope_friend_labels"
PLUGIN_SCOPE_BIZ_MODE = "_scope_biz_mode"
FRIEND_LABEL_CACHE_TTL_SECONDS = 300.0
SCOPE_TARGET_ALIASES = {
    "room": "rooms",
    "rooms": "rooms",
    "group": "rooms",
    "groups": "rooms",
    "friend_label": "friend_labels",
    "friend_labels": "friend_labels",
    "friend-labels": "friend_labels",
    "friends": "friend_labels",
    "biz": "biz",
    "official_account": "biz",
    "official_accounts": "biz",
}

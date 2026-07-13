"""兼容旧拼写 plugins.invite_to_toom（已弃用，请使用 invite_to_room）。

后续版本将删除本文件；启动时会自动把配置与状态迁移到 invite_to_room。
"""

from .invite_to_room import *  # noqa: F403

name = "invite_to_toom"

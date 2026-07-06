"""联系人/群成员目录缓存，用于消息展示 enrichment。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Any

from loguru import logger

from client import WxRobotApiClient

@dataclass(slots=True)
class ContactProfile:
    wxid: str
    display_name: str
    avatar_url: str
    nickname: str = ""


@dataclass(slots=True)
class RoomMemberProfile:
    wxid: str
    display_name: str
    avatar_url: str
    nick_name: str = ""
    room_nick_name: str = ""


CONTACT_MISS_CACHE_TTL_SECONDS = 30.0
CONTACT_REFRESH_COOLDOWN_SECONDS = 3.0
ROOM_MEMBER_CACHE_TTL_SECONDS = 300.0
PLUGIN_TARGETS_CACHE_TTL_SECONDS = 60.0


class ContactDirectoryCache:
    def __init__(self, api_client: WxRobotApiClient):
        self.api_client = api_client
        self._contacts: dict[int, dict[str, ContactProfile]] = {}
        self._contact_miss_cache: dict[int, dict[str, float]] = {}
        self._contact_refresh_attempted_at: dict[int, float] = {}
        self._room_members: dict[tuple[int, str], dict[str, RoomMemberProfile]] = {}
        self._room_member_expires_at: dict[tuple[int, str], float] = {}
        self._contact_locks: dict[int, asyncio.Lock] = {}
        self._room_member_locks: dict[tuple[int, str], asyncio.Lock] = {}

    @staticmethod
    def _pid_key(wxpid: int | None) -> int:
        return -1 if wxpid in (None, "") else int(wxpid)

    def _get_contact_lock(self, wxpid: int | None) -> asyncio.Lock:
        key = self._pid_key(wxpid)
        lock = self._contact_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._contact_locks[key] = lock
        return lock

    def _clear_contact_miss_cache(self, wxpid: int | None) -> None:
        self._contact_miss_cache.pop(self._pid_key(wxpid), None)

    def _remember_contact_miss(self, wxid: str, wxpid: int | None) -> None:
        normalized_wxid = str(wxid or "").strip()
        if not normalized_wxid:
            return
        pid_key = self._pid_key(wxpid)
        miss_cache = self._contact_miss_cache.get(pid_key)
        if miss_cache is None:
            miss_cache = {}
            self._contact_miss_cache[pid_key] = miss_cache
        miss_cache[normalized_wxid] = monotonic() + CONTACT_MISS_CACHE_TTL_SECONDS

    def _is_contact_miss_cached(self, wxid: str, wxpid: int | None) -> bool:
        normalized_wxid = str(wxid or "").strip()
        if not normalized_wxid:
            return False
        pid_key = self._pid_key(wxpid)
        miss_cache = self._contact_miss_cache.get(pid_key)
        if not miss_cache:
            return False
        expires_at = miss_cache.get(normalized_wxid)
        if expires_at is None:
            return False
        if expires_at <= monotonic():
            miss_cache.pop(normalized_wxid, None)
            if not miss_cache:
                self._contact_miss_cache.pop(pid_key, None)
            return False
        return True

    def _get_room_member_lock(self, roomid: str, wxpid: int | None) -> asyncio.Lock:
        key = (self._pid_key(wxpid), roomid)
        lock = self._room_member_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._room_member_locks[key] = lock
        return lock

    @staticmethod
    def _build_contact_profile(item: dict[str, Any]) -> ContactProfile | None:
        wxid = str(item.get("wxid") or "").strip()
        if not wxid:
            return None
        nickname = str(item.get("nickname") or "").strip()
        remarks = str(item.get("remarks") or "").strip()
        display_name = nickname or remarks or wxid
        avatar_url = str(item.get("small_head_url") or item.get("big_head_url") or "").strip()
        return ContactProfile(wxid=wxid, display_name=display_name, avatar_url=avatar_url, nickname=nickname)

    @staticmethod
    def _build_room_member_profile(item: dict[str, Any]) -> RoomMemberProfile | None:
        wxid = str(item.get("username") or item.get("wxid") or "").strip()
        if not wxid:
            return None
        nick_name = str(item.get("nick_name") or "").strip()
        room_nick_name = str(item.get("room_nick_name") or "").strip()
        display_name = room_nick_name or nick_name or wxid
        avatar_url = str(item.get("small_head_url") or item.get("big_head_url") or "").strip()
        return RoomMemberProfile(
            wxid=wxid,
            display_name=display_name,
            avatar_url=avatar_url,
            nick_name=nick_name,
            room_nick_name=room_nick_name,
        )

    @staticmethod
    def _coerce_message_type(value: Any) -> int | None:
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

    async def warmup(self) -> None:
        wxpids: set[int | None] = {None}
        try:
            users = await self.api_client.get_logged_in_users()
        except Exception as exc:
            logger.warning("获取已登录微信账号列表失败，使用默认账号预热联系人缓存: {}", exc)
            users = []

        for item in users or []:
            wxpid = item.get("wxpid")
            if wxpid not in (None, ""):
                wxpids.add(int(wxpid))

        await asyncio.gather(*(self.refresh_contacts(wxpid) for wxpid in wxpids), return_exceptions=True)

    async def refresh_contacts(self, wxpid: int | None) -> dict[str, ContactProfile]:
        lock = self._get_contact_lock(wxpid)
        pid_key = self._pid_key(wxpid)
        async with lock:
            last_attempted_at = self._contact_refresh_attempted_at.get(pid_key)
            if last_attempted_at is not None and (monotonic() - last_attempted_at) < CONTACT_REFRESH_COOLDOWN_SECONDS:
                return self._contacts.get(pid_key, {})
            try:
                user_list, room_list, biz_list = await asyncio.gather(
                    self.api_client.get_user_list(wxpid),
                    self.api_client.get_room_list(wxpid),
                    self.api_client.get_biz_list(wxpid),
                )
            except Exception as exc:
                self._contact_refresh_attempted_at[pid_key] = monotonic()
                logger.warning("刷新联系人缓存失败(wxpid={}): {}", wxpid, exc)
                return self._contacts.get(pid_key, {})

            profiles: dict[str, ContactProfile] = {}
            for payload in (user_list, room_list, biz_list):
                for item in payload or []:
                    profile = self._build_contact_profile(item)
                    if profile is not None:
                        profiles[profile.wxid] = profile

            # Cache empty results as well so repeated message enrichment does not
            # fan out into the same contact refresh storm on every lookup.
            self._contacts[pid_key] = profiles
            self._clear_contact_miss_cache(wxpid)
            self._contact_refresh_attempted_at[pid_key] = monotonic()
            return self._contacts.get(pid_key, {})

    async def get_contact(self, wxid: str, wxpid: int | None) -> ContactProfile | None:
        normalized_wxid = str(wxid or "").strip()
        if not normalized_wxid:
            return None
        pid_keys = [self._pid_key(wxpid)]
        if wxpid not in (None, ""):
            pid_keys.append(self._pid_key(None))

        for pid_key in pid_keys:
            profile = self._contacts.get(pid_key, {}).get(normalized_wxid)
            if profile is not None:
                return profile

        if self._is_contact_miss_cached(normalized_wxid, wxpid):
            return None

        await self.refresh_contacts(wxpid)
        for pid_key in pid_keys:
            profile = self._contacts.get(pid_key, {}).get(normalized_wxid)
            if profile is not None:
                return profile

        self._remember_contact_miss(normalized_wxid, wxpid)
        return None

    def _is_room_member_cache_valid(self, cache_key: tuple[int, str]) -> bool:
        expires_at = self._room_member_expires_at.get(cache_key)
        if expires_at is None:
            return False
        if expires_at <= monotonic():
            self._room_member_expires_at.pop(cache_key, None)
            self._room_members.pop(cache_key, None)
            return False
        return cache_key in self._room_members

    async def refresh_room_members(self, roomid: str, wxpid: int | None) -> dict[str, RoomMemberProfile]:
        lock = self._get_room_member_lock(roomid, wxpid)
        cache_key = (self._pid_key(wxpid), roomid)
        async with lock:
            if self._is_room_member_cache_valid(cache_key):
                return self._room_members.get(cache_key, {})
            try:
                members = await self.api_client.get_room_members(roomid, wxpid)
            except Exception as exc:
                logger.warning("刷新群成员缓存失败(roomid={}, wxpid={}): {}", roomid, wxpid, exc)
                return self._room_members.get(cache_key, {})

            profiles: dict[str, RoomMemberProfile] = {}
            for item in members or []:
                profile = self._build_room_member_profile(item)
                if profile is not None:
                    profiles[profile.wxid] = profile

            # Mirror contact-cache behavior: even an empty member list should
            # suppress repeated refreshes until a later explicit invalidation.
            self._room_members[cache_key] = profiles
            self._room_member_expires_at[cache_key] = monotonic() + ROOM_MEMBER_CACHE_TTL_SECONDS
            return self._room_members.get(cache_key, {})

    async def get_room_member(self, roomid: str, wxid: str, wxpid: int | None) -> RoomMemberProfile | None:
        if not roomid or not wxid:
            return None
        cache_key = (self._pid_key(wxpid), roomid)
        if self._is_room_member_cache_valid(cache_key):
            return self._room_members.get(cache_key, {}).get(wxid)

        await self.refresh_room_members(roomid, wxpid)
        return self._room_members.get(cache_key, {}).get(wxid)

    async def enrich_message(self, message: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(message)
        wxpid = enriched.get("wxpid")
        conversation_wxid = str(enriched.get("conversation_wxid") or "").strip()
        sender_wxid = str(enriched.get("sender_wxid") or "").strip()
        is_group_message = bool(enriched.get("is_group_message"))

        conversation_task = self.get_contact(conversation_wxid, wxpid) if conversation_wxid else None
        sender_task = (
            None
            if is_group_message
            else (self.get_contact(sender_wxid, wxpid) if sender_wxid else None)
        )
        room_member_task = (
            self.get_room_member(conversation_wxid, sender_wxid, wxpid)
            if is_group_message and conversation_wxid and sender_wxid
            else None
        )
        pending_tasks = [task for task in (conversation_task, sender_task, room_member_task) if task is not None]
        if pending_tasks:
            resolved = await asyncio.gather(*pending_tasks)
        else:
            resolved = []
        resolved_iter = iter(resolved)
        conversation_profile = next(resolved_iter) if conversation_task is not None else None
        sender_profile = next(resolved_iter) if sender_task is not None else None
        room_member_profile = next(resolved_iter) if room_member_task is not None else None

        conversation_display_name = (
            conversation_profile.display_name if conversation_profile is not None else conversation_wxid or "未知会话"
        )
        sender_display_name = sender_profile.display_name if sender_profile is not None else sender_wxid or "未知发送者"
        room_sender_display_name = (
            room_member_profile.display_name if room_member_profile is not None else sender_wxid or "未知发送者"
        )
        avatar_url = ""
        if is_group_message:
            avatar_url = conversation_profile.avatar_url if conversation_profile is not None else ""
        else:
            avatar_url = (
                sender_profile.avatar_url
                if sender_profile is not None
                else conversation_profile.avatar_url if conversation_profile is not None else ""
            )

        text_content = ""
        message_type_code = self._coerce_message_type(enriched.get("local_type") or enriched.get("msg_type"))
        if message_type_code == 1:
            text_content = str(
                enriched.get("content")
                or (enriched.get("payload") or {}).get("message_content")
                or (enriched.get("payload") or {}).get("content")
                or ""
            )
            for candidate in (
                sender_wxid,
                conversation_wxid,
                str((enriched.get("payload") or {}).get("room_sender") or ""),
                str((enriched.get("payload") or {}).get("sender") or ""),
            ):
                if candidate and text_content.startswith(f"{candidate}:"):
                    text_content = text_content[len(candidate) + 1 :].lstrip()
                    break

        enriched.update(
            {
                "conversation_display_name": conversation_display_name,
                "sender_display_name": sender_display_name,
                "room_sender_display_name": room_sender_display_name,
                "avatar_url": avatar_url,
                "conversation_avatar_url": conversation_profile.avatar_url if conversation_profile is not None else "",
                "sender_avatar_url": sender_profile.avatar_url if sender_profile is not None else "",
                "room_sender_avatar_url": room_member_profile.avatar_url if room_member_profile is not None else "",
                "title_display": conversation_display_name if is_group_message else (sender_display_name or conversation_display_name),
                "text_content": text_content,
            }
        )
        return enriched

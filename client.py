import asyncio
import json
from datetime import datetime
from time import monotonic
from typing import Any
from urllib import error, request


class WxRobotApiError(RuntimeError):
    pass


class WxRobotApiClient:
    _LIVE_WXPID_CACHE_TTL_SECONDS = 5.0

    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._cached_live_wxpids: list[int] = []
        self._cached_live_wxpids_at = 0.0

    @staticmethod
    def _coerce_timeout(value: Any) -> float | None:
        try:
            timeout = float(value)
        except (TypeError, ValueError):
            return None
        return timeout if timeout > 0 else None

    def _resolve_request_timeout(self, request_timeout: float | None = None) -> float:
        return self._coerce_timeout(request_timeout) or self.timeout

    def _resolve_wait_request_timeout(
        self,
        *,
        wait: bool,
        timeout: float | int | None,
        buffer_seconds: float = 2.0,
    ) -> float | None:
        if not wait:
            return None
        operation_timeout = self._coerce_timeout(timeout)
        if operation_timeout is None:
            return None
        return max(self.timeout, operation_timeout + max(0.0, buffer_seconds))

    @staticmethod
    def _normalize_wxpid_value(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_unix_seconds(value: Any) -> int:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            numeric_value = int(value)
            return numeric_value // 1000 if abs(numeric_value) >= 1_000_000_000_000 else numeric_value

        text = str(value or "").strip()
        if not text:
            raise ValueError("时间不能为空")

        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            numeric_value = int(text)
            return numeric_value // 1000 if abs(numeric_value) >= 1_000_000_000_000 else numeric_value

        normalized_text = text.replace("T", " ")
        for format_string in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return int(datetime.strptime(normalized_text, format_string).timestamp())
            except ValueError:
                continue

        try:
            return int(datetime.fromisoformat(text).timestamp())
        except ValueError as exc:
            raise ValueError(f"无法解析时间参数: {value}") from exc

    @classmethod
    def _extract_wxpids(cls, payload: Any) -> list[int]:
        wxpids = payload.get("wxpids") if isinstance(payload, dict) else payload
        items: list[int] = []
        for item in wxpids if isinstance(wxpids, list) else []:
            normalized = cls._normalize_wxpid_value(item)
            if normalized is None or normalized in items:
                continue
            items.append(normalized)
        return items

    def _cache_live_wxpids(self, wxpids: list[int]) -> list[int]:
        self._cached_live_wxpids = list(wxpids)
        self._cached_live_wxpids_at = monotonic()
        return list(self._cached_live_wxpids)

    def _get_live_wxpids_sync(self, request_timeout: float | None = None, *, force: bool = False) -> list[int]:
        now = monotonic()
        if not force and self._cached_live_wxpids_at > 0 and now - self._cached_live_wxpids_at <= self._LIVE_WXPID_CACHE_TTL_SECONDS:
            return list(self._cached_live_wxpids)
        try:
            payload = self._request_json_sync("/getwxpids", None, "GET", request_timeout)
        except WxRobotApiError:
            return list(self._cached_live_wxpids)
        return self._cache_live_wxpids(self._extract_wxpids(payload))

    def _resolve_optional_wxpid_sync(self, wxpid: Any, request_timeout: float | None = None) -> int | None:
        normalized_wxpid = self._normalize_wxpid_value(wxpid)
        live_wxpids = self._get_live_wxpids_sync(request_timeout)
        if not live_wxpids:
            return normalized_wxpid
        if normalized_wxpid in live_wxpids:
            return normalized_wxpid
        return live_wxpids[0]

    def _normalize_payload_wxpid_sync(
        self,
        payload: dict[str, Any] | None,
        request_timeout: float | None = None,
    ) -> dict[str, Any] | None:
        if payload is None:
            return None
        next_payload = dict(payload)
        resolved_wxpid = self._resolve_optional_wxpid_sync(next_payload.get("wxpid"), request_timeout)
        if resolved_wxpid is None:
            next_payload.pop("wxpid", None)
        else:
            next_payload["wxpid"] = resolved_wxpid
        return next_payload

    async def get_json(self, path: str, request_timeout: float | None = None) -> Any:
        return await asyncio.to_thread(self._request_json_sync, path, None, "GET", request_timeout)

    async def post_json(self, path: str, payload: dict[str, Any], request_timeout: float | None = None) -> Any:
        return await asyncio.to_thread(self._request_json_sync, path, payload, "POST", request_timeout)

    async def post_json_with_status(self, path: str, payload: dict[str, Any], request_timeout: float | None = None) -> Any:
        return await asyncio.to_thread(
            self._request_json_sync,
            path,
            payload,
            "POST",
            request_timeout,
            include_status_code=True,
        )

    def _request_json_sync(
        self,
        path: str,
        payload: dict[str, Any] | None,
        method: str,
        request_timeout: float | None = None,
        *,
        include_status_code: bool = False,
    ) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        effective_timeout = self._resolve_request_timeout(request_timeout)
        normalized_payload = self._normalize_payload_wxpid_sync(payload, effective_timeout)
        body = None if normalized_payload is None else json.dumps(normalized_payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"} if normalized_payload is not None else {}
        req = request.Request(
            url,
            data=body,
            headers=headers,
            method=method,
        )
        status_code: int | None = None
        try:
            with request.urlopen(req, timeout=effective_timeout) as resp:
                try:
                    status_code = int(getattr(resp, "status", None) or resp.getcode())
                except (TypeError, ValueError):
                    status_code = None
                response_text = resp.read().decode("utf-8")
        except TimeoutError as exc:
            raise WxRobotApiError(f"调用 {url} 超时({effective_timeout:.1f}s)") from exc
        except error.HTTPError as exc:
            response_text = exc.read().decode("utf-8", errors="ignore")
            raise WxRobotApiError(f"调用 {url} 失败，HTTP {exc.code}: {response_text}") from exc
        except error.URLError as exc:
            raise WxRobotApiError(f"调用 {url} 失败: {exc.reason}") from exc

        if not response_text:
            return {"status_code": status_code} if include_status_code and status_code is not None else {}
        try:
            parsed_response = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise WxRobotApiError(f"调用 {url} 返回了非 JSON 响应: {response_text}") from exc

        if include_status_code and status_code is not None:
            if isinstance(parsed_response, dict):
                parsed_response = dict(parsed_response)
                parsed_response.setdefault("status_code", status_code)
            else:
                parsed_response = {
                    "status_code": status_code,
                    "data": parsed_response,
                }
        return parsed_response

    @staticmethod
    def _with_optional_wxpid(payload: dict[str, Any] | None = None, wxpid: int | None = None) -> dict[str, Any]:
        next_payload = dict(payload or {})
        if wxpid is not None:
            next_payload["wxpid"] = wxpid
        return next_payload

    @staticmethod
    def _normalize_wxids(wxids: list[str] | tuple[str, ...] | str) -> str:
        if isinstance(wxids, (list, tuple, set)):
            return ",".join(str(item).strip() for item in wxids if str(item).strip())
        return str(wxids or "").strip()

    @staticmethod
    def _normalize_labels(labels: list[str] | tuple[str, ...] | str) -> str:
        if isinstance(labels, (list, tuple, set)):
            return ",".join(str(item).strip() for item in labels if str(item).strip())
        return str(labels or "").strip()

    async def get_logged_in_users(self) -> list[dict[str, Any]]:
        return await self.get_json("/getusers")

    async def get_wx_pids(self) -> list[int]:
        return self._cache_live_wxpids(self._extract_wxpids(await self.get_json("/getwxpids")))

    async def hook(self) -> Any:
        return await self.get_json("/hook")

    async def get_user_list(self, wxpid: int | None = None) -> list[dict[str, Any]]:
        return await self.post_json("/user/list", self._with_optional_wxpid(wxpid=wxpid))

    async def get_room_list(self, wxpid: int | None = None) -> list[dict[str, Any]]:
        return await self.post_json("/room/list", self._with_optional_wxpid(wxpid=wxpid))

    async def get_biz_list(self, wxpid: int | None = None) -> list[dict[str, Any]]:
        return await self.post_json("/other/getbizlist", self._with_optional_wxpid(wxpid=wxpid))

    async def get_room_members(self, roomid: str, wxpid: int | None = None) -> list[dict[str, Any]]:
        payload = self._with_optional_wxpid({"roomid": roomid}, wxpid)
        return await self.post_json("/room/getmembers", payload)

    async def get_user_info(self, wxid: str, roomid: str = "", wxpid: int | None = None) -> dict[str, Any]:
        payload = self._with_optional_wxpid({"wxid": wxid, "roomid": roomid}, wxpid)
        return await self.post_json("/user/info", payload)

    async def download_cdn_image(
        self,
        msgid: str,
        wxid: str,
        wxpid: int | None = None,
        flag: int = 3,
        wait: bool = True,
        timeout: int = 15,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "msgid": msgid,
            "wxid": wxid,
            "flag": flag,
            "wait": wait,
            "timeout": timeout,
        }
        if wxpid is not None:
            payload["wxpid"] = wxpid
        request_timeout = self._resolve_wait_request_timeout(wait=wait, timeout=timeout)
        return await self.post_json_with_status("/cdn/image", payload, request_timeout=request_timeout)

    async def download_cdn_video(
        self,
        msgid: str,
        wxid: str,
        wxpid: int | None = None,
        wait: bool = True,
        timeout: int = 15,
    ) -> dict[str, Any]:
        payload = self._with_optional_wxpid({"msgid": msgid, "wxid": wxid, "wait": wait, "timeout": timeout}, wxpid)
        request_timeout = self._resolve_wait_request_timeout(wait=wait, timeout=timeout)
        return await self.post_json("/cdn/video", payload, request_timeout=request_timeout)

    async def download_cdn_file(
        self,
        msgid: str,
        wxid: str,
        wxpid: int | None = None,
        wait: bool = True,
        timeout: int = 15,
    ) -> dict[str, Any]:
        payload = self._with_optional_wxpid({"msgid": msgid, "wxid": wxid, "wait": wait, "timeout": timeout}, wxpid)
        request_timeout = self._resolve_wait_request_timeout(wait=wait, timeout=timeout)
        return await self.post_json("/cdn/file", payload, request_timeout=request_timeout)

    async def send_text(
        self,
        wxid: str,
        content: str,
        atlist: str = "",
        wxpid: int | None = None,
        wait: bool = False,
        timeout: int = 3,
    ) -> dict[str, Any]:
        payload = self._with_optional_wxpid(
            {"wxid": wxid, "content": content, "atlist": atlist, "wait": wait, "timeout": timeout},
            wxpid,
        )
        request_timeout = self._resolve_wait_request_timeout(wait=wait, timeout=timeout)
        return await self.post_json("/send/text", payload, request_timeout=request_timeout)

    async def send_image(
        self,
        wxid: str,
        path: str,
        wxpid: int | None = None,
        wait: bool = False,
        timeout: int = 3,
    ) -> dict[str, Any]:
        payload = self._with_optional_wxpid({"wxid": wxid, "path": path, "wait": wait, "timeout": timeout}, wxpid)
        request_timeout = self._resolve_wait_request_timeout(wait=wait, timeout=timeout)
        return await self.post_json("/send/image", payload, request_timeout=request_timeout)

    async def send_file(
        self,
        wxid: str,
        path: str,
        wxpid: int | None = None,
        wait: bool = False,
        timeout: int = 3,
    ) -> dict[str, Any]:
        payload = self._with_optional_wxpid({"wxid": wxid, "path": path, "wait": wait, "timeout": timeout}, wxpid)
        request_timeout = self._resolve_wait_request_timeout(wait=wait, timeout=timeout)
        return await self.post_json("/send/file", payload, request_timeout=request_timeout)

    async def send_video(
        self,
        wxid: str,
        path: str,
        wxpid: int | None = None,
        wait: bool = False,
        timeout: int = 3,
    ) -> dict[str, Any]:
        payload = self._with_optional_wxpid({"wxid": wxid, "path": path, "wait": wait, "timeout": timeout}, wxpid)
        request_timeout = self._resolve_wait_request_timeout(wait=wait, timeout=timeout)
        return await self.post_json("/send/video", payload, request_timeout=request_timeout)

    async def send_gif(
        self,
        wxid: str,
        path: str,
        wxpid: int | None = None,
        wait: bool = False,
        timeout: int = 3,
    ) -> dict[str, Any]:
        payload = self._with_optional_wxpid({"wxid": wxid, "path": path, "wait": wait, "timeout": timeout}, wxpid)
        request_timeout = self._resolve_wait_request_timeout(wait=wait, timeout=timeout)
        return await self.post_json("/send/gif", payload, request_timeout=request_timeout)

    async def send_article(
        self,
        wxid: str,
        title: str,
        url: str,
        cover: str,
        ghid: str,
        nickname: str,
        desc: str = "",
        wxpid: int | None = None,
        wait: bool = False,
        timeout: int = 3,
    ) -> dict[str, Any]:
        payload = self._with_optional_wxpid(
            {
                "wxid": wxid,
                "title": title,
                "desc": desc,
                "url": url,
                "cover": cover,
                "ghid": ghid,
                "nickname": nickname,
                "wait": wait,
                "timeout": timeout,
            },
            wxpid,
        )
        request_timeout = self._resolve_wait_request_timeout(wait=wait, timeout=timeout)
        return await self.post_json("/send/article", payload, request_timeout=request_timeout)

    async def check_user_state(self, wxid: str, wxpid: int | None = None) -> dict[str, Any]:
        return await self.post_json("/user/checkstate", self._with_optional_wxpid({"wxid": wxid}, wxpid))

    async def set_remarks(self, wxid: str, remarks: str, wxpid: int | None = None) -> dict[str, Any]:
        return await self.post_json("/user/setremarks", self._with_optional_wxpid({"wxid": wxid, "remarks": remarks}, wxpid))

    async def delete_user(self, wxid: str, wxpid: int | None = None) -> dict[str, Any]:
        return await self.post_json("/user/delete", self._with_optional_wxpid({"wxid": wxid}, wxpid))

    async def agree_friend_request(
        self,
        wxid: str,
        v4: str,
        remarks: str = "",
        labels: str = "",
        sns_permissions: int = 0,
        add_type: int = 1,
        wxpid: int | None = None,
    ) -> dict[str, Any]:
        payload = {
            "wxid": wxid,
            "v4": v4,
            "remarks": remarks,
            "labels": labels,
            "sns_permissions": sns_permissions,
            "add_type": add_type,
        }
        return await self.post_json("/user/agreefriend", self._with_optional_wxpid(payload, wxpid))

    async def receive_notify(self, wxid: str, notify: bool = True, wxpid: int | None = None) -> dict[str, Any]:
        return await self.post_json("/user/receivenotify", self._with_optional_wxpid({"wxid": wxid, "notify": notify}, wxpid))

    async def add_room_member(
        self,
        wxid: str,
        roomid: str,
        remarks: str = "",
        content: str = "",
        sns_permissions: int = 0,
        wxpid: int | None = None,
    ) -> dict[str, Any]:
        payload = {"wxid": wxid, "roomid": roomid, "remarks": remarks, "content": content, "sns_permissions": sns_permissions}
        return await self.post_json("/user/addroommember", self._with_optional_wxpid(payload, wxpid))

    async def invite_room_members(self, roomid: str, wxids: list[str] | tuple[str, ...] | str, wxpid: int | None = None) -> dict[str, Any]:
        return await self.post_json("/room/invitemembers", self._with_optional_wxpid({"roomid": roomid, "wxids": self._normalize_wxids(wxids)}, wxpid))

    async def add_room_members(self, roomid: str, wxids: list[str] | tuple[str, ...] | str, wxpid: int | None = None) -> dict[str, Any]:
        return await self.post_json("/room/addmembers", self._with_optional_wxpid({"roomid": roomid, "wxids": self._normalize_wxids(wxids)}, wxpid))

    async def delete_room_members(self, roomid: str, wxids: list[str] | tuple[str, ...] | str, wxpid: int | None = None) -> dict[str, Any]:
        return await self.post_json("/room/deletemembers", self._with_optional_wxpid({"roomid": roomid, "wxids": self._normalize_wxids(wxids)}, wxpid))

    async def exec_sql(self, sql: str, db_name: str | None = None, wxpid: int | None = None) -> dict[str, Any]:
        return await self.post_json("/other/execsql", self._with_optional_wxpid({"sql": sql, "db_name": db_name}, wxpid))

    async def get_chat_messages(
        self,
        wxid: str,
        start_time: str | int,
        end_time: str | int,
        max_count: int = 500,
        wxpid: int | None = None,
    ) -> list[dict[str, Any]]:
        payload = {
            "wxid": wxid,
            "start_time": self._normalize_unix_seconds(start_time),
            "end_time": self._normalize_unix_seconds(end_time),
            "max_count": max_count,
        }
        return await self.post_json("/other/chatmsgs", self._with_optional_wxpid(payload, wxpid))

    async def get_resource_path(self, msgid: str, wxid: str, local_type: int, wxpid: int | None = None) -> dict[str, Any]:
        payload = {"msgid": msgid, "wxid": wxid, "local_type": local_type}
        return await self.post_json("/other/resourcepath", self._with_optional_wxpid(payload, wxpid))

    async def get_labels(self, wxpid: int | None = None) -> dict[str, Any]:
        return await self.post_json("/label/get", self._with_optional_wxpid({}, wxpid))

    async def add_label(self, label_name: str, wxpid: int | None = None) -> dict[str, Any]:
        return await self.post_json("/label/add", self._with_optional_wxpid({"label_name": label_name}, wxpid))

    async def set_labels(self, wxid: str, labels: list[str] | tuple[str, ...] | str, wxpid: int | None = None) -> dict[str, Any]:
        payload = {"wxid": wxid, "labels": self._normalize_labels(labels)}
        return await self.post_json("/label/set", self._with_optional_wxpid(payload, wxpid))

    async def delete_labels(self, labels: list[str] | tuple[str, ...] | str, wxpid: int | None = None) -> dict[str, Any]:
        payload = {"labels": self._normalize_labels(labels)}
        return await self.post_json("/label/delete", self._with_optional_wxpid(payload, wxpid))

    async def getLoggedInUsers(self) -> list[dict[str, Any]]:
        return await self.get_logged_in_users()

    async def getWxPids(self) -> list[int]:
        return await self.get_wx_pids()

    async def getUserList(self, *, wxpid: int | None = None) -> list[dict[str, Any]]:
        return await self.get_user_list(wxpid)

    async def getRoomList(self, *, wxpid: int | None = None) -> list[dict[str, Any]]:
        return await self.get_room_list(wxpid)

    async def getBizList(self, *, wxpid: int | None = None) -> list[dict[str, Any]]:
        return await self.get_biz_list(wxpid)

    async def getRoomMembers(self, *, roomid: str, wxpid: int | None = None) -> list[dict[str, Any]]:
        return await self.get_room_members(roomid, wxpid)

    async def getUserInfo(self, *, wxid: str, roomid: str = "", wxpid: int | None = None) -> dict[str, Any]:
        return await self.get_user_info(wxid, roomid, wxpid)

    async def downloadCdnImage(self, *, msgid: str, wxid: str, wxpid: int | None = None, flag: int = 3, wait: bool = True, timeout: int = 15) -> dict[str, Any]:
        return await self.download_cdn_image(msgid, wxid, wxpid, flag, wait, timeout)

    async def downloadCdnVideo(self, *, msgid: str, wxid: str, wxpid: int | None = None, wait: bool = True, timeout: int = 15) -> dict[str, Any]:
        return await self.download_cdn_video(msgid, wxid, wxpid, wait, timeout)

    async def downloadCdnFile(self, *, msgid: str, wxid: str, wxpid: int | None = None, wait: bool = True, timeout: int = 15) -> dict[str, Any]:
        return await self.download_cdn_file(msgid, wxid, wxpid, wait, timeout)

    async def sendText(self, *, wxid: str, content: str, atlist: str = "", wxpid: int | None = None, wait: bool = False, timeout: int = 3) -> dict[str, Any]:
        return await self.send_text(wxid, content, atlist, wxpid, wait, timeout)

    async def sendImage(self, *, wxid: str, path: str, wxpid: int | None = None, wait: bool = False, timeout: int = 3) -> dict[str, Any]:
        return await self.send_image(wxid, path, wxpid, wait, timeout)

    async def sendFile(self, *, wxid: str, path: str, wxpid: int | None = None, wait: bool = False, timeout: int = 3) -> dict[str, Any]:
        return await self.send_file(wxid, path, wxpid, wait, timeout)

    async def sendVideo(self, *, wxid: str, path: str, wxpid: int | None = None, wait: bool = False, timeout: int = 3) -> dict[str, Any]:
        return await self.send_video(wxid, path, wxpid, wait, timeout)

    async def sendGif(self, *, wxid: str, path: str, wxpid: int | None = None, wait: bool = False, timeout: int = 3) -> dict[str, Any]:
        return await self.send_gif(wxid, path, wxpid, wait, timeout)

    async def sendArticle(self, *, wxid: str, title: str, url: str, cover: str, ghid: str, nickname: str, desc: str = "", wxpid: int | None = None, wait: bool = False, timeout: int = 3) -> dict[str, Any]:
        return await self.send_article(wxid, title, url, cover, ghid, nickname, desc, wxpid, wait, timeout)

    async def checkUserState(self, *, wxid: str, wxpid: int | None = None) -> dict[str, Any]:
        return await self.check_user_state(wxid, wxpid)

    async def setRemarks(self, *, wxid: str, remarks: str, wxpid: int | None = None) -> dict[str, Any]:
        return await self.set_remarks(wxid, remarks, wxpid)

    async def deleteUser(self, *, wxid: str, wxpid: int | None = None) -> dict[str, Any]:
        return await self.delete_user(wxid, wxpid)

    async def agreeFriendRequest(self, *, wxid: str, v4: str, remarks: str = "", labels: list[str] | tuple[str, ...] | str = "", sns_permissions: int = 0, add_type: int = 1, wxpid: int | None = None) -> dict[str, Any]:
        return await self.agree_friend_request(wxid, v4, remarks, self._normalize_labels(labels), sns_permissions, add_type, wxpid)

    async def receiveNotify(self, *, wxid: str, notify: bool = True, wxpid: int | None = None) -> dict[str, Any]:
        return await self.receive_notify(wxid, notify, wxpid)

    async def addRoomMember(self, *, wxid: str, roomid: str, remarks: str = "", content: str = "", sns_permissions: int = 0, wxpid: int | None = None) -> dict[str, Any]:
        return await self.add_room_member(wxid, roomid, remarks, content, sns_permissions, wxpid)

    async def inviteRoomMembers(self, *, roomid: str, wxids: list[str] | tuple[str, ...] | str, wxpid: int | None = None) -> dict[str, Any]:
        return await self.invite_room_members(roomid, wxids, wxpid)

    async def addRoomMembers(self, *, roomid: str, wxids: list[str] | tuple[str, ...] | str, wxpid: int | None = None) -> dict[str, Any]:
        return await self.add_room_members(roomid, wxids, wxpid)

    async def deleteRoomMembers(self, *, roomid: str, wxids: list[str] | tuple[str, ...] | str, wxpid: int | None = None) -> dict[str, Any]:
        return await self.delete_room_members(roomid, wxids, wxpid)

    async def execSql(self, *, sql: str, db_name: str | None = None, wxpid: int | None = None) -> dict[str, Any]:
        return await self.exec_sql(sql, db_name, wxpid)

    async def getChatMessages(self, *, wxid: str, start_time: str | int, end_time: str | int, max_count: int = 500, wxpid: int | None = None) -> list[dict[str, Any]]:
        return await self.get_chat_messages(wxid, start_time, end_time, max_count, wxpid)

    async def getResourcePath(self, *, msgid: str, wxid: str, local_type: int, wxpid: int | None = None) -> dict[str, Any]:
        return await self.get_resource_path(msgid, wxid, local_type, wxpid)

    async def getLabels(self, *, wxpid: int | None = None) -> dict[str, Any]:
        return await self.get_labels(wxpid)

    async def addLabel(self, *, label_name: str, wxpid: int | None = None) -> dict[str, Any]:
        return await self.add_label(label_name, wxpid)

    async def setLabels(self, *, wxid: str, labels: list[str] | tuple[str, ...] | str, wxpid: int | None = None) -> dict[str, Any]:
        return await self.set_labels(wxid, labels, wxpid)

    async def deleteLabels(self, *, labels: list[str] | tuple[str, ...] | str, wxpid: int | None = None) -> dict[str, Any]:
        return await self.delete_labels(labels, wxpid)
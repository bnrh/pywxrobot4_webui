from datetime import datetime, timedelta
from typing import Any

from core.config import normalize_plugin_module_name

DOWNLOAD_RECENT_USER_IMAGES_PLUGIN_MODULE = normalize_plugin_module_name("plugins.download_recent_user_images")
ENTER_ROOM_TIP_PLUGIN_MODULE = normalize_plugin_module_name("plugins.enter_room_tip")
ROOM_AI_REPLY_PLUGIN_MODULE = normalize_plugin_module_name("plugins.room_ai_reply")
INVITE_TO_ROOM_PLUGIN_MODULE = normalize_plugin_module_name("plugins.invite_to_room")
INVITE_TO_ROOM_ALIAS_MODULE = normalize_plugin_module_name("plugins.invite_to_toom")

def normalize_plugin_config_for_payload(module_name: str, config: Any) -> Any:
    normalized_module_name = normalize_plugin_module_name(module_name)
    if normalized_module_name == DOWNLOAD_RECENT_USER_IMAGES_PLUGIN_MODULE and isinstance(config, dict):
        normalized_config = {
            key: value
            for key, value in config.items()
            if key not in {"db_name", "wait", "timeout"}
        }
        if not str(normalized_config.get("start_time") or "").strip():
            normalized_config["start_time"] = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        return normalized_config

    if normalized_module_name == ENTER_ROOM_TIP_PLUGIN_MODULE and isinstance(config, dict):
        normalized_rows: list[dict[str, Any]] = []
        raw_rows = config.get("room_welcomes")

        def normalize_image_path(value: Any) -> str:
            return str(value or "").strip().replace("\\", "/")

        def append_room_welcome(roomid: Any, content: Any = "", path: Any = "") -> None:
            normalized_roomid = str(roomid or "").strip()
            normalized_content = str(content or "").strip()
            normalized_path = normalize_image_path(path)
            if not normalized_roomid or (not normalized_content and not normalized_path):
                return
            row = {
                "roomid": normalized_roomid,
                "content": normalized_content,
                "path": normalized_path,
            }
            existing_index = next((index for index, item in enumerate(normalized_rows) if item.get("roomid") == normalized_roomid), -1)
            if existing_index >= 0:
                normalized_rows[existing_index] = row
            else:
                normalized_rows.append(row)

        if isinstance(raw_rows, list):
            for item in raw_rows:
                if not isinstance(item, dict):
                    continue
                append_room_welcome(
                    item.get("roomid") or item.get("wxid"),
                    item.get("content") or item.get("text"),
                    item.get("path") or item.get("image_path") or item.get("image"),
                )
        else:
            legacy_rows = raw_rows if isinstance(raw_rows, dict) else config.get("welcome_file")
            if isinstance(legacy_rows, dict):
                for roomid, items in legacy_rows.items():
                    if isinstance(items, dict):
                        append_room_welcome(roomid, items.get("content") or items.get("text"), items.get("path") or items.get("image_path") or items.get("image"))
                        continue
                    if isinstance(items, str):
                        append_room_welcome(roomid, items, "")
                        continue
                    if not isinstance(items, list):
                        continue
                    text_segments: list[str] = []
                    image_path = ""
                    for item in items:
                        if isinstance(item, str):
                            text_segments.append(str(item).strip())
                            continue
                        if not isinstance(item, dict):
                            continue
                        content = str(item.get("content") or item.get("text") or "").strip()
                        path = normalize_image_path(item.get("path") or item.get("image_path") or item.get("image"))
                        if content:
                            text_segments.append(content)
                        if path and not image_path:
                            image_path = path
                    append_room_welcome(roomid, "\n".join(segment for segment in text_segments if segment).strip(), image_path)

        if normalized_rows:
            return {
                **config,
                "room_welcomes": normalized_rows,
            }
        return config

    if normalized_module_name == ROOM_AI_REPLY_PLUGIN_MODULE and isinstance(config, dict):
        normalized_rows: list[dict[str, Any]] = []

        def append_room_config(roomid: Any, base_url: Any = "", api_key: Any = "", model: Any = "", system_prompt: Any = "") -> None:
            normalized_roomid = str(roomid or "").strip()
            if not normalized_roomid:
                return
            row = {
                "roomid": normalized_roomid,
                "base_url": str(base_url or "").strip(),
                "api_key": str(api_key or "").strip(),
                "model": str(model or "").strip(),
                "system_prompt": str(system_prompt or "").strip(),
            }
            existing_index = next((index for index, item in enumerate(normalized_rows) if item.get("roomid") == normalized_roomid), -1)
            if existing_index >= 0:
                normalized_rows[existing_index] = row
            else:
                normalized_rows.append(row)

        raw_rows = config.get("room_configs")
        if isinstance(raw_rows, list):
            for item in raw_rows:
                if not isinstance(item, dict):
                    continue
                append_room_config(
                    item.get("roomid") or item.get("wxid"),
                    item.get("base_url"),
                    item.get("api_key"),
                    item.get("model"),
                    item.get("system_prompt") or item.get("prompt"),
                )

        if not normalized_rows:
            append_room_config(
                config.get("roomid") or config.get("wxid"),
                config.get("base_url"),
                config.get("api_key"),
                config.get("model"),
                config.get("system_prompt") or config.get("prompt"),
            )

        if normalized_rows:
            return {
                **config,
                "room_configs": normalized_rows,
            }
        return config

    if normalized_module_name not in {INVITE_TO_ROOM_PLUGIN_MODULE, INVITE_TO_ROOM_ALIAS_MODULE} or not isinstance(config, dict):
        return config

    normalized_rules: list[dict[str, Any]] = []
    seen_rules: set[tuple[str, str, bool]] = set()

    def normalize_rule_full_match(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value or "").strip().lower() in {"1", "true", "yes", "on", "y", "是"}

    def append_rule(roomid: Any, keyword: Any, full_match: Any = False) -> None:
        normalized_roomid = str(roomid or "").strip()
        normalized_keyword = str(keyword or "").strip()
        normalized_full_match = normalize_rule_full_match(full_match)
        rule_key = (normalized_roomid, normalized_keyword, normalized_full_match)
        if not normalized_roomid or not normalized_keyword or rule_key in seen_rules:
            return
        seen_rules.add(rule_key)
        normalized_rules.append(
            {
                "roomid": normalized_roomid,
                "keyword": normalized_keyword,
                "full_match": normalized_full_match,
            }
        )

    raw_rules = config.get("keyword_rooms")
    if isinstance(raw_rules, list):
        for item in raw_rules:
            if not isinstance(item, dict):
                continue
            append_rule(item.get("roomid"), item.get("keyword"), item.get("full_match"))
    elif isinstance(raw_rules, dict):
        for keyword, roomid in raw_rules.items():
            append_rule(roomid, keyword, False)

    legacy_keywords = config.get("keywords")
    if isinstance(legacy_keywords, dict):
        for roomid, keyword_values in legacy_keywords.items():
            for keyword in [str(item or "").strip() for item in str(keyword_values or "").replace("，", ",").replace("\n", ",").split(",") if str(item or "").strip()]:
                append_rule(roomid, keyword, False)

    if not normalized_rules and not isinstance(raw_rules, list):
        return config

    return {
        **config,
        "keyword_rooms": normalized_rules,
    }

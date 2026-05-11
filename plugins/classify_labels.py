from ._plugin_sdk import normalize_text, sleep, to_string_list, unique_strings


name = "classify_labels"
description = "按配置将群成员归类到指定好友标签，适合批量标签整理"
category = "functional"
message_dependent = False
config_schema = [
    {
        "key": "wxpid",
        "label": "微信进程",
        "type": "select",
        "options_source": "wxpid_options",
        "empty_option_label": "请选择微信进程",
        "required": True,
        "required_message": "微信进程不能为空",
        "full_width": False,
        "description": "执行插件时使用这个微信进程，并遍历下方已配置规则的群聊。",
    },
    {
        "key": "process_interval_seconds",
        "label": "处理间隔(秒)",
        "type": "number",
        "default": 0.1,
        "min": 0,
        "max": 60,
        "step": 0.1,
        "full_width": False,
        "description": "每为一位好友写入标签后等待的秒数。",
    },
    {
        "key": "room_label_rules",
        "label": "标签配置规则",
        "type": "object-list",
        "display_mode": "table",
        "default": [],
        "meaningful_keys": ["roomid", "label"],
        "unique_by": ["roomid"],
        "unique_message": "同一个群聊只能保留一条规则",
        "empty_text": "暂无已保存规则，点击“新增”填写后，再点当前行的“保存”。",
        "description": "每行配置一个群聊及其对应标签。执行插件时会遍历这里配置的所有群聊。",
        "columns": [
            {
                "key": "roomid",
                "label": "群聊",
                "type": "select",
                "searchable": True,
                "options_source": "room_options",
                "empty_option_label": "",
                "placeholder": "输入群名称或 wxid 搜索",
                "required": True,
                "required_message": "群聊不能为空",
                "width": "wide",
            },
            {
                "key": "label",
                "label": "标签",
                "type": "select",
                "options_source": "label_options",
                "empty_option_label": "请选择标签",
                "required": True,
                "required_message": "标签不能为空",
                "width": "wide",
            },
        ],
    },
]


def normalize_wxpid(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def resolve_process_interval_seconds(config):
    raw_value = config.get("process_interval_seconds")
    if raw_value not in (None, ""):
        try:
            return max(0.0, float(raw_value or 0))
        except (TypeError, ValueError):
            return 0.1
    try:
        return max(0.0, float(config.get("delay_ms", 100) or 0) / 1000.0)
    except (TypeError, ValueError):
        return 0.1


def normalize_room_label_entries(config):
    raw_rules = config.get("room_label_rules")
    if raw_rules is None:
        raw_rules = config.get("room_labels")

    entries: list[dict[str, str]] = []
    seen_keys: set[str] = set()

    if isinstance(raw_rules, list):
        for item in raw_rules:
            if not isinstance(item, dict):
                continue
            roomid = normalize_text(item.get("roomid") or item.get("wxid"))
            room_name = normalize_text(item.get("room_name") or item.get("nickname") or item.get("name"))
            label = normalize_text(item.get("label") or item.get("label_name"))
            dedupe_key = roomid or room_name
            if not label or not dedupe_key or dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            entries.append({"roomid": roomid, "room_name": room_name, "label": label})
        return entries

    if isinstance(raw_rules, dict):
        for roomid, label in raw_rules.items():
            normalized_roomid = normalize_text(roomid)
            normalized_label = normalize_text(label)
            if not normalized_roomid or not normalized_label or normalized_roomid in seen_keys:
                continue
            seen_keys.add(normalized_roomid)
            entries.append({"roomid": normalized_roomid, "room_name": "", "label": normalized_label})
    return entries


async def build_room_lookup(context, wxpid):
    rooms = await context.api.get_room_list(wxpid)
    by_id = {}
    by_name = {}
    for room in rooms if isinstance(rooms, list) else []:
        roomid = normalize_text(room.get("wxid"))
        nickname = normalize_text(room.get("nickname") or room.get("remarks") or room.get("wxid"))
        if not roomid:
            continue
        entry = {"roomid": roomid, "nickname": nickname, "wxpid": wxpid}
        by_id[roomid] = entry
        if nickname and nickname not in by_name:
            by_name[nickname] = entry
    return {"by_id": by_id, "by_name": by_name}


async def build_friend_lookup(context, wxpid):
    friends = await context.api.get_user_list(wxpid)
    return {
        normalize_text(friend.get("wxid")): friend
        for friend in friends if isinstance(friends, list)
        for friend in friends
        if isinstance(friend, dict) and normalize_text(friend.get("wxid"))
    }


async def resolve_self_wxid(context, wxpid):
    users = await context.api.get_logged_in_users()
    for item in users if isinstance(users, list) else []:
        try:
            if int(item.get("wxpid") or item.get("pid") or -1) == int(wxpid):
                return normalize_text(item.get("wxid"))
        except (TypeError, ValueError):
            continue
    return ""


async def ensure_label_id(context, label_name, wxpid):
    labels = await context.api.get_labels(wxpid=wxpid)
    return normalize_text(labels.get(label_name)) if isinstance(labels, dict) else ""


def merge_labels(existing_labels, next_label_id):
    return unique_strings([*to_string_list(existing_labels), next_label_id])


def build_empty_report(reason, wxpid, process_interval_seconds, rule_count, *, error=""):
    return {
        "reason": reason,
        "wxpid": wxpid,
        "processIntervalSeconds": process_interval_seconds,
        "ruleCount": rule_count,
        "appliedCount": 0,
        "skippedCount": 0,
        "rooms": [],
        "error": error,
    }


async def run_label_classification(context, reason):
    entries = normalize_room_label_entries(context.config)
    wxpid = normalize_wxpid(context.config.get("wxpid"))
    process_interval_seconds = resolve_process_interval_seconds(context.config)
    delay_ms = process_interval_seconds * 1000

    if not entries:
        report = build_empty_report(reason, wxpid, process_interval_seconds, 0)
        context.state.namespace("classify_labels").set("last_report", report)
        return report

    if wxpid is None:
        report = build_empty_report(reason, None, process_interval_seconds, len(entries), error="missing-wxpid")
        context.logger.warning("好友标签分类插件缺少微信进程配置", report)
        context.state.namespace("classify_labels").set("last_report", report)
        return report

    context.logger.info(
        "好友标签分类开始执行",
        {
            "reason": reason,
            "wxpid": wxpid,
            "rule_count": len(entries),
            "process_interval_seconds": process_interval_seconds,
        },
    )

    room_lookup = await build_room_lookup(context, wxpid)
    context.logger.info("好友标签分类已加载群聊清单", {"reason": reason, "wxpid": wxpid, "room_count": len(room_lookup["by_id"])})

    friends_by_wxid = await build_friend_lookup(context, wxpid)
    context.logger.info("好友标签分类已加载好友清单", {"reason": reason, "wxpid": wxpid, "friend_count": len(friends_by_wxid)})

    self_wxid = await resolve_self_wxid(context, wxpid)
    context.logger.info("好友标签分类已解析当前账号", {"reason": reason, "wxpid": wxpid, "self_wxid": self_wxid})

    reports = []
    applied_count = 0
    skipped_count = 0

    for entry in entries:
        resolved_room = (entry.get("roomid") and room_lookup["by_id"].get(entry["roomid"])) or (entry.get("room_name") and room_lookup["by_name"].get(entry["room_name"]))
        if not resolved_room:
            skipped_count += 1
            context.logger.warning(
                "标签分类插件未找到目标群聊",
                {"reason": reason, "wxpid": wxpid, "roomid": entry.get("roomid"), "room_name": entry.get("room_name"), "label": entry.get("label")},
            )
            continue

        label_id = await ensure_label_id(context, entry["label"], wxpid)
        if not label_id:
            skipped_count += 1
            context.logger.warning(
                "标签分类插件未找到目标标签",
                {"reason": reason, "wxpid": wxpid, "roomid": resolved_room["roomid"], "room_name": resolved_room["nickname"], "label": entry["label"]},
            )
            continue

        context.logger.info(
            "标签分类插件开始处理规则",
            {"reason": reason, "wxpid": wxpid, "roomid": resolved_room["roomid"], "room_name": resolved_room["nickname"], "label": entry["label"], "label_id": label_id},
        )

        members = await context.api.get_room_members(resolved_room["roomid"], wxpid)
        room_applied = 0
        room_skipped = 0
        member_count = len(members) if isinstance(members, list) else 0

        for member in members if isinstance(members, list) else []:
            member_wxid = normalize_text(member.get("username") or member.get("wxid"))
            if not member_wxid or member_wxid == self_wxid:
                room_skipped += 1
                continue

            friend = friends_by_wxid.get(member_wxid)
            if not friend:
                room_skipped += 1
                continue

            existing_labels = to_string_list(friend.get("labels"))
            if label_id in existing_labels:
                room_skipped += 1
                continue

            merged_labels = merge_labels(existing_labels, label_id)
            await context.api.set_labels(wxid=member_wxid, labels=merged_labels, wxpid=wxpid)
            friend["labels"] = ",".join(merged_labels)
            room_applied += 1
            applied_count += 1

            if delay_ms > 0:
                await sleep(delay_ms)

        skipped_count += room_skipped
        room_report = {
            "roomid": resolved_room["roomid"],
            "room_name": resolved_room["nickname"],
            "label": entry["label"],
            "label_id": label_id,
            "member_count": member_count,
            "applied_count": room_applied,
            "skipped_count": room_skipped,
            "wxpid": wxpid,
        }
        reports.append(room_report)
        context.logger.info("标签分类插件规则处理完成", room_report)

    report = {
        "reason": reason,
        "wxpid": wxpid,
        "processIntervalSeconds": process_interval_seconds,
        "ruleCount": len(entries),
        "appliedCount": applied_count,
        "skippedCount": skipped_count,
        "rooms": reports,
    }
    context.state.namespace("classify_labels").set("last_report", report)
    context.logger.info("好友标签分类已完成", report)
    return report


async def execute(context):
    report = await run_label_classification(context, "manual-execute")
    if report.get("error") == "missing-wxpid":
        return {"handled": False, "detail": "请先选择微信进程", "data": report}
    if not report["rooms"]:
        return {"handled": False, "detail": "没有可执行的标签配置规则", "data": report}
    detail = f"已遍历 {len(report['rooms'])} 个群聊，成功为 {report['appliedCount']} 位好友设置标签"
    context.logger.info(detail, report)
    return {
        "handled": True,
        "detail": detail,
        "data": report,
    }
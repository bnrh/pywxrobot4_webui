from ._plugin_sdk import filter_room_entries, normalize_text, sleep, to_string_list, unique_strings


name = "classify_labels"
description = "按配置将群成员归类到指定好友标签，适合批量标签整理"
category = "functional"
message_dependent = False
scope_targets = ["rooms"]
config_schema = [
    {"key": "wxpid", "label": "默认微信进程ID", "type": "number", "full_width": False, "description": "不填写时使用主 API 的默认微信进程。"},
    {"key": "delay_ms", "label": "处理间隔毫秒", "type": "number", "default": 100, "min": 0, "max": 10000, "step": 10, "full_width": False},
    {"key": "dry_run", "label": "仅预演不写入", "type": "checkbox", "default": False, "full_width": False},
    {"key": "create_missing_labels", "label": "自动创建缺失标签", "type": "checkbox", "default": True, "full_width": False},
    {"key": "run_on_startup", "label": "启动时执行", "type": "checkbox", "default": True, "full_width": False},
    {"key": "run_on_reload", "label": "热重载时执行", "type": "checkbox", "default": True, "full_width": False},
    {"key": "room_labels", "label": "群标签规则", "type": "object-list", "default": [], "meaningful_keys": ["label", "roomid", "room_name"], "description": "为目标群配置要同步到群成员好友标签上的标签名。", "columns": [{"key": "roomid", "label": "群ID", "type": "text", "placeholder": "123456@chatroom"}, {"key": "room_name", "label": "群名称", "type": "text", "placeholder": "可选，用于按名称匹配"}, {"key": "label", "label": "标签名", "type": "text", "placeholder": "例如 视频号群"}, {"key": "wxpid", "label": "微信进程ID", "type": "number", "placeholder": "可选"}]},
]


def normalize_room_label_entries(config):
    room_labels = config.get("room_labels")
    if isinstance(room_labels, list):
        entries = [
            {"roomid": normalize_text(item.get("roomid") or item.get("wxid")), "room_name": normalize_text(item.get("room_name") or item.get("nickname") or item.get("name")), "label": normalize_text(item.get("label") or item.get("label_name")), "wxpid": item.get("wxpid")}
            for item in room_labels if isinstance(item, dict)
            if normalize_text(item.get("label") or item.get("label_name")) and (normalize_text(item.get("roomid") or item.get("wxid")) or normalize_text(item.get("room_name") or item.get("nickname") or item.get("name")))
        ]
        return filter_room_entries(entries, config)
    if isinstance(room_labels, dict):
        entries = [{"roomid": normalize_text(roomid), "label": normalize_text(label)} for roomid, label in room_labels.items() if normalize_text(roomid) and normalize_text(label)]
        return filter_room_entries(entries, config)
    return filter_room_entries([], config)


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


async def ensure_label_id(context, label_name, wxpid, create_missing=True):
    labels = await context.api.get_labels(wxpid=wxpid)
    label_id = labels.get(label_name) if isinstance(labels, dict) else None
    if not label_id and create_missing:
        await context.api.add_label(label_name=label_name, wxpid=wxpid)
        labels = await context.api.get_labels(wxpid=wxpid)
        label_id = labels.get(label_name) if isinstance(labels, dict) else None
    return normalize_text(label_id)


def merge_labels(existing_labels, next_label_id):
    return unique_strings([*to_string_list(existing_labels), next_label_id])


async def resolve_self_wxid(context, wxpid):
    users = await context.api.get_logged_in_users()
    for item in users if isinstance(users, list) else []:
        try:
            if int(item.get("wxpid") or item.get("pid") or -1) == int(wxpid):
                return normalize_text(item.get("wxid"))
        except (TypeError, ValueError):
            continue
    return ""


async def run_label_classification(context, reason):
    entries = normalize_room_label_entries(context.config)
    if not entries:
        return {"appliedCount": 0, "skippedCount": 0, "rooms": []}

    default_wxpid = context.config.get("wxpid")
    delay_ms = max(0, int(float(context.config.get("delay_ms", 100) or 0)))
    dry_run = bool(context.config.get("dry_run"))
    room_lookup_cache = {}
    friend_lookup_cache = {}
    self_wxid_cache = {}
    reports = []
    applied_count = 0
    skipped_count = 0

    for entry in entries:
        wxpid = entry.get("wxpid") if entry.get("wxpid") is not None else default_wxpid
        if wxpid not in room_lookup_cache:
            room_lookup_cache[wxpid] = await build_room_lookup(context, wxpid)
        if wxpid not in friend_lookup_cache:
            friends = await context.api.get_user_list(wxpid)
            friend_lookup_cache[wxpid] = {normalize_text(friend.get("wxid")): friend for friend in friends if isinstance(friend, dict)}
        if wxpid not in self_wxid_cache:
            self_wxid_cache[wxpid] = await resolve_self_wxid(context, wxpid)

        room_lookup = room_lookup_cache[wxpid]
        resolved_room = (entry.get("roomid") and room_lookup["by_id"].get(entry["roomid"])) or (entry.get("room_name") and room_lookup["by_name"].get(entry["room_name"]))
        if not resolved_room:
            skipped_count += 1
            context.logger.warning("标签分类插件未找到目标群聊", {"reason": reason, "roomid": entry.get("roomid"), "room_name": entry.get("room_name"), "label": entry.get("label"), "wxpid": wxpid})
            continue

        label_id = await ensure_label_id(context, entry["label"], wxpid, create_missing=context.config.get("create_missing_labels") is not False)
        if not label_id:
            skipped_count += 1
            context.logger.warning("标签分类插件未找到或创建标签失败", {"reason": reason, "roomid": resolved_room["roomid"], "label": entry["label"], "wxpid": wxpid})
            continue

        members = await context.api.get_room_members(resolved_room["roomid"], wxpid)
        friends_by_wxid = friend_lookup_cache[wxpid]
        self_wxid = self_wxid_cache[wxpid]
        room_applied = 0
        room_skipped = 0
        for member in members if isinstance(members, list) else []:
            member_wxid = normalize_text(member.get("username") or member.get("wxid"))
            if not member_wxid or member_wxid == self_wxid:
                room_skipped += 1
                continue
            friend = friends_by_wxid.get(member_wxid)
            if not friend:
                room_skipped += 1
                continue
            merged_labels = merge_labels(friend.get("labels"), label_id)
            if label_id not in merged_labels or label_id in to_string_list(friend.get("labels")):
                room_skipped += 1
                continue
            if not dry_run:
                await context.api.set_labels(wxid=member_wxid, labels=merged_labels, wxpid=wxpid)
                friend["labels"] = ",".join(merged_labels)
            room_applied += 1
            applied_count += 1
            if delay_ms > 0:
                await sleep(delay_ms)

        skipped_count += room_skipped
        reports.append({"roomid": resolved_room["roomid"], "room_name": resolved_room["nickname"], "label": entry["label"], "label_id": label_id, "applied_count": room_applied, "skipped_count": room_skipped, "dry_run": dry_run, "wxpid": wxpid})

    context.state.namespace("classify_labels").set("last_report", {"reason": reason, "dry_run": dry_run, "applied_count": applied_count, "skipped_count": skipped_count, "rooms": reports})
    return {"appliedCount": applied_count, "skippedCount": skipped_count, "rooms": reports, "dryRun": dry_run}


async def startup(context):
    if context.config.get("run_on_startup") is False:
        return
    report = await run_label_classification(context, "startup")
    if report["appliedCount"] or report["rooms"]:
        context.logger.info("好友标签分类已完成", report)


async def on_hot_reload(hot_reload, context):
    if hot_reload.get("changed") and context.config.get("run_on_reload") is not False:
        report = await run_label_classification(context, "hot-reload")
        if report["appliedCount"] or report["rooms"]:
            context.logger.info("好友标签分类已完成", report)


async def execute(context):
    report = await run_label_classification(context, "manual-execute")
    if report["appliedCount"] or report["rooms"]:
        context.logger.info("好友标签分类已完成", report)
        return {"handled": True, "detail": f"已完成 {len(report['rooms'])} 个群聊的好友标签分类", "data": report}
    return {"handled": False, "detail": "没有可执行的标签分类规则", "data": report}

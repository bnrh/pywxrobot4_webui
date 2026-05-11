from datetime import datetime

from ._plugin_sdk import sleep


name = "watch_wechat_processes"
description = "周期巡检微信进程变化，检测到新增或减少时自动重新 hook"
category = "functional"
message_dependent = False
tick_interval_field = "interval_seconds"
tick_interval_seconds = 5
config_schema = [
    {
        "key": "interval_seconds",
        "label": "巡检间隔秒数",
        "type": "number",
        "default": 5,
        "min": 1,
        "max": 3600,
        "step": 1,
        "full_width": False,
        "description": "每隔多少秒检查一次微信进程变化。",
    },
    {
        "key": "post_hook_delay_seconds",
        "label": "重新 hook 后等待秒数",
        "type": "number",
        "default": 2,
        "min": 0,
        "max": 60,
        "step": 0.5,
        "full_width": False,
        "description": "调用 /hook 后等待多久再刷新用户快照。",
    },
]


def normalize_snapshot(wxpids_payload):
    wxpids = wxpids_payload.get("wxpids") if isinstance(wxpids_payload, dict) else wxpids_payload
    seen = set()
    items = []
    for item in wxpids if isinstance(wxpids, list) else []:
        try:
            wxpid = int(item)
        except (TypeError, ValueError):
            continue
        if wxpid in seen:
            continue
        seen.add(wxpid)
        items.append({"wxpid": wxpid})
    return sorted(items, key=lambda item: item["wxpid"])


def build_snapshot_diff(previous_snapshot, current_snapshot):
    previous_map = {str(item.get("wxpid") or item.get("pid") or item.get("wxid") or ""): item for item in previous_snapshot}
    current_map = {str(item.get("wxpid") or item.get("pid") or item.get("wxid") or ""): item for item in current_snapshot}
    added = []
    removed = []
    changed = []

    for key, item in current_map.items():
        if key not in previous_map:
            added.append(item)
            continue
        if previous_map[key] != item:
            changed.append({"before": previous_map[key], "after": item})

    for key, item in previous_map.items():
        if key not in current_map:
            removed.append(item)

    return {"added": added, "removed": removed, "changed": changed}


async def capture_current_snapshot(context):
    wxpids = await context.api.get_wx_pids()
    return normalize_snapshot(wxpids)


async def startup(context):
    snapshot = await capture_current_snapshot(context)
    context.state.namespace("watch_wechat_processes").set("user_snapshot", snapshot)
    context.logger.info("已初始化微信进程巡检快照", {"process_count": len(snapshot)})


async def tick(context):
    state = context.state.namespace("watch_wechat_processes")
    previous_snapshot = state.get("user_snapshot", [])
    current_snapshot = await capture_current_snapshot(context)

    if not isinstance(previous_snapshot, list) or not previous_snapshot:
        state.set("user_snapshot", current_snapshot)
        return {"handled": False, "detail": ""}

    if previous_snapshot == current_snapshot:
        return {"handled": False, "detail": ""}

    diff = build_snapshot_diff(previous_snapshot, current_snapshot)
    context.logger.warn("检测到微信进程变化，准备重新 hook", diff)

    await context.api.hook()
    wait_seconds = max(0.0, float(context.config.get("post_hook_delay_seconds", 2) or 0))
    if wait_seconds > 0:
        await sleep(wait_seconds * 1000)
    refreshed_snapshot = await capture_current_snapshot(context)
    state.set("user_snapshot", refreshed_snapshot)
    state.set(
        "last_hook_result",
        {
            "triggered_at": datetime.now().astimezone().isoformat(),
            "before_count": len(previous_snapshot),
            "detected_count": len(current_snapshot),
            "refreshed_count": len(refreshed_snapshot),
            "diff": diff,
        },
    )
    context.logger.info(
        "微信进程变化已处理并完成重新 hook",
        {
            "before_count": len(previous_snapshot),
            "detected_count": len(current_snapshot),
            "refreshed_count": len(refreshed_snapshot),
        },
    )
    return {
        "handled": True,
        "detail": f"检测到微信进程变化，已重新 hook 并刷新 {len(refreshed_snapshot)} 个用户进程",
        "data": {
            "before_count": len(previous_snapshot),
            "detected_count": len(current_snapshot),
            "refreshed_count": len(refreshed_snapshot),
            "diff": diff,
        },
    }
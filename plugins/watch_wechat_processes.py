from datetime import datetime

from ._plugin_sdk import sleep


name = "watch_wechat_processes"
description = "周期巡检微信进程与登录账号缓存变化，检测到异常时自动重新 hook"
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
        "description": "调用 /hook 后等待多久再刷新进程与登录账号快照。",
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


def normalize_account_snapshot(accounts_payload):
    seen = set()
    items = []
    for item in accounts_payload if isinstance(accounts_payload, list) else []:
        if not isinstance(item, dict):
            continue
        wxid = str(item.get("wxid") or "").strip()
        wxh = str(item.get("wxh") or item.get("alias") or "").strip()
        nickname = str(item.get("nickname") or "").strip()
        display_name = str(item.get("display_name") or nickname or wxh or wxid or "未命名账号").strip()
        try:
            wxpid = int(item.get("wxpid") if item.get("wxpid") not in (None, "") else item.get("pid"))
        except (TypeError, ValueError):
            wxpid = None
        identity = (wxpid, wxid, wxh, nickname, display_name)
        if identity in seen:
            continue
        seen.add(identity)
        items.append(
            {
                "display_name": display_name,
                "nickname": nickname,
                "wxid": wxid,
                "wxh": wxh,
                "wxpid": wxpid,
            }
        )
    return sorted(
        items,
        key=lambda item: (
            item.get("wxpid") is None,
            item.get("wxpid") if item.get("wxpid") is not None else 0,
            item.get("wxid") or "",
            item.get("wxh") or "",
            item.get("nickname") or "",
            item.get("display_name") or "",
        ),
    )


async def capture_current_account_snapshot(context):
    users_payload = await context.api.get_logged_in_users()
    users = users_payload if isinstance(users_payload, list) else []
    return users, normalize_account_snapshot(context.serialize_login_accounts(users))


def get_cached_account_snapshot(context):
    return normalize_account_snapshot(context.get_cached_login_accounts())


async def check_and_refresh_watch_state(context, state, reason):
    previous_process_snapshot = state.get("user_snapshot", [])
    if not isinstance(previous_process_snapshot, list):
        previous_process_snapshot = []

    current_process_snapshot = await capture_current_snapshot(context)
    current_users, current_account_snapshot = await capture_current_account_snapshot(context)
    cached_account_snapshot = get_cached_account_snapshot(context)

    process_changed = bool(previous_process_snapshot) and previous_process_snapshot != current_process_snapshot
    account_cache_changed = cached_account_snapshot != current_account_snapshot

    if not process_changed and not account_cache_changed:
        state.set("user_snapshot", current_process_snapshot)
        state.set("account_snapshot", current_account_snapshot)
        return None

    process_diff = build_snapshot_diff(previous_process_snapshot, current_process_snapshot)
    account_diff = build_snapshot_diff(cached_account_snapshot, current_account_snapshot)
    trigger_reasons = []
    if process_changed:
        trigger_reasons.append("process_changed")
    if account_cache_changed:
        trigger_reasons.append("account_cache_changed")

    context.logger.warn(
        "检测到微信进程或登录账号缓存变化，准备重新 hook",
        {
            "reason": reason,
            "trigger_reasons": trigger_reasons,
            "process_diff": process_diff,
            "account_diff": account_diff,
            "cached_account_count": len(cached_account_snapshot),
            "current_account_count": len(current_account_snapshot),
        },
    )

    await context.api.hook()
    wait_seconds = max(0.0, float(context.config.get("post_hook_delay_seconds", 2) or 0))
    if wait_seconds > 0:
        await sleep(wait_seconds * 1000)

    refreshed_process_snapshot = await capture_current_snapshot(context)
    refreshed_users, refreshed_account_snapshot = await capture_current_account_snapshot(context)
    refreshed_cached_accounts = await context.refresh_cached_login_accounts(refreshed_users)
    refreshed_cached_account_snapshot = normalize_account_snapshot(refreshed_cached_accounts)

    state.set("user_snapshot", refreshed_process_snapshot)
    state.set("account_snapshot", refreshed_account_snapshot)
    state.set(
        "last_hook_result",
        {
            "triggered_at": datetime.now().astimezone().isoformat(),
            "reason": reason,
            "trigger_reasons": trigger_reasons,
            "before_count": len(previous_process_snapshot),
            "detected_count": len(current_process_snapshot),
            "refreshed_count": len(refreshed_process_snapshot),
            "cached_account_count": len(cached_account_snapshot),
            "detected_account_count": len(current_account_snapshot),
            "refreshed_account_count": len(refreshed_account_snapshot),
            "refreshed_cached_account_count": len(refreshed_cached_account_snapshot),
            "diff": process_diff,
            "account_diff": account_diff,
        },
    )
    context.logger.info(
        "微信进程与登录账号缓存变化已处理并完成重新 hook",
        {
            "reason": reason,
            "before_count": len(previous_process_snapshot),
            "detected_count": len(current_process_snapshot),
            "refreshed_count": len(refreshed_process_snapshot),
            "cached_account_count": len(cached_account_snapshot),
            "detected_account_count": len(current_account_snapshot),
            "refreshed_account_count": len(refreshed_account_snapshot),
            "refreshed_cached_account_count": len(refreshed_cached_account_snapshot),
        },
    )
    return {
        "handled": True,
        "detail": f"检测到微信进程或登录账号缓存变化，已重新 hook 并同步 {len(refreshed_cached_account_snapshot)} 个登录账号缓存",
        "data": {
            "reason": reason,
            "trigger_reasons": trigger_reasons,
            "before_count": len(previous_process_snapshot),
            "detected_count": len(current_process_snapshot),
            "refreshed_count": len(refreshed_process_snapshot),
            "cached_account_count": len(cached_account_snapshot),
            "detected_account_count": len(current_account_snapshot),
            "refreshed_account_count": len(refreshed_account_snapshot),
            "refreshed_cached_account_count": len(refreshed_cached_account_snapshot),
            "diff": process_diff,
            "account_diff": account_diff,
        },
    }


async def startup(context):
    state = context.state.namespace("watch_wechat_processes")
    result = await check_and_refresh_watch_state(context, state, reason="startup")
    if result is not None:
        return

    process_snapshot = state.get("user_snapshot", [])
    account_snapshot = state.get("account_snapshot", [])
    context.logger.info(
        "已初始化微信进程巡检快照",
        {
            "process_count": len(process_snapshot) if isinstance(process_snapshot, list) else 0,
            "account_count": len(account_snapshot) if isinstance(account_snapshot, list) else 0,
        },
    )


async def execute(context):
    state = context.state.namespace("watch_wechat_processes")
    result = await check_and_refresh_watch_state(context, state, reason="manual_execute")
    if result is not None:
        return result

    process_snapshot = state.get("user_snapshot", [])
    account_snapshot = state.get("account_snapshot", [])
    return {
        "handled": True,
        "detail": f"巡检完成，当前 {len(process_snapshot) if isinstance(process_snapshot, list) else 0} 个微信进程、{len(account_snapshot) if isinstance(account_snapshot, list) else 0} 个登录账号，未发现需要重新 hook 的变化",
        "data": {
            "process_count": len(process_snapshot) if isinstance(process_snapshot, list) else 0,
            "account_count": len(account_snapshot) if isinstance(account_snapshot, list) else 0,
        },
    }


async def tick(context):
    state = context.state.namespace("watch_wechat_processes")
    result = await check_and_refresh_watch_state(context, state, reason="tick")
    if result is None:
        return {"handled": False, "detail": ""}
    return result
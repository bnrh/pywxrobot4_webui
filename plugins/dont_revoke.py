from typing import Any

from ._plugin_sdk import normalize_text, resolve_wxpid_targets


name = "dont_revoke"
description = "手动为指定微信进程开启或关闭防撤回"
category = "functional"
message_dependent = False


config_schema = [
    {
        "key": "wxpid",
        "label": "微信进程",
        "type": "select",
        "options_source": "wxpid_options",
        "full_width": False,
        "description": "默认使用第一个微信进程，也可以选择所有当前登录进程。",
    },
    {
        "key": "revoke",
        "label": "启用防撤回",
        "type": "checkbox",
        "default": True,
        "full_width": False,
        "description": "勾选后点击“执行插件”会开启防撤回；取消勾选后点击“执行插件”会关闭防撤回。",
    },
]


def is_success_ret(value: Any) -> bool:
    return value in (None, "", 0, "0", True)


def extract_api_error(payload: Any) -> str:
    if not isinstance(payload, dict):
        return normalize_text(payload)
    if is_success_ret(payload.get("ret")):
        return ""
    for key in ("error", "errmsg", "err_msg", "message", "msg", "detail"):
        text = normalize_text(payload.get(key))
        if text:
            return text
    return f"ret={payload.get('ret')}"


def resolve_revoke_enabled(config: Any) -> bool:
    if not isinstance(config, dict):
        return True
    return bool(config.get("revoke", True))


def build_action_text(revoke: bool) -> str:
    return "开启" if revoke else "关闭"


def build_success_detail(revoke: bool, success_count: int, failed_count: int) -> str:
    action_text = build_action_text(revoke)
    detail = f"已为 {success_count} 个微信进程{action_text}防撤回"
    if failed_count > 0:
        detail = f"{detail}，另有 {failed_count} 个微信进程操作失败"
    return detail


async def apply_dont_revoke(context: Any, reason: str) -> dict[str, Any]:
    wxpid_selection = context.config.get("wxpid") if isinstance(context.config, dict) else None
    target_wxpids = await resolve_wxpid_targets(context.api, wxpid_selection)
    revoke_enabled = resolve_revoke_enabled(context.config)
    report = {
        "reason": reason,
        "wxpid_selection": wxpid_selection,
        "target_wxpids": target_wxpids,
        "revoke": revoke_enabled,
        "action": build_action_text(revoke_enabled),
        "success_count": 0,
        "failed_count": 0,
        "operations": [],
    }
    state = context.state.namespace("dont_revoke")

    if not target_wxpids:
        report["error"] = "missing-live-wxpids"
        context.logger.warning("防撤回操作跳过，当前没有可用的微信进程", report)
        state.set("last_report", report)
        return report

    context.logger.info("开始执行防撤回操作", report)

    for wxpid in target_wxpids:
        try:
            payload = await context.api.dont_revoke(revoke=revoke_enabled, wxpid=wxpid)
        except Exception as exc:
            failure = {
                "wxpid": wxpid,
                "action": report["action"],
                "status": "failed",
                "error": str(exc),
            }
            report["operations"].append(failure)
            report["failed_count"] += 1
            context.logger.warning("防撤回操作失败", failure)
            continue

        error_text = extract_api_error(payload)
        if error_text:
            failure = {
                "wxpid": wxpid,
                "action": report["action"],
                "status": "failed",
                "error": error_text,
                "response": payload,
            }
            report["operations"].append(failure)
            report["failed_count"] += 1
            context.logger.warning("防撤回操作失败", failure)
            continue

        success = {
            "wxpid": wxpid,
            "action": report["action"],
            "status": "enabled" if revoke_enabled else "disabled",
            "response": payload,
        }
        report["operations"].append(success)
        report["success_count"] += 1
        context.logger.info("防撤回操作成功", success)

    context.logger.info("防撤回操作结束", report)
    state.set("last_report", report)
    return report


async def execute(context: Any) -> dict[str, Any]:
    report = await apply_dont_revoke(context, "manual-execute")
    if report.get("error") == "missing-live-wxpids":
        return {
            "handled": False,
            "detail": "当前没有已登录的微信进程",
            "data": report,
        }

    if report.get("success_count"):
        return {
            "handled": True,
            "detail": build_success_detail(bool(report.get("revoke")), int(report.get("success_count") or 0), int(report.get("failed_count") or 0)),
            "data": report,
        }

    action_text = build_action_text(bool(report.get("revoke")))
    return {
        "handled": False,
        "detail": f"没有成功{action_text}任何微信进程的防撤回",
        "data": report,
    }
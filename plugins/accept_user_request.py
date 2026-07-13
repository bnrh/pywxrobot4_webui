import re
from time import time

from ._plugin_sdk import MESSAGE_TYPES, get_message_type, normalize_text, parse_xml_attributes, random_between, sleep, unique_strings, is_truthy


SNS_PERMISSION_MAP = {
    "默认": 0,
    "不让他看": 1,
    "不看他": 2,
    "不让他看|不看他": 3,
    "仅聊天": 8,
}

ACCEPT_DELAY_MIN_SECONDS = 3
ACCEPT_DELAY_MAX_SECONDS = 8
GREETING_DELAY_MIN_SECONDS = 2
GREETING_DELAY_MAX_SECONDS = 5
DISTURB_DELAY_SECONDS = 5
PENDING_REQUEST_TTL_MS = 5 * 60 * 1000

NOTICE_NAME_PATTERN = re.compile(r"你已添加了(.+?)[,，]现在可以开始聊天了。?")


name = "accept_user_request"
description = "自动通过好友请求，并支持按关键词打标签、发送欢迎语和免打扰设置"
event_filters = ["friend_request", "notice"]
config_schema = [
    {"key": "classify_label_bool", "label": "是否进行标签分类", "type": "checkbox", "default": False, "full_width": False, "description": "按下方关键词规则，在同意好友请求后为好友设置对应标签。"},
    {"key": "disturb_bool", "label": "是否在同意好友后开启好友消息免打扰", "type": "checkbox", "default": False, "full_width": False},
    {"key": "sns_permission", "label": "同意好友请求后设置的朋友圈权限", "type": "select", "default": "默认", "full_width": False, "options": [{"label": "默认", "value": "默认"}, {"label": "不让他看", "value": "不让他看"}, {"label": "不看他", "value": "不看他"}, {"label": "不让他看且不看他", "value": "不让他看|不看他"}, {"label": "仅聊天", "value": "仅聊天"}]},
    {"key": "send_greetings_bool", "label": "是否发送欢迎语", "type": "checkbox", "default": False, "full_width": False, "description": "仅当好友请求被自动同意且未命中任何关键词规则时，才会在好友通过后发送欢迎语；命中关键词规则时不会发送。"},
    {"key": "greetings", "label": "欢迎语内容", "type": "textarea", "default": "", "rows": 4, "description": "在好友通过完成后自动发送的文本内容。"},
    {"key": "keywords_only_bool", "label": "是否仅同意触发关键词的好友", "type": "checkbox", "default": False, "full_width": False, "description": "启用后，只有命中下方关键词规则的好友请求才会被自动同意。"},
    {
        "key": "keyword_rules",
        "label": "关键词规则",
        "type": "object-list",
        "display_mode": "table",
        "default": [],
        "meaningful_keys": ["keyword", "label"],
        "empty_text": "暂无已保存规则，点击“新增”填写后，再点当前行的“保存”。",
        "description": "每条规则包含关键词、对应标签，以及是否要求全匹配。半匹配时会按包含关系判断。",
        "columns": [
            {"key": "keyword", "label": "关键词", "type": "text", "placeholder": "例如 视频号"},
            {"key": "label", "label": "标签", "type": "select", "options_source": "label_options", "empty_option_label": "请选择标签", "required": True, "required_message": "标签不能为空"},
            {"key": "full_match", "label": "是否全匹配", "type": "checkbox"},
        ],
    },
]




def resolve_sns_permission(config):
    permission = config.get("sns_permission")
    if isinstance(permission, int):
        return permission
    return SNS_PERMISSION_MAP.get(str(permission or "默认").strip(), 0)


def now_milliseconds():
    return int(time() * 1000)


def build_event_debug_payload(event, content_override=None):
    content = normalize_text(
        content_override
        if content_override is not None
        else (event.normalized_content or getattr(event, "content", ""))
    )
    if len(content) > 120:
        content = f"{content[:117]}..."
    return {
        "msgid": normalize_text(getattr(event, "normalized_msgid", "") or getattr(event, "msgid", "")),
        "wxpid": event.normalized_wxpid,
        "local_type": getattr(event, "normalized_local_type", None),
        "msg_type": getattr(event, "normalized_msg_type", None),
        "sender": normalize_text(getattr(event, "sender", "")),
        "sender_wxid": normalize_text(getattr(event, "sender_wxid", "") or ""),
        "room_sender": normalize_text(getattr(event, "room_sender", "")),
        "recipient": normalize_text(getattr(event, "recipient", "")),
        "conversation_wxid": normalize_text(getattr(event, "conversation_wxid", "") or ""),
        "content_preview": content,
    }


def normalize_pending_request(value):
    payload = value if isinstance(value, dict) else {}
    try:
        received_at = int(payload.get("received_at") or 0)
    except (TypeError, ValueError):
        received_at = 0
    try:
        agreed_at = int(payload.get("agreed_at") or 0)
    except (TypeError, ValueError):
        agreed_at = 0
    return {
        "friend_wxid": normalize_text(payload.get("friend_wxid")),
        "nickname": normalize_text(payload.get("nickname")),
        "alias": normalize_text(payload.get("alias")),
        "verification": normalize_text(payload.get("verification")),
        "v4": normalize_text(payload.get("v4")),
        "msgid": normalize_text(payload.get("msgid")),
        "stage": normalize_text(payload.get("stage") or "waiting-approve"),
        "send_greetings": bool(payload.get("send_greetings")),
        "received_at": received_at,
        "agreed_at": agreed_at,
        "matched_keywords": unique_strings(payload.get("matched_keywords")),
        "labels": normalize_text(payload.get("labels")),
    }


def build_pending_request_summary(friend_wxid, pending, now_ms=None):
    normalized_pending = normalize_pending_request(pending)
    age_ms = None
    if now_ms is not None and normalized_pending["received_at"] > 0:
        age_ms = max(0, now_ms - normalized_pending["received_at"])
    return {
        "friend_wxid": normalize_text(friend_wxid) or normalized_pending["friend_wxid"],
        "nickname": normalized_pending["nickname"],
        "alias": normalized_pending["alias"],
        "verification": normalized_pending["verification"],
        "msgid": normalized_pending["msgid"],
        "stage": normalized_pending["stage"],
        "received_at": normalized_pending["received_at"],
        "agreed_at": normalized_pending["agreed_at"],
        "age_ms": age_ms,
        "matched_keywords": normalized_pending["matched_keywords"],
        "labels": normalized_pending["labels"],
    }


def cleanup_stale_pending_requests(pending_requests, logger, now_ms):
    stale_items = []
    for pending_key, pending_value in pending_requests.entries():
        pending = normalize_pending_request(pending_value)
        age_ms = max(0, now_ms - pending["received_at"]) if pending["received_at"] > 0 else PENDING_REQUEST_TTL_MS + 1
        if age_ms <= PENDING_REQUEST_TTL_MS:
            continue
        pending_requests.delete(pending_key)
        stale_items.append(build_pending_request_summary(pending_key, pending, now_ms))
    if stale_items:
        logger.warning("清理过期的好友请求挂起记录", {"count": len(stale_items), "items": stale_items[:5]})


def get_pending_replacement_reason(existing_pending, now_ms, current_v4, current_verification, current_msgid):
    age_ms = max(0, now_ms - existing_pending["received_at"]) if existing_pending["received_at"] > 0 else PENDING_REQUEST_TTL_MS + 1
    if age_ms > PENDING_REQUEST_TTL_MS:
        return f"挂起记录已超时({age_ms}ms)"
    if current_msgid and existing_pending["msgid"] and existing_pending["msgid"] != current_msgid:
        return "消息 ID 已变化"
    if current_v4 and existing_pending["v4"] and existing_pending["v4"] != current_v4:
        return "好友请求 ticket 已变化"
    if current_verification and existing_pending["verification"] and existing_pending["verification"] != current_verification:
        return "好友请求验证语已变化"
    return ""


def extract_notice_display_name(content):
    match = NOTICE_NAME_PATTERN.search(str(content or ""))
    if not match:
        return ""
    return normalize_text(match.group(1).strip('"\'“”‘’ '))


def find_pending_request_for_notice(event, content, pending_requests):
    sender_candidates = unique_strings(
        [
            getattr(event, "sender", ""),
            event.sender_wxid,
            getattr(event, "room_sender", ""),
            event.conversation_wxid,
        ]
    )
    notice_display_name = extract_notice_display_name(content)
    pending_items = [
        (pending_key, normalize_pending_request(pending_value))
        for pending_key, pending_value in pending_requests.entries()
    ]
    if not pending_items:
        return {"key": "", "pending": None, "match_reason": "", "sender_candidates": sender_candidates, "notice_display_name": notice_display_name}

    sender_candidate_set = set(sender_candidates)
    for pending_key, pending in pending_items:
        identifiers = set(
            unique_strings(
                [
                    pending_key,
                    pending["friend_wxid"],
                    pending["alias"],
                    pending["nickname"],
                ]
            )
        )
        if sender_candidate_set & identifiers:
            return {"key": pending_key, "pending": pending, "match_reason": "sender-or-profile", "sender_candidates": sender_candidates, "notice_display_name": notice_display_name}
        if notice_display_name and notice_display_name in identifiers:
            return {"key": pending_key, "pending": pending, "match_reason": "notice-display-name", "sender_candidates": sender_candidates, "notice_display_name": notice_display_name}

    if len(pending_items) == 1:
        pending_key, pending = pending_items[0]
        return {"key": pending_key, "pending": pending, "match_reason": "single-pending-fallback", "sender_candidates": sender_candidates, "notice_display_name": notice_display_name}

    return {"key": "", "pending": None, "match_reason": "", "sender_candidates": sender_candidates, "notice_display_name": notice_display_name}


def normalize_keyword_rules(config):
    raw_rules = config.get("keyword_rules") if isinstance(config, dict) else []
    if not isinstance(raw_rules, list):
        return []

    rules = []
    for item in raw_rules:
        if not isinstance(item, dict):
            continue
        keyword = normalize_text(item.get("keyword"))
        label = normalize_text(item.get("label"))
        if not keyword and not label:
            continue
        rules.append(
            {
                "keyword": keyword,
                "label": label,
                "full_match": is_truthy(item.get("full_match")),
            }
        )
    return rules


def match_keyword_rule(content, rule):
    keyword = normalize_text(rule.get("keyword"))
    if not keyword:
        return False
    normalized_content = normalize_text(content)
    if is_truthy(rule.get("full_match")):
        return normalized_content == keyword
    return keyword in normalized_content


def evaluate_keyword_rules(content, config):
    rules = normalize_keyword_rules(config)
    matched_rules = [rule for rule in rules if match_keyword_rule(content, rule)]
    return {
        "rules": rules,
        "matched_rules": matched_rules,
        "matched_keywords": unique_strings([rule.get("keyword") for rule in matched_rules]),
        "matched_label_names": unique_strings([rule.get("label") for rule in matched_rules if normalize_text(rule.get("label"))]),
    }


async def resolve_label_ids(context, wxpid, label_names):
    desired_labels = unique_strings(label_names)
    if not desired_labels:
        return {"labels": "", "missing_labels": []}

    label_map = await context.api.get_labels(wxpid=wxpid)
    label_ids = []
    missing_labels = []
    for label_name in desired_labels:
        label_id = label_map.get(label_name) if isinstance(label_map, dict) else None
        if label_id in (None, ""):
            missing_labels.append(label_name)
            continue
        label_ids.append(str(label_id))
    return {"labels": ",".join(unique_strings(label_ids)), "missing_labels": missing_labels}


async def handle_message(event, context):
    type_code = get_message_type(event)
    pending_requests = context.state.namespace("pending_requests")
    now_ms = now_milliseconds()
    cleanup_stale_pending_requests(pending_requests, context.logger, now_ms)

    if type_code == MESSAGE_TYPES.ADDFRIEND:
        payload = parse_xml_attributes(event.normalized_content or getattr(event, "content", ""))
        friend_wxid = normalize_text(payload.get("fromusername"))
        v3 = normalize_text(payload.get("encryptusername"))
        v4 = normalize_text(payload.get("ticket"))
        nickname = normalize_text(payload.get("fromnickname"))
        alias = normalize_text(payload.get("alias"))
        verification = normalize_text(payload.get("content"))
        add_type = int(payload.get("scene") or 1)
        context.logger.info(
            "收到好友请求消息",
            {
                **build_event_debug_payload(event),
                "friend_wxid": friend_wxid,
                "nickname": nickname,
                "alias": alias,
                "verification": verification,
                "scene": add_type,
            },
        )
        if not friend_wxid or not v3 or not v4:
            context.logger.warning("好友请求缺少必要字段，已跳过处理", {**build_event_debug_payload(event), "friend_wxid": friend_wxid, "v3": bool(v3), "v4": bool(v4)})
            return {"handled": False, "detail": "好友请求缺少必要字段"}

        existing_pending = normalize_pending_request(pending_requests.get(friend_wxid))
        if existing_pending["friend_wxid"]:
            replace_reason = get_pending_replacement_reason(existing_pending, now_ms, v4, verification, event.normalized_msgid)
            if replace_reason:
                pending_requests.delete(friend_wxid)
                context.logger.warning(
                    "检测到残留的好友请求挂起记录，已覆盖为新的好友请求",
                    {"reason": replace_reason, "existing": build_pending_request_summary(friend_wxid, existing_pending, now_ms), "incoming_verification": verification, "incoming_msgid": event.normalized_msgid, "incoming_alias": alias},
                )
            else:
                context.logger.warning(
                    "好友请求仍在处理中，跳过重复请求",
                    {"current": {"friend_wxid": friend_wxid, "nickname": nickname, "alias": alias, "verification": verification, "msgid": event.normalized_msgid}, "pending": build_pending_request_summary(friend_wxid, existing_pending, now_ms)},
                )
                return {"handled": False, "detail": f"好友请求仍在处理中: {friend_wxid}"}

        keyword_result = evaluate_keyword_rules(verification, context.config)
        context.logger.info("好友请求关键词匹配结果", {"friend_wxid": friend_wxid, "verification": verification, "matched_keywords": keyword_result["matched_keywords"], "matched_label_names": keyword_result["matched_label_names"], "keywords_only": is_truthy(context.config.get("keywords_only_bool"))})
        if is_truthy(context.config.get("keywords_only_bool")) and not keyword_result["matched_rules"]:
            return {"handled": False, "detail": ""}

        label_result = {"labels": "", "missing_labels": []}
        if is_truthy(context.config.get("classify_label_bool")):
            label_result = await resolve_label_ids(context, event.normalized_wxpid, keyword_result["matched_label_names"])
            if label_result["missing_labels"]:
                context.logger.warning("好友请求命中了标签规则，但部分标签不存在", {"friend_wxid": friend_wxid, "missing_labels": label_result["missing_labels"], "matched_keywords": keyword_result["matched_keywords"]})

        send_greetings = not keyword_result["matched_rules"]
        pending_record = {
            "friend_wxid": friend_wxid,
            "nickname": nickname,
            "alias": alias,
            "send_greetings": send_greetings,
            "received_at": now_ms,
            "verification": verification,
            "matched_keywords": keyword_result["matched_keywords"],
            "labels": label_result["labels"],
            "v4": v4,
            "msgid": event.normalized_msgid,
            "stage": "waiting-approve",
        }
        pending_requests.set(friend_wxid, pending_record)
        context.logger.debug("好友请求挂起状态已写入", build_pending_request_summary(friend_wxid, pending_record, now_ms))
        context.logger.debug("欢迎语挂起策略已确定", {"friend_wxid": friend_wxid, "matched_keywords": keyword_result["matched_keywords"], "matched_rule_count": len(keyword_result["matched_rules"]), "send_greetings": send_greetings})

        accept_delay_seconds = random_between(ACCEPT_DELAY_MIN_SECONDS, ACCEPT_DELAY_MAX_SECONDS)
        context.logger.info("好友请求已写入挂起状态，准备调用同意接口", {"friend_wxid": friend_wxid, "nickname": nickname, "alias": alias, "verification": verification, "matched_keywords": keyword_result["matched_keywords"], "labels": label_result["labels"], "send_greetings": send_greetings, "accept_delay_seconds": accept_delay_seconds})

        try:
            await sleep(accept_delay_seconds * 1000)
            context.logger.info("开始调用同意好友请求接口", {"friend_wxid": friend_wxid, "nickname": nickname, "alias": alias, "labels": label_result["labels"], "sns_permission": resolve_sns_permission(context.config), "wxpid": event.normalized_wxpid})
            await context.api.agree_friend_request(
                wxid=v3,
                v4=v4,
                remarks="",
                labels=label_result["labels"],
                sns_permissions=resolve_sns_permission(context.config),
                add_type=add_type,
                wxpid=event.normalized_wxpid,
            )
        except Exception as exc:
            pending_requests.delete(friend_wxid)
            context.logger.error("同意好友请求失败，已清理挂起状态", {"friend_wxid": friend_wxid, "nickname": nickname, "alias": alias, "verification": verification, "matched_keywords": keyword_result["matched_keywords"], "labels": label_result["labels"], "error": str(exc)})
            raise

        pending_record["stage"] = "waiting-notice"
        pending_record["agreed_at"] = now_milliseconds()
        pending_requests.set(friend_wxid, pending_record)
        context.logger.info("已自动同意好友请求，等待好友添加完成通知", {"friend_wxid": friend_wxid, "nickname": nickname, "alias": alias, "verification": verification, "matched_keywords": keyword_result["matched_keywords"], "labels": label_result["labels"], "classify_label": is_truthy(context.config.get("classify_label_bool"))})
        return {"handled": True, "detail": f"已自动同意 {friend_wxid} 的好友请求", "data": {"friend_wxid": friend_wxid, "labels": label_result["labels"], "matched_keywords": keyword_result["matched_keywords"], "send_greetings": send_greetings}}

    if type_code == MESSAGE_TYPES.NOTICE:
        content = normalize_text(event.normalized_content or getattr(event, "content", ""))
        if "现在可以开始聊天了" not in content:
            return {"handled": False, "detail": ""}

        notice_match = find_pending_request_for_notice(event, content, pending_requests)
        pending = notice_match["pending"]
        if not pending:
            return {"handled": False, "detail": ""}

        pending_key = notice_match["key"]
        friend_wxid = pending.get("friend_wxid") or pending_key
        context.logger.debug("好友添加完成通知原始匹配信息", {"match_reason": notice_match["match_reason"], "notice_display_name": notice_match["notice_display_name"], "sender_candidates": notice_match["sender_candidates"]})
        context.logger.info("好友添加完成通知已匹配到挂起记录", {"friend_wxid": friend_wxid, "match_reason": notice_match["match_reason"], "notice_display_name": notice_match["notice_display_name"], "sender_candidates": notice_match["sender_candidates"], "pending": build_pending_request_summary(friend_wxid, pending, now_milliseconds())})
        pending_requests.delete(pending_key)

        greeting_text = str(context.config.get("greetings") or "").strip()
        should_send_greetings = bool(pending.get("send_greetings")) and is_truthy(context.config.get("send_greetings_bool")) and bool(greeting_text)
        context.logger.debug("欢迎语发送条件计算结果", {"friend_wxid": friend_wxid, "send_greetings_config": is_truthy(context.config.get("send_greetings_bool")), "has_greeting_text": bool(greeting_text), "should_send_greetings": should_send_greetings, "pending_send_greetings": bool(pending.get("send_greetings")), "matched_keywords": pending.get("matched_keywords", [])})
        if should_send_greetings:
            greeting_delay_seconds = random_between(GREETING_DELAY_MIN_SECONDS, GREETING_DELAY_MAX_SECONDS)
            context.logger.info("准备发送欢迎语", {"friend_wxid": friend_wxid, "delay_seconds": greeting_delay_seconds, "greeting_preview": greeting_text[:60]})
            await sleep(greeting_delay_seconds * 1000)
            await context.api.send_text(wxid=friend_wxid, content=greeting_text, wxpid=event.normalized_wxpid)
            context.logger.info("欢迎语发送完成", {"friend_wxid": friend_wxid})

        if is_truthy(context.config.get("disturb_bool")):
            context.logger.info("准备开启好友消息免打扰", {"friend_wxid": friend_wxid, "delay_seconds": DISTURB_DELAY_SECONDS})
            await sleep(DISTURB_DELAY_SECONDS * 1000)
            await context.api.receive_notify(wxid=friend_wxid, notify=True, wxpid=event.normalized_wxpid)
            context.logger.info("好友消息免打扰设置完成", {"friend_wxid": friend_wxid})

        sent_greetings = bool(should_send_greetings)
        context.logger.info("好友请求后续动作已完成", {"friend_wxid": friend_wxid, "sent_greetings": sent_greetings, "disturb": is_truthy(context.config.get("disturb_bool")), "matched_keywords": pending.get("matched_keywords", [])})
        return {"handled": True, "detail": f"好友 {friend_wxid} 的后续动作已完成", "data": {"friend_wxid": friend_wxid, "sent_greetings": sent_greetings, "matched_keywords": pending.get("matched_keywords", [])}}

    return {"handled": False, "detail": ""}

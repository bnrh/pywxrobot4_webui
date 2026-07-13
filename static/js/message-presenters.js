/** 消息列表与详情展示辅助函数。 */

import { el, normalizeInlineText, text } from "./dom-utils.js";
import { formatUnixTimestamp } from "./format-utils.js";
import { getMessageTypeLabel, getPayloadValue } from "./message-labels.js";

export function getConversationLabel(message) {
    return normalizeInlineText(
        message.conversation_display_name
        || message.conversation_wxid
        || getPayloadValue(message, "talker", "sender", "wxid", "conversation_id")
        || "未知会话"
    );
}

export function getSenderLabel(message) {
    return normalizeInlineText(
        message.room_sender_display_name
        || message.sender_display_name
        || message.sender_wxid
        || getPayloadValue(message, "room_sender", "from_wxid", "from_user", "sender", "wxid")
        || "未知发送者"
    );
}

export function getMessageTimeLabel(message) {
    const rawValue = getPayloadValue(message, "create_time", "timestamp", "ts");
    if (typeof rawValue === "string" && /[-:]/.test(rawValue)) {
        return rawValue;
    }
    return formatUnixTimestamp(rawValue) || message.received_at || "未知时间";
}

export function getMessageSummary(message) {
    const candidates = [
        message.text_content,
        message.content,
        getPayloadValue(message, "content", "message_content", "msg", "title", "desc", "brief", "description", "s1", "s3", "s4"),
    ];

    for (const candidate of candidates) {
        const content = normalizeInlineText(candidate);
        if (content) {
            return content;
        }
    }

    const typeLabel = getMessageTypeLabel(message);
    if (typeLabel === "图片") {
        return "收到一条图片消息";
    }
    if (typeLabel === "语音") {
        return "收到一条语音消息";
    }
    if (typeLabel === "视频") {
        return "收到一条视频消息";
    }
    if (typeLabel === "表情") {
        return "收到一条表情消息";
    }
    return `收到一条${typeLabel}`;
}

export function getMessageTitle(message) {
    const explicitTitle = normalizeInlineText(message.title_display);
    if (explicitTitle) {
        return explicitTitle;
    }
    const sender = getSenderLabel(message);
    const typeLabel = getMessageTypeLabel(message);
    if (message.is_group_message) {
        return getConversationLabel(message);
    }
    if (sender && sender !== "未知发送者") {
        return sender;
    }
    if (message.msgid) {
        return `${typeLabel} · ${message.msgid}`;
    }
    return `${typeLabel}消息`;
}

export function getAvatarUrl(message) {
    return normalizeInlineText(
        message.avatar_url
        || message.conversation_avatar_url
        || message.sender_avatar_url
    );
}

export function renderAvatar(message) {
    const title = getMessageTitle(message);
    const avatarUrl = getAvatarUrl(message);
    const fallback = (title || "?").slice(0, 1).toUpperCase();
    if (avatarUrl) {
        return el("div", { className: "message-avatar" }, [
            el("img", {
                className: "message-avatar-img",
                src: avatarUrl,
                alt: title,
            }),
        ]);
    }
    return el("div", { className: "message-avatar message-avatar-fallback" }, text(fallback));
}

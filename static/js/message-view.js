/** 消息列表与详情渲染。 */

import {
    badge,
    detailMeta,
    emptyState,
    el,
    formatJson,
    normalizeInlineText,
    replaceChildren,
    text,
} from "./dom-utils.js";
import { formatUnixTimestamp, truncateText } from "./format-utils.js";
import {
    getMessageTypeCode,
    getMessageTypeLabel,
    getPayloadValue,
} from "./message-labels.js";
import {
    getConversationLabel,
    getMessageSummary,
    getMessageTimeLabel,
    getMessageTitle,
    getSenderLabel,
    renderAvatar,
} from "./message-presenters.js";
import { getStatusTone } from "./status-tones.js";

export function resolveSelectedMessageId(messages, selectedMessageId, messageAutoFollow) {
    if (!Array.isArray(messages) || !messages.length) {
        return selectedMessageId;
    }
    if (
        messageAutoFollow
        || !selectedMessageId
        || !messages.some((item) => item.internal_id === selectedMessageId)
    ) {
        return messages[0].internal_id;
    }
    return selectedMessageId;
}

function buildMessageListItem(message, selectedMessageId) {
    const preview = truncateText(getMessageSummary(message), 88);
    const typeLabel = getMessageTypeLabel(message);
    const conversationLabel = getConversationLabel(message);
    const senderLabel = getSenderLabel(message);
    const timeLabel = getMessageTimeLabel(message);
    let subline = timeLabel;
    if (message.is_group_message && senderLabel) {
        subline = `${timeLabel} · ${senderLabel}`;
    } else if (!message.is_group_message && conversationLabel) {
        subline = `${timeLabel} · ${conversationLabel}`;
    }

    return el(
        "button",
        {
            className: `message-item ${message.internal_id === selectedMessageId ? "is-active" : ""}`,
            type: "button",
            dataset: { messageId: String(message.internal_id) },
        },
        [
            renderAvatar(message),
            el("div", { className: "message-main" }, [
                el("div", { className: "message-item-head" }, [
                    el("div", { className: "message-primary" }, [
                        el("h4", { className: "message-title" }, text(getMessageTitle(message))),
                        el("div", { className: "detail-meta message-subline" }, text(subline)),
                    ]),
                    el("div", { className: "badge-row message-badges" }, [
                        badge(message.status, getStatusTone(message.status)),
                        badge(typeLabel),
                    ]),
                ]),
                el("p", { className: "message-copy" }, text(preview)),
            ]),
        ],
    );
}

function buildPluginResults(selected) {
    if (!selected.plugin_results?.length) {
        return [emptyState("插件尚未返回处理结果。")];
    }
    return selected.plugin_results.flatMap((item) => [
        el("div", { className: "badge-row" }, [
            badge(item.plugin, item.handled ? "good" : ""),
            badge(item.handled ? "已处理" : "跳过", item.stop_processing ? "good" : ""),
        ]),
        detailMeta(item.detail || "无额外说明"),
    ]);
}

function buildMessageDetailSections(selected) {
    const selectedConversation = getConversationLabel(selected);
    const selectedSender = getSenderLabel(selected);
    const selectedTypeLabel = getMessageTypeLabel(selected);
    const selectedTextContent = normalizeInlineText(selected.text_content || "");
    const rawPayloadText = formatJson(selected.payload);
    const shouldShowTextContent = getMessageTypeCode(selected) === 1 && Boolean(selectedTextContent);
    const selectedSourceTime = getPayloadValue(selected, "create_time", "timestamp", "ts");
    const sourceTimestamp = typeof selectedSourceTime === "string" && /[-:]/.test(selectedSourceTime)
        ? selectedSourceTime
        : formatUnixTimestamp(selectedSourceTime);

    const sections = [
        el("div", { className: "detail-head" }, [
            el("div", null, [
                el("h4", { className: "detail-title" }, text(getMessageTitle(selected))),
            ]),
            el("div", { className: "badge-row" }, [
                badge(selected.status, getStatusTone(selected.status)),
                badge(selectedTypeLabel),
                badge(selected.is_group_message ? "群聊" : "单聊"),
            ]),
        ]),
        el("div", { className: "detail-section" }, [
            el("h5", { className: "detail-section-title" }, text("消息信息")),
            detailMeta(`消息 ID：${selected.msgid || `内部消息 ${selected.internal_id}`}`),
            detailMeta(`会话：${selectedConversation}`),
            detailMeta(`发送者：${selected.sender_display_name || selectedSender}`),
            selected.is_group_message
                ? detailMeta(`群成员：${selected.room_sender_display_name || selectedSender}`)
                : null,
        ]),
    ];

    if (shouldShowTextContent) {
        sections.push(el("div", { className: "detail-section" }, [
            el("h5", { className: "detail-section-title" }, text("消息内容")),
            el("div", { className: "detail-text" }, text(selectedTextContent)),
        ]));
    }

    sections.push(
        el("div", { className: "detail-section" }, [
            el("h5", { className: "detail-section-title" }, text("处理时间")),
            detailMeta(`接收时间：${selected.received_at || "未知"}`),
            detailMeta(`消息时间：${sourceTimestamp || "上游未提供"}`),
            detailMeta(`完成时间：${selected.processed_at || "处理中"}`),
        ]),
        el("div", { className: "detail-section" }, [
            el("h5", { className: "detail-section-title" }, text("插件结果")),
            el("div", null, buildPluginResults(selected)),
        ]),
        el("div", { className: "detail-section" }, [
            el("div", { className: "detail-section-head" }, [
                el("h5", { className: "detail-section-title" }, text("原始负载")),
                el(
                    "button",
                    {
                        className: "button ghost compact",
                        type: "button",
                        dataset: { action: "copy-message-payload" },
                    },
                    text("复制原始负载"),
                ),
            ]),
            el("pre", { className: "code-block" }, text(rawPayloadText)),
        ]),
    );

    return sections;
}

export function renderMessagesView(elements, viewState) {
    const { messages, messageAutoFollow } = viewState;
    let { selectedMessageId } = viewState;

    if (!messages.length) {
        replaceChildren(elements.messageList, emptyState("还没有收到任何消息。"));
        replaceChildren(elements.messageDetail, emptyState("请选择左侧消息查看详情。"));
        return { selectedMessageId };
    }

    selectedMessageId = resolveSelectedMessageId(messages, selectedMessageId, messageAutoFollow);
    replaceChildren(
        elements.messageList,
        ...messages.map((message) => buildMessageListItem(message, selectedMessageId)),
    );

    const selected = messages.find((message) => message.internal_id === selectedMessageId);
    replaceChildren(elements.messageDetail, ...buildMessageDetailSections(selected));

    return { selectedMessageId };
}

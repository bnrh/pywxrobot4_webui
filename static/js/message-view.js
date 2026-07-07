/** 消息列表与详情渲染。 */

import { escapeHtml, formatJson, normalizeInlineText } from "./dom-utils.js";
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

export function renderMessagesView(elements, viewState) {
    const { messages, messageAutoFollow } = viewState;
    let { selectedMessageId } = viewState;

    if (!messages.length) {
        elements.messageList.innerHTML = '<div class="empty-state">还没有收到任何消息。</div>';
        elements.messageDetail.innerHTML = '<div class="empty-state">请选择左侧消息查看详情。</div>';
        return { selectedMessageId };
    }

    selectedMessageId = resolveSelectedMessageId(messages, selectedMessageId, messageAutoFollow);

    elements.messageList.innerHTML = messages.map((message) => {
        const preview = truncateText(getMessageSummary(message), 88);
        const typeLabel = getMessageTypeLabel(message);
        const conversationLabel = getConversationLabel(message);
        const senderLabel = getSenderLabel(message);
        const timeLabel = getMessageTimeLabel(message);
        const badges = [
            `<span class="badge ${getStatusTone(message.status)}">${escapeHtml(message.status)}</span>`,
            `<span class="badge">${escapeHtml(typeLabel)}</span>`,
        ].join("");

        return `
            <button class="message-item ${message.internal_id === selectedMessageId ? "is-active" : ""}" data-message-id="${message.internal_id}" type="button">
                ${renderAvatar(message)}
                <div class="message-main">
                    <div class="message-item-head">
                        <div class="message-primary">
                            <h4 class="message-title">${escapeHtml(getMessageTitle(message))}</h4>
                            <div class="detail-meta message-subline">${escapeHtml(timeLabel)}${message.is_group_message && senderLabel ? ` · ${escapeHtml(senderLabel)}` : !message.is_group_message && conversationLabel ? ` · ${escapeHtml(conversationLabel)}` : ""}</div>
                        </div>
                        <div class="badge-row message-badges">${badges}</div>
                    </div>
                    <p class="message-copy">${escapeHtml(preview)}</p>
                </div>
            </button>
        `;
    }).join("");

    const selected = messages.find((message) => message.internal_id === selectedMessageId);
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
    const results = selected.plugin_results?.length
        ? selected.plugin_results.map((item) => `
            <div class="badge-row">
                <span class="badge ${item.handled ? "good" : ""}">${escapeHtml(item.plugin)}</span>
                <span class="badge ${item.stop_processing ? "good" : ""}">${item.handled ? "已处理" : "跳过"}</span>
            </div>
            <div class="detail-meta">${escapeHtml(item.detail || "无额外说明")}</div>
        `).join("")
        : '<div class="empty-state">插件尚未返回处理结果。</div>';

    elements.messageDetail.innerHTML = `
        <div class="detail-head">
            <div>
                <h4 class="detail-title">${escapeHtml(getMessageTitle(selected))}</h4>
            </div>
            <div class="badge-row">
                <span class="badge ${getStatusTone(selected.status)}">${escapeHtml(selected.status)}</span>
                <span class="badge">${escapeHtml(selectedTypeLabel)}</span>
                <span class="badge">${selected.is_group_message ? "群聊" : "单聊"}</span>
            </div>
        </div>
        <div class="detail-section">
            <h5 class="detail-section-title">消息信息</h5>
            <div class="detail-meta">消息 ID：${escapeHtml(selected.msgid || `内部消息 ${selected.internal_id}`)}</div>
            <div class="detail-meta">会话：${escapeHtml(selectedConversation)}</div>
            <div class="detail-meta">发送者：${escapeHtml(selected.sender_display_name || selectedSender)}</div>
            ${selected.is_group_message ? `<div class="detail-meta">群成员：${escapeHtml(selected.room_sender_display_name || selectedSender)}</div>` : ""}
        </div>
        ${shouldShowTextContent ? `<div class="detail-section"><h5 class="detail-section-title">消息内容</h5><div class="detail-text">${escapeHtml(selectedTextContent)}</div></div>` : ""}
        <div class="detail-section">
            <h5 class="detail-section-title">处理时间</h5>
            <div class="detail-meta">接收时间：${escapeHtml(selected.received_at || "未知")}</div>
            <div class="detail-meta">消息时间：${escapeHtml(sourceTimestamp || "上游未提供")}</div>
            <div class="detail-meta">完成时间：${escapeHtml(selected.processed_at || "处理中")}</div>
        </div>
        <div class="detail-section">
            <h5 class="detail-section-title">插件结果</h5>
            <div>${results}</div>
        </div>
        <div class="detail-section">
            <div class="detail-section-head">
                <h5 class="detail-section-title">原始负载</h5>
                <button class="button ghost compact" type="button" data-action="copy-message-payload">复制原始负载</button>
            </div>
            <pre class="code-block">${escapeHtml(rawPayloadText)}</pre>
        </div>
    `;

    return { selectedMessageId };
}

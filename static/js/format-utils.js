/** 日期、时长与文本截断格式化。 */

import { normalizeInlineText } from "./dom-utils.js";

export function formatUnixTimestamp(value) {
    const numericValue = Number(value);
    if (!Number.isFinite(numericValue) || numericValue <= 0) {
        return "";
    }

    const timestamp = numericValue > 1e12 ? numericValue : numericValue * 1000;
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) {
        return "";
    }

    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}:${String(date.getSeconds()).padStart(2, "0")}`;
}

export function formatDuration(totalSeconds) {
    const normalized = Math.max(0, Math.floor(Number(totalSeconds) || 0));
    const hours = Math.floor(normalized / 3600);
    const minutes = Math.floor((normalized % 3600) / 60);
    const seconds = Math.floor(normalized % 60);
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function formatStandardDateTime(value) {
    const normalized = normalizeInlineText(value);
    if (!normalized) {
        return "";
    }
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(normalized)) {
        return normalized;
    }
    const parsed = new Date(normalized);
    if (Number.isNaN(parsed.getTime())) {
        return normalized;
    }
    return `${parsed.getFullYear()}-${String(parsed.getMonth() + 1).padStart(2, "0")}-${String(parsed.getDate()).padStart(2, "0")} ${String(parsed.getHours()).padStart(2, "0")}:${String(parsed.getMinutes()).padStart(2, "0")}:${String(parsed.getSeconds()).padStart(2, "0")}`;
}

export function formatHeartbeatInterval(value) {
    const seconds = Math.max(0, Number(value) || 0);
    return seconds > 0 ? `${seconds} 秒一次` : "已关闭";
}

export function truncateText(value, maxLength = 96) {
    const text = String(value ?? "");
    return text.length <= maxLength ? text : `${text.slice(0, maxLength - 1)}…`;
}

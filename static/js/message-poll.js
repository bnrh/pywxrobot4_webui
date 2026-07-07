/** 消息轮询错误文案与网络异常识别。 */

import { normalizeInlineText } from "./dom-utils.js";

export function isNetworkFetchError(error) {
    const message = normalizeInlineText(error?.message || error);
    return message === "Failed to fetch" || /NetworkError/i.test(message);
}

export function getMessagePollErrorText(error, failureCount) {
    if (isNetworkFetchError(error)) {
        return failureCount > 1
            ? `消息服务仍未连通，正在第 ${failureCount} 次重试...`
            : "消息服务暂时不可用，正在自动重连...";
    }
    return `消息自动刷新失败：${error.message}`;
}

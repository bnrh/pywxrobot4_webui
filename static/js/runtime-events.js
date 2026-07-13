import { buildEventStreamUrl } from "./api.js";
import {
    MESSAGE_POLL_INTERVAL_MS,
    MESSAGE_POLL_INTERVAL_SSE_MS,
    OVERVIEW_POLL_INTERVAL_MS,
    OVERVIEW_POLL_INTERVAL_SSE_MS,
} from "./polling-config.js";

let runtimeEventSource = null;
let runtimeStreamConnected = false;
let lastMessagePollAt = 0;
let lastOverviewPollAt = 0;

export function isRuntimeStreamConnected() {
    return runtimeStreamConnected;
}

export function connectRuntimeEventStream({ onRuntimeEvent }) {
    if (typeof EventSource === "undefined") {
        return;
    }
    if (runtimeEventSource) {
        runtimeEventSource.close();
        runtimeEventSource = null;
    }
    runtimeEventSource = new EventSource(buildEventStreamUrl());
    runtimeEventSource.onopen = () => {
        runtimeStreamConnected = true;
    };
    runtimeEventSource.onmessage = (event) => {
        let payload;
        try {
            payload = JSON.parse(event.data);
        } catch {
            return;
        }
        if (String(payload?.type || "") === "connected") {
            runtimeStreamConnected = true;
        }
        onRuntimeEvent?.(payload);
    };
    runtimeEventSource.onerror = () => {
        runtimeStreamConnected = false;
        runtimeEventSource?.close();
        runtimeEventSource = null;
        window.setTimeout(() => {
            if (document.visibilityState === "hidden") {
                const resumeWhenVisible = () => {
                    if (document.visibilityState !== "visible") {
                        return;
                    }
                    document.removeEventListener("visibilitychange", resumeWhenVisible);
                    connectRuntimeEventStream({ onRuntimeEvent });
                };
                document.addEventListener("visibilitychange", resumeWhenVisible);
                return;
            }
            connectRuntimeEventStream({ onRuntimeEvent });
        }, 5000);
    };
}

export function shouldPollMessages(now = Date.now()) {
    if (runtimeStreamConnected) {
        // SSE 正常时仅靠事件刷新；MESSAGE_POLL_INTERVAL_SSE_MS=0 表示禁用轮询。
        if (!MESSAGE_POLL_INTERVAL_SSE_MS || MESSAGE_POLL_INTERVAL_SSE_MS <= 0) {
            return false;
        }
        if (now - lastMessagePollAt < MESSAGE_POLL_INTERVAL_SSE_MS) {
            return false;
        }
        lastMessagePollAt = now;
        return true;
    }
    if (now - lastMessagePollAt < MESSAGE_POLL_INTERVAL_MS) {
        return false;
    }
    lastMessagePollAt = now;
    return true;
}

export function shouldPollOverview(now = Date.now()) {
    const pollIntervalMs = runtimeStreamConnected ? OVERVIEW_POLL_INTERVAL_SSE_MS : OVERVIEW_POLL_INTERVAL_MS;
    if (now - lastOverviewPollAt < pollIntervalMs) {
        return false;
    }
    lastOverviewPollAt = now;
    return true;
}

/** 测试辅助：重置节流时间戳。 */
export function resetRuntimeEventPollState({ connected = false } = {}) {
    runtimeStreamConnected = Boolean(connected);
    lastMessagePollAt = 0;
    lastOverviewPollAt = 0;
}

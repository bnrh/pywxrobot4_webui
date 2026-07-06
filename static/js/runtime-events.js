import { buildEventStreamUrl } from "./api.js";
import { MESSAGE_POLL_INTERVAL_MS, MESSAGE_POLL_INTERVAL_SSE_MS } from "./polling-config.js";

let runtimeEventSource = null;
let runtimeStreamConnected = false;
let lastMessagePollAt = 0;

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
        onRuntimeEvent?.(payload);
    };
    runtimeEventSource.onerror = () => {
        runtimeStreamConnected = false;
        runtimeEventSource?.close();
        runtimeEventSource = null;
        window.setTimeout(() => connectRuntimeEventStream({ onRuntimeEvent }), 5000);
    };
}

export function shouldPollMessages(now = Date.now()) {
    const pollIntervalMs = runtimeStreamConnected ? MESSAGE_POLL_INTERVAL_SSE_MS : MESSAGE_POLL_INTERVAL_MS;
    if (now - lastMessagePollAt < pollIntervalMs) {
        return false;
    }
    lastMessagePollAt = now;
    return true;
}

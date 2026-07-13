import { mergeOverviewMetrics } from "../../static/js/overview-metrics.js";
import {
    MESSAGE_POLL_INTERVAL_MS,
    OVERVIEW_POLL_INTERVAL_MS,
    OVERVIEW_POLL_INTERVAL_SSE_MS,
} from "../../static/js/polling-config.js";
import {
    resetRuntimeEventPollState,
    shouldPollMessages,
    shouldPollOverview,
} from "../../static/js/runtime-events.js";

resetRuntimeEventPollState({ connected: true });
if (shouldPollMessages()) {
    throw new Error("SSE connected should not poll messages");
}

resetRuntimeEventPollState({ connected: false });
const firstPollAt = MESSAGE_POLL_INTERVAL_MS;
const firstPoll = shouldPollMessages(firstPollAt);
const secondPoll = shouldPollMessages(firstPollAt + MESSAGE_POLL_INTERVAL_MS - 1);
const thirdPoll = shouldPollMessages(firstPollAt + MESSAGE_POLL_INTERVAL_MS);
if (!firstPoll || secondPoll || !thirdPoll) {
    throw new Error("message poll throttle without SSE is incorrect");
}

resetRuntimeEventPollState({ connected: true });
const overviewFirstAt = OVERVIEW_POLL_INTERVAL_SSE_MS;
const overviewFirst = shouldPollOverview(overviewFirstAt);
const overviewSoon = shouldPollOverview(overviewFirstAt + OVERVIEW_POLL_INTERVAL_SSE_MS - 1);
const overviewLater = shouldPollOverview(overviewFirstAt + OVERVIEW_POLL_INTERVAL_SSE_MS);
if (!overviewFirst || overviewSoon || !overviewLater) {
    throw new Error("overview poll throttle with SSE is incorrect");
}

resetRuntimeEventPollState({ connected: false });
const overviewFallbackAt = OVERVIEW_POLL_INTERVAL_MS;
const overviewFallbackFirst = shouldPollOverview(overviewFallbackAt);
const overviewFallbackSoon = shouldPollOverview(overviewFallbackAt + OVERVIEW_POLL_INTERVAL_MS - 1);
if (!overviewFallbackFirst || overviewFallbackSoon) {
    throw new Error("overview poll throttle without SSE is incorrect");
}

const merged = mergeOverviewMetrics(
    {
        queued_messages: 1,
        worker_count: 2,
        queue_size: 50,
        heartbeat: { enabled: true, healthy: true },
        runtime_metrics: { workers_active: 2, recent_messages: 3 },
    },
    {
        queued_messages: 4,
        workers_active: 1,
        workers_configured: 3,
        recent_messages: 9,
        queue_capacity: 80,
        heartbeat_healthy: false,
        wxrobot_api_reachable: true,
    },
);

if (merged.queued_messages !== 4) {
    throw new Error(`expected queued_messages=4, got ${merged.queued_messages}`);
}
if (merged.worker_count !== 3 || merged.queue_size !== 80) {
    throw new Error("overview top-level fields were not patched");
}
if (merged.runtime_metrics.workers_active !== 1 || merged.runtime_metrics.recent_messages !== 9) {
    throw new Error("runtime_metrics were not patched");
}
if (merged.heartbeat.healthy !== false || merged.heartbeat.wxrobot_api_reachable !== true) {
    throw new Error("heartbeat metrics were not patched");
}
if (merged.heartbeat.enabled !== true) {
    throw new Error("existing heartbeat fields should be preserved");
}

console.log("runtime polling / overview metrics tests passed");

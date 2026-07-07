import { buildOverviewCards } from "../../static/js/overview-cards.js";

const overview = {
    enabled_plugin_count: 2,
    loaded_plugin_count: 2,
    queued_messages: 0,
    pending_restart_fields: [],
    uptime_seconds: 3600,
    runtime_started_at: "2026-07-07T10:00:00",
    worker_count: 4,
    queue_size: 100,
    heartbeat: {
        enabled: true,
        healthy: true,
        interval_seconds: 60,
    },
    runtime_metrics: {
        workers_active: 4,
        workers_configured: 4,
        queue_rejections: 2,
        recent_messages: 10,
        recent_plugin_logs: 5,
        queue_capacity: 100,
        queue_enqueue_wait_seconds: 0.5,
    },
};

const cards = buildOverviewCards(overview, Date.now());
const labels = cards.map((card) => card.label);

if (cards.length < 11) {
    throw new Error(`expected at least 11 cards, got ${cards.length}`);
}

for (const label of ["工作线程", "队列拒绝", "最近消息缓冲", "插件日志缓冲"]) {
    if (!labels.includes(label)) {
        throw new Error(`missing overview card: ${label}`);
    }
}

const rejectionCard = cards.find((card) => card.label === "队列拒绝");
if (rejectionCard?.value !== "2") {
    throw new Error(`unexpected queue rejection card value: ${rejectionCard?.value}`);
}

console.log("overview-cards ok");

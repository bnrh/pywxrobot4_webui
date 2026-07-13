/** 将 SSE 推送的运行时指标合并进概览状态（不重置 overviewFetchedAt）。 */

export function mergeOverviewMetrics(overview, metrics) {
    if (!overview || typeof overview !== "object") {
        return overview;
    }
    if (!metrics || typeof metrics !== "object") {
        return overview;
    }

    const runtimeMetrics = {
        ...(overview.runtime_metrics && typeof overview.runtime_metrics === "object" ? overview.runtime_metrics : {}),
    };
    if (metrics.workers_active !== undefined) {
        runtimeMetrics.workers_active = Number(metrics.workers_active) || 0;
    }
    if (metrics.workers_configured !== undefined) {
        runtimeMetrics.workers_configured = Number(metrics.workers_configured) || 0;
    }
    if (metrics.queue_rejections !== undefined) {
        runtimeMetrics.queue_rejections = Number(metrics.queue_rejections) || 0;
    }
    if (metrics.recent_messages !== undefined) {
        runtimeMetrics.recent_messages = Number(metrics.recent_messages) || 0;
    }
    if (metrics.recent_plugin_logs !== undefined) {
        runtimeMetrics.recent_plugin_logs = Number(metrics.recent_plugin_logs) || 0;
    }
    if (metrics.queue_capacity !== undefined) {
        runtimeMetrics.queue_capacity = Number(metrics.queue_capacity) || 0;
    }
    if (metrics.queue_enqueue_wait_seconds !== undefined) {
        runtimeMetrics.queue_enqueue_wait_seconds = Number(metrics.queue_enqueue_wait_seconds) || 0;
    }

    const heartbeat = {
        ...(overview.heartbeat && typeof overview.heartbeat === "object" ? overview.heartbeat : {}),
    };
    if (metrics.heartbeat_healthy !== undefined) {
        heartbeat.healthy = metrics.heartbeat_healthy;
    }
    if (metrics.wxrobot_api_reachable !== undefined) {
        heartbeat.wxrobot_api_reachable = metrics.wxrobot_api_reachable;
    }

    const next = {
        ...overview,
        runtime_metrics: runtimeMetrics,
        heartbeat,
    };
    if (metrics.queued_messages !== undefined) {
        next.queued_messages = Number(metrics.queued_messages) || 0;
    }
    if (metrics.workers_configured !== undefined) {
        next.worker_count = Number(metrics.workers_configured) || 0;
    }
    if (metrics.queue_capacity !== undefined) {
        next.queue_size = Number(metrics.queue_capacity) || 0;
    }
    return next;
}

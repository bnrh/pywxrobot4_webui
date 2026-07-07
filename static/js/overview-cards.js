/** 仪表盘概览卡片数据组装。 */

import { formatDuration, formatHeartbeatInterval, formatStandardDateTime } from "./format-utils.js";

export function buildOverviewCards(overview, overviewFetchedAt = Date.now()) {
    const enabledCount = Number(overview.enabled_plugin_count || 0);
    const loadedCount = Number(overview.loaded_plugin_count || 0);
    const queuedMessages = Number(overview.queued_messages || 0);
    const pendingRestartFields = overview.pending_restart_fields || [];
    const elapsedSeconds = Math.max(0, Math.floor((Date.now() - (overviewFetchedAt || Date.now())) / 1000));
    const uptimeSeconds = Math.max(0, Number(overview.uptime_seconds || 0) + elapsedSeconds);
    const requiresRestart = pendingRestartFields.length > 0;
    const runtimeStartedAt = formatStandardDateTime(overview.runtime_started_at) || "未知";
    const heartbeat = overview.heartbeat || {};
    const heartbeatEnabled = Boolean(heartbeat.enabled);
    const heartbeatHealthy = heartbeat.healthy;
    const heartbeatStatus = !heartbeatEnabled
        ? "已关闭"
        : heartbeatHealthy === false
            ? "异常"
            : heartbeatHealthy === true
                ? "正常"
                : "检测中";
    const heartbeatHint = heartbeatEnabled
        ? `${formatHeartbeatInterval(heartbeat.interval_seconds)}${heartbeat.last_checked_at ? ` · 最近 ${formatStandardDateTime(heartbeat.last_checked_at)}` : ""}`
        : "设置为 0 时保持关闭";
    const runtimeMetrics = overview.runtime_metrics || {};
    const workersActive = Number(runtimeMetrics.workers_active ?? 0);
    const workersConfigured = Number(runtimeMetrics.workers_configured ?? overview.worker_count ?? 0);
    const queueRejections = Number(runtimeMetrics.queue_rejections ?? 0);
    const recentMessages = Number(runtimeMetrics.recent_messages ?? 0);
    const recentPluginLogs = Number(runtimeMetrics.recent_plugin_logs ?? 0);
    const queueCapacity = Number(runtimeMetrics.queue_capacity ?? overview.queue_size ?? 0);
    const enqueueWaitSeconds = Number(runtimeMetrics.queue_enqueue_wait_seconds ?? 0);

    const cards = [
        {
            label: "运行时间",
            value: formatDuration(uptimeSeconds),
            hint: "从 WebUI 服务启动时开始累计，并每秒自动刷新",
            tone: "sky",
        },
        {
            label: "启动时间",
            value: runtimeStartedAt,
            hint: "WebUI 服务启动时间",
            tone: "teal",
            valueClass: "is-compact",
        },
        {
            label: "心跳检测",
            value: heartbeatStatus,
            hint: heartbeatHint,
            tone: heartbeatEnabled && heartbeatHealthy === false ? "amber" : "teal",
        },
        {
            label: "已启用插件",
            value: String(enabledCount),
            hint: "来自当前配置的启用数量",
            tone: "teal",
        },
        {
            label: "成功加载",
            value: String(loadedCount),
            hint: loadedCount === enabledCount ? "运行时插件已全部在线" : "仍有插件未进入运行态",
            tone: loadedCount === enabledCount ? "sky" : "amber",
        },
        {
            label: "待处理消息",
            value: String(queuedMessages),
            hint: queuedMessages > 0 ? "队列中仍有消息等待消费" : "消息流当前没有堆积",
            tone: queuedMessages > 0 ? "amber" : "teal",
        },
        {
            label: "重启变更",
            value: String(pendingRestartFields.length),
            hint: requiresRestart ? "部分设置待重启后生效" : "当前运行态与配置保持同步",
            tone: requiresRestart ? "amber" : "sky",
        },
        {
            label: "工作线程",
            value: `${workersActive}/${workersConfigured}`,
            hint: workersActive === workersConfigured ? "全部 worker 正在运行" : "部分 worker 未启动或已退出",
            tone: workersActive === workersConfigured && workersConfigured > 0 ? "teal" : "amber",
        },
        {
            label: "队列拒绝",
            value: String(queueRejections),
            hint: queueRejections > 0
                ? `队列满时等待 ${enqueueWaitSeconds}s 后仍无法入队`
                : "尚未记录队列拒绝事件",
            tone: queueRejections > 0 ? "amber" : "teal",
        },
        {
            label: "最近消息缓冲",
            value: String(recentMessages),
            hint: queueCapacity ? `队列容量 ${queueCapacity} · 内存保留最近消息供 UI 展示` : "内存保留最近消息供 UI 展示",
            tone: "sky",
        },
        {
            label: "插件日志缓冲",
            value: String(recentPluginLogs),
            hint: "内存与 SQLite 保留的最近插件日志条数",
            tone: "sky",
        },
    ];
    return cards;
}
